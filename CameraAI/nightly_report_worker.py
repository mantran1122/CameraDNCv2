"""
Nightly Automated Video Analysis & Per-Camera Daily Report Worker (22:00 -> 04:00).

Implements the Rolling 22:00 Cutoff Window:
- Report Date D covers events from (D - 1 day) 22:00:00 to D 21:59:59.
- Events occurring at or after 22:00:00 on Day D are automatically rolled into Day D+1.
- Runs automatically between 22:00 and 04:00 (or on-demand via Admin/Manager trigger).
- Saves concise per-camera reports (.json and .md) in storage/nightly_reports/YYYY-MM-DD/.
"""

import json
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
import database
from clip_storage import resolve_clip_path


EVENT_VI_LABELS = {
    "Intrusion": "Đột nhập vùng cấm",
    "CrossLine": "Vượt rào / đường cảnh báo",
    "Fight": "Xô xát / Đánh nhau",
    "AudioMutation": "Âm thanh đột biến lớn",
    "AudioAnomaly": "Bất thường âm thanh",
    "SoundDetection": "Phát hiện tiếng động lạ",
    "HumanTrait": "Phát hiện người",
    "FaceDetection": "Nhận diện khuôn mặt",
    "VehicleTrait": "Phát hiện phương tiện",
    "VideoMotion": "Chuyển động",
    "RtspSessionDisconnect": "Mất kết nối luồng RTSP",
}


def compute_rolling_window(report_date_str: str) -> Tuple[str, str, str]:
    """Return (normalized_date_str, start_ts, end_ts) for the 22:00 rolling cutoff window.
    For report_date_str = '2026-10-12':
      start_ts = '2026-10-11 22:00:00'
      end_ts   = '2026-10-12 21:59:59'
    """
    try:
        target_dt = datetime.strptime(report_date_str.strip(), "%Y-%m-%d").date()
    except Exception:
        target_dt = date.today()

    prev_dt = target_dt - timedelta(days=1)
    cutoff_h = getattr(config, "NIGHTLY_CUTOFF_HOUR", 22)
    start_ts = f"{prev_dt.strftime('%Y-%m-%d')} {cutoff_h:02d}:00:00"
    end_ts = f"{target_dt.strftime('%Y-%m-%d')} {cutoff_h - 1:02d}:59:59"
    return target_dt.strftime("%Y-%m-%d"), start_ts, end_ts


def default_report_date_for_now(now: Optional[datetime] = None) -> str:
    """Determine which report date should be processed at a given timestamp.
    - If current time is >= 22:00 on Day D, the window for Day D just closed -> process Day D.
    - If current time is < 22:00 on Day D (e.g. 00:00 -> 04:00 AM or daytime), the most recently
      closed full 22:00 window is Day (D - 1), unless there are already events today and user
      explicitly asks for today. For automatic 22:00-04:00 scheduling:
        * 22:00..23:59 -> today
        * 00:00..04:00 -> yesterday
    """
    now = now or datetime.now()
    if now.hour >= getattr(config, "NIGHTLY_CUTOFF_HOUR", 22):
        return now.strftime("%Y-%m-%d")
    return (now.date() - timedelta(days=1)).strftime("%Y-%m-%d")


def _classify_shift(ts_str: str) -> str:
    """Map an event timestamp ('YYYY-MM-DD HH:MM:SS') into one of the 4 consecutive shifts:
    - shift_1_night:   22:00 (D-1) -> 05:59:59 (D)
    - shift_2_morning: 06:00 (D)   -> 11:59:59 (D)
    - shift_3_afternoon: 12:00 (D) -> 17:59:59 (D)
    - shift_4_evening: 18:00 (D)   -> 21:59:59 (D)
    """
    try:
        time_part = ts_str.split(" ")[1] if " " in ts_str else ts_str.split("T")[1][:8]
        hour = int(time_part.split(":")[0])
    except Exception:
        hour = 12

    if hour >= 22 or hour < 6:
        return "shift_1_night"
    elif 6 <= hour < 12:
        return "shift_2_morning"
    elif 12 <= hour < 18:
        return "shift_3_afternoon"
    else:
        return "shift_4_evening"


SHIFT_META = {
    "shift_1_night": {
        "key": "shift_1_night",
        "title": "Ca Đêm (22:00 hôm trước → 06:00 sáng)",
        "icon": "",
        "short_label": "22:00 - 06:00",
    },
    "shift_2_morning": {
        "key": "shift_2_morning",
        "title": "Ca Sáng (06:00 → 12:00 trưa)",
        "icon": "",
        "short_label": "06:00 - 12:00",
    },
    "shift_3_afternoon": {
        "key": "shift_3_afternoon",
        "title": "Ca Chiều (12:00 → 18:00 chiều)",
        "icon": "",
        "short_label": "12:00 - 18:00",
    },
    "shift_4_evening": {
        "key": "shift_4_evening",
        "title": "Ca Tối (18:00 → 22:00 tối)",
        "icon": "",
        "short_label": "18:00 - 22:00",
    },
}


class NightlyReportWorker:
    def __init__(self) -> None:
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._active_job: Optional[Dict[str, Any]] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="nightly-report-worker",
        )
        self._thread.start()
        print("[NIGHTLY REPORT] Worker scheduled for window 22:00 -> 04:00 (Rolling cutoff 22:00).")

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None

    def get_active_job(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._active_job) if self._active_job else None

    def trigger_async(
        self,
        report_date_str: Optional[str] = None,
        max_vlm_clips: int = 8,
        use_llm_narrative: bool = True,
        triggered_by: str = "manual",
    ) -> Dict[str, Any]:
        """Trigger report generation asynchronously in a background thread."""
        with self._lock:
            if self._active_job and self._active_job.get("status") == "running":
                return dict(self._active_job)

        if not report_date_str:
            # If triggered manually during the day and today already has events, use today;
            # otherwise use the default closed window date.
            today_str = date.today().strftime("%Y-%m-%d")
            _, s_today, e_today = compute_rolling_window(today_str)
            today_events = database.get_events_in_rolling_window(s_today, e_today)
            if today_events:
                report_date_str = today_str
            else:
                report_date_str = default_report_date_for_now()

        norm_date, start_ts, end_ts = compute_rolling_window(report_date_str)
        job_info = {
            "report_date": norm_date,
            "window_start": start_ts,
            "window_end": end_ts,
            "status": "running",
            "phase": "initializing",
            "triggered_by": triggered_by,
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "processed_cameras": 0,
            "total_cameras": 32,
            "vlm_analyzed_clips": 0,
        }
        with self._lock:
            self._active_job = job_info

        t = threading.Thread(
            target=self._run_job_safe,
            args=(norm_date, max_vlm_clips, use_llm_narrative, triggered_by),
            daemon=True,
            name=f"nightly-job-{norm_date}",
        )
        t.start()
        return job_info

    def _scheduler_loop(self) -> None:
        """Background daemon that wakes up every 45 seconds and checks if current time is within
        the 22:00 -> 04:00 nightly window and whether the target report has been completed.
        """
        while self._running.is_set():
            try:
                now = datetime.now()
                start_h = getattr(config, "NIGHTLY_START_HOUR", 22)
                end_h = getattr(config, "NIGHTLY_END_HOUR", 4)
                in_nightly_window = (now.hour >= start_h) or (now.hour < end_h)

                if in_nightly_window:
                    target_date = default_report_date_for_now(now)
                    report_dir = config.NIGHTLY_REPORT_DIR / target_date
                    status_file = report_dir / "_job_status.json"
                    already_done = False
                    if status_file.is_file():
                        try:
                            st = json.loads(status_file.read_text(encoding="utf-8"))
                            if st.get("status") == "completed":
                                already_done = True
                        except Exception:
                            pass

                    with self._lock:
                        is_busy = bool(self._active_job and self._active_job.get("status") == "running")

                    if not already_done and not is_busy:
                        print(f"[NIGHTLY REPORT] Auto-starting 22:00-04:00 analysis for report date {target_date}")
                        self.trigger_async(
                            report_date_str=target_date,
                            max_vlm_clips=24,
                            use_llm_narrative=True,
                            triggered_by="auto_scheduler_22h_04h",
                        )
            except Exception as exc:
                print(f"[NIGHTLY REPORT] Scheduler check error: {exc}")

            for _ in range(45):
                if not self._running.is_set():
                    break
                time.sleep(1.0)

    def _update_job_status(self, report_dir: Path, **updates: Any) -> Dict[str, Any]:
        with self._lock:
            if self._active_job is None:
                self._active_job = {}
            self._active_job.update(updates)
            self._active_job["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            snapshot = dict(self._active_job)

        try:
            report_dir.mkdir(parents=True, exist_ok=True)
            status_file = report_dir / "_job_status.json"
            status_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[NIGHTLY REPORT] Failed writing _job_status.json: {exc}")
        return snapshot

    def _run_job_safe(
        self,
        report_date_str: str,
        max_vlm_clips: int,
        use_llm_narrative: bool,
        triggered_by: str,
    ) -> None:
        norm_date, start_ts, end_ts = compute_rolling_window(report_date_str)
        report_dir = config.NIGHTLY_REPORT_DIR / norm_date
        try:
            self._execute_pipeline(
                norm_date=norm_date,
                start_ts=start_ts,
                end_ts=end_ts,
                report_dir=report_dir,
                max_vlm_clips=max_vlm_clips,
                use_llm_narrative=use_llm_narrative,
                triggered_by=triggered_by,
            )
        except Exception as exc:
            print(f"[NIGHTLY REPORT] Job failed for {norm_date}: {exc}")
            self._update_job_status(
                report_dir,
                status="failed",
                phase="error",
                error_message=str(exc),
                completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )

    def _execute_pipeline(
        self,
        norm_date: str,
        start_ts: str,
        end_ts: str,
        report_dir: Path,
        max_vlm_clips: int,
        use_llm_narrative: bool,
        triggered_by: str,
    ) -> None:
        report_dir.mkdir(parents=True, exist_ok=True)
        camera_names = getattr(config, "CAMERA_NAMES", {}) or {}
        all_channels = sorted({int(k) for k in camera_names.keys() if str(k).isdigit()} | set(range(1, 33)))

        self._update_job_status(
            report_dir,
            report_date=norm_date,
            window_start=start_ts,
            window_end=end_ts,
            status="running",
            phase="tier1_fetching_events",
            triggered_by=triggered_by,
            total_cameras=len(all_channels),
            processed_cameras=0,
        )

        # Fetch all events in the rolling 22:00 D-1 -> 21:59:59 D window
        events = database.get_events_in_rolling_window(start_ts, end_ts)

        # Tier 1: Enrich unanalyzed priority video clips with VLM if within time budget
        self._update_job_status(report_dir, phase="tier1_vlm_enrichment", total_events_in_window=len(events))
        vlm_count = self._enrich_unanalyzed_clips(events, report_dir, max_vlm_clips=max_vlm_clips)

        # Re-fetch events so newly completed video_analyses summaries are included
        if vlm_count > 0:
            events = database.get_events_in_rolling_window(start_ts, end_ts)

        # Group events by camera channel
        events_by_channel: Dict[int, List[Dict[str, Any]]] = {ch: [] for ch in all_channels}
        for ev in events:
            ch = int(ev.get("channel") or 1)
            events_by_channel.setdefault(ch, []).append(ev)

        # Tier 2 & Tier 3: Map-Reduce per Camera & Save Reports
        self._update_job_status(report_dir, phase="tier2_tier3_generating_camera_reports", vlm_analyzed_clips=vlm_count)

        camera_summaries_index: List[Dict[str, Any]] = []
        total_anomalies_all = 0
        high_risk_cameras: List[int] = []
        active_cameras_count = 0
        allow_checkpoint_resume = str(triggered_by or "").startswith("auto")

        for idx, ch in enumerate(all_channels, start=1):
            ch_events = events_by_channel.get(ch, [])
            cam_name = camera_names.get(str(ch), f"Camera Kênh {ch:02d}")
            cam_code = f"cam_{ch:02d}"
            json_path = report_dir / f"{cam_code}.json"
            md_path = report_dir / f"{cam_code}.md"

            cam_report: Optional[Dict[str, Any]] = None
            if allow_checkpoint_resume and json_path.is_file() and md_path.is_file():
                try:
                    cached = json.loads(json_path.read_text(encoding="utf-8"))
                    if (
                        isinstance(cached, dict)
                        and cached.get("report_date") == norm_date
                        and int(cached.get("total_events", -1)) == len(ch_events)
                        and cached.get("executive_summary")
                    ):
                        cam_report = cached
                except Exception:
                    cam_report = None

            if cam_report is None:
                cam_report = self._build_single_camera_report(
                    channel=ch,
                    cam_name=cam_name,
                    report_date=norm_date,
                    window_start=start_ts,
                    window_end=end_ts,
                    events=ch_events,
                    use_llm_narrative=use_llm_narrative,
                )
                # Save cam_XX.json and cam_XX.md checkpoint immediately
                json_path.write_text(json.dumps(cam_report, ensure_ascii=False, indent=2), encoding="utf-8")
                md_path.write_text(cam_report["markdown_content"], encoding="utf-8")

            if cam_report["total_events"] > 0:
                active_cameras_count += 1
            total_anomalies_all += cam_report["anomaly_count"]
            if cam_report["risk_level"] == "high":
                high_risk_cameras.append(ch)

            camera_summaries_index.append({
                "channel": ch,
                "camera_code": f"D{ch}",
                "camera_name": cam_name,
                "total_events": cam_report["total_events"],
                "anomaly_count": cam_report["anomaly_count"],
                "critical_count": cam_report["critical_count"],
                "human_count": cam_report["human_count"],
                "vehicle_count": cam_report["vehicle_count"],
                "clip_count": cam_report["clip_count"],
                "risk_level": cam_report["risk_level"],
                "risk_label": cam_report["risk_label"],
                "peak_hour_label": cam_report["peak_hour_label"],
                "executive_summary": cam_report["executive_summary"],
                "json_file": f"{cam_code}.json",
                "md_file": f"{cam_code}.md",
                "updated_at": cam_report["generated_at"],
            })

            self._update_job_status(
                report_dir,
                processed_cameras=idx,
                current_channel=ch,
            )

        nas_path_str = ""
        try:
            import synology_storage
            if synology_storage.enabled():
                nas_path_str = synology_storage.remote_report_path(norm_date)
        except Exception:
            pass

        master_summary = {
            "report_date": norm_date,
            "window_start": start_ts,
            "window_end": end_ts,
            "cutoff_rule": "Video từ 22:00 hôm trước đến 21:59:59 hôm nay (Video từ 22:00 tối nay đẩy sang báo cáo ngày mai)",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "triggered_by": triggered_by,
            "total_cameras": len(all_channels),
            "active_cameras": active_cameras_count,
            "total_events": len(events),
            "total_anomalies": total_anomalies_all,
            "vlm_analyzed_clips": vlm_count,
            "high_risk_channels": high_risk_cameras,
            "nas_synced": False,
            "nas_path": nas_path_str,
            "cameras": camera_summaries_index,
        }

        master_file = report_dir / "_daily_master_summary.json"
        master_file.write_text(json.dumps(master_summary, ensure_ascii=False, indent=2), encoding="utf-8")

        # Mirror daily report folder (.json and .md files) to Synology NAS if enabled
        nas_synced = False
        try:
            import synology_storage
            if synology_storage.enabled():
                self._update_job_status(report_dir, phase="syncing_to_nas")
                sync_res = synology_storage.upload_nightly_report_dir(norm_date, report_dir)
                if sync_res.get("uploaded", 0) > 0:
                    nas_synced = True
                    master_summary["nas_synced"] = True
                    master_summary["nas_path"] = sync_res.get("remote_dir") or nas_path_str
                    master_file.write_text(json.dumps(master_summary, ensure_ascii=False, indent=2), encoding="utf-8")
                    synology_storage.upload_nightly_report_dir(norm_date, report_dir)
                    print(f"[NIGHTLY REPORT] Mirrored {sync_res.get('uploaded')} report files to Synology NAS: {master_summary['nas_path']}")
        except Exception as exc:
            print(f"[NIGHTLY REPORT] Synology NAS sync warning for {norm_date}: {exc}")

        self._update_job_status(
            report_dir,
            status="completed",
            phase="completed",
            processed_cameras=len(all_channels),
            total_events_in_window=len(events),
            total_anomalies=total_anomalies_all,
            active_cameras=active_cameras_count,
            nas_synced=nas_synced,
            nas_path=master_summary["nas_path"],
            completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        print(
            f"[NIGHTLY REPORT] Completed report {norm_date} ({start_ts} -> {end_ts}): "
            f"{len(events)} events across {active_cameras_count}/{len(all_channels)} active cameras (NAS synced={nas_synced})."
        )

    def _enrich_unanalyzed_clips(
        self,
        events: List[Dict[str, Any]],
        report_dir: Path,
        max_vlm_clips: int = 8,
    ) -> int:
        """Run dense VLM analysis on priority clips that have not been analyzed yet,
        respecting the 03:15 AM nightly deadline guardrail.
        """
        if max_vlm_clips <= 0:
            return 0

        candidates: List[Dict[str, Any]] = []
        for ev in events:
            clip_ref = str(ev.get("clip_filename") or "").strip()
            if not clip_ref:
                continue
            if ev.get("video_analysis_status") == "completed" and ev.get("video_analysis_summary"):
                continue
            try:
                clip_path = resolve_clip_path(clip_ref, fetch_remote=False)
                if not clip_path or not clip_path.is_file():
                    continue
            except Exception:
                continue
            candidates.append(ev)

        if not candidates:
            return 0

        # Prioritize critical anomaly codes first
        critical_codes = set(getattr(config, "CRITICAL_ANOMALY_CODES", []))
        candidates.sort(
            key=lambda x: (
                0 if x.get("event_code") in critical_codes else 1,
                0 if x.get("severity") == "high" else 1,
                -(int(x.get("id") or 0)),
            )
        )

        analyzed = 0
        for ev in candidates[:max_vlm_clips]:
            # Time-budget guardrail: if running in early morning and past 03:15 AM, move to Reduce phase
            now = datetime.now()
            if now.hour == 3 and now.minute >= 15:
                print("[NIGHTLY REPORT] Reached 03:15 AM guardrail; stopping individual clip VLM scan to finalize reports.")
                break

            event_id = int(ev["id"])
            clip_path = resolve_clip_path(str(ev["clip_filename"]), fetch_remote=False)
            if not clip_path or not clip_path.is_file():
                continue

            try:
                from qwen_vision_client import analyze_video_dense

                prompt = (
                    f"Phân tích ngắn gọn sự kiện camera an ninh Kênh {ev.get('channel')} "
                    f"({ev.get('event_code')}, Sự kiện #{event_id}) lúc {ev.get('timestamp')}: "
                    f"Mô tả đối tượng, hành động chính trong video và đánh giá mức độ an ninh."
                )
                res = analyze_video_dense(clip_path, prompt=prompt, num_frames=min(6, config.DENSE_FRAMES_COUNT))
                reply_text = (res.get("reply") or "").strip()
                if reply_text:
                    lowered = reply_text.lower()
                    if any(k in lowered for k in ["nguy hiểm", "đột nhập", "xô xát", "đánh nhau", "cháy"]):
                        risk_level = "high"
                    elif any(k in lowered for k in ["nghi vấn", "bất thường", "chú ý", "cảnh báo"]):
                        risk_level = "medium"
                    else:
                        risk_level = "low"

                    database.update_video_analysis(
                        event_id,
                        status="completed",
                        summary=reply_text,
                        risk_level=risk_level,
                        events=[{"event": ev.get("event_code"), "detail": reply_text[:140]}],
                        frames=[],
                        video_model="Nightly VLM Worker (22h-04h)",
                        analyzed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                    )
                    analyzed += 1
                    self._update_job_status(report_dir, vlm_analyzed_clips=analyzed)
            except Exception as exc:
                print(f"[NIGHTLY REPORT] VLM analysis skipped for event #{event_id}: {exc}")

        return analyzed

    def _build_single_camera_report(
        self,
        channel: int,
        cam_name: str,
        report_date: str,
        window_start: str,
        window_end: str,
        events: List[Dict[str, Any]],
        use_llm_narrative: bool = True,
    ) -> Dict[str, Any]:
        """Build structured JSON and concise Markdown report for a single camera across the 4 consecutive shifts."""
        total_events = len(events)
        critical_codes = set(getattr(config, "CRITICAL_ANOMALY_CODES", []))

        anomalies: List[Dict[str, Any]] = []
        critical_events: List[Dict[str, Any]] = []
        human_count = 0
        vehicle_count = 0
        clip_count = 0
        hourly_counts = [0] * 24

        shifts: Dict[str, List[Dict[str, Any]]] = {
            "shift_1_night": [],
            "shift_2_morning": [],
            "shift_3_afternoon": [],
            "shift_4_evening": [],
        }

        for ev in events:
            code = str(ev.get("event_code") or "")
            etype = str(ev.get("event_type") or "")
            sev = str(ev.get("severity") or "info").lower()
            ts = str(ev.get("timestamp") or "")

            if ev.get("clip_filename"):
                clip_count += 1

            if code in ("HumanTrait", "FaceDetection", "SmartMotionHuman"):
                human_count += 1
            elif code in ("VehicleTrait", "SmartMotionVehicle"):
                vehicle_count += 1

            is_anom = (
                code in critical_codes
                or etype in ("video_anomaly", "audio_anomaly")
                or config.is_channel_anomaly(channel, code)
            )
            if is_anom and code != "VideoMotion":
                anomalies.append(ev)
                if code in critical_codes or sev == "high":
                    critical_events.append(ev)

            try:
                t_part = ts.split(" ")[1] if " " in ts else ts.split("T")[1][:8]
                h = int(t_part.split(":")[0])
                if 0 <= h < 24:
                    hourly_counts[h] += 1
            except Exception:
                pass

            s_key = _classify_shift(ts)
            shifts[s_key].append(ev)

        if total_events > 0 and max(hourly_counts) > 0:
            peak_h = hourly_counts.index(max(hourly_counts))
            peak_hour_label = f"{peak_h:02d}:00 - {(peak_h + 1) % 24:02d}:00 ({max(hourly_counts)} sự kiện)"
        else:
            peak_hour_label = "Không có khung giờ cao điểm"

        # Risk assessment
        if len(critical_events) > 0:
            risk_level = "high"
            risk_label = "NGHIÊM TRỌNG — CÓ CẢNH BÁO AN NINH"
            risk_badge = "CẢNH BÁO CAO (HIGH RISK)"
        elif len(anomalies) > 0 or shifts["shift_1_night"]:
            risk_level = "medium"
            risk_label = "CẦN CHÚ Ý (CÓ HOẠT ĐỘNG ĐÊM / CẢNH BÁO NHẸ)"
            risk_badge = "CẦN CHÚ Ý (MEDIUM RISK)"
        elif total_events > 0:
            risk_level = "low"
            risk_label = "AN TOÀN — HOẠT ĐỘNG THƯỜNG NHẬT"
            risk_badge = "BÌNH THƯỜNG (NORMAL)"
        else:
            risk_level = "none"
            risk_label = "YÊN TĨNH — KHÔNG GHI NHẬN SỰ KIỆN"
            risk_badge = "YÊN TĨNH (NO ACTIVITY)"

        # Build shift breakdown summaries
        shift_summaries: List[Dict[str, Any]] = []
        for s_key in ["shift_1_night", "shift_2_morning", "shift_3_afternoon", "shift_4_evening"]:
            meta = SHIFT_META[s_key]
            s_events = shifts[s_key]
            s_anom = [
                e for e in s_events
                if (e.get("event_code") in critical_codes or e.get("event_type") in ("video_anomaly", "audio_anomaly"))
                and e.get("event_code") != "VideoMotion"
            ]
            s_human = sum(1 for e in s_events if e.get("event_code") in ("HumanTrait", "FaceDetection"))
            s_vehicle = sum(1 for e in s_events if e.get("event_code") in ("VehicleTrait",))

            if not s_events:
                text = "Không ghi nhận chuyển động hay sự kiện nào. Khu vực yên tĩnh."
            else:
                first_ts = str(s_events[0].get("timestamp") or "").split(" ")[-1]
                last_ts = str(s_events[-1].get("timestamp") or "").split(" ")[-1]
                parts = [
                    f"Ghi nhận **{len(s_events)}** sự kiện (từ `{first_ts}` đến `{last_ts}`): "
                    f"{s_human} lượt người, {s_vehicle} phương tiện."
                ]
                if s_anom:
                    import re
                    notable_strs = []
                    for ae in s_anom[:3]:
                        lbl = EVENT_VI_LABELS.get(str(ae.get("event_code")), str(ae.get("event_code")))
                        ai_sum = (ae.get("video_analysis_summary") or ae.get("description") or "").strip()
                        if len(ai_sum) > 140:
                            ai_sum = ai_sum[:137] + "..."
                        ae_ts = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", r"\3/\2/\1", str(ae.get("timestamp") or ""))
                        notable_strs.append(f"`{ae_ts}` [#{ae.get('id')} - {lbl}]: {ai_sum}")
                    parts.append("Sự kiện đáng chú ý: " + "; ".join(notable_strs))
                else:
                    # Check if any event has VLM analysis summary
                    vlm_evs = [e for e in s_events if e.get("video_analysis_summary")]
                    if vlm_evs:
                        sample_sum = str(vlm_evs[0].get("video_analysis_summary")).strip()
                        if len(sample_sum) > 140:
                            sample_sum = sample_sum[:137] + "..."
                        parts.append(f"Ghi chú AI Vision (#{vlm_evs[0].get('id')}): {sample_sum}")
                    else:
                        parts.append("Hoạt động di chuyển thường nhật, không có dấu hiệu bất thường.")
                text = " ".join(parts)

            shift_summaries.append({
                "shift_key": s_key,
                "title": meta["title"],
                "icon": meta["icon"],
                "short_label": meta["short_label"],
                "event_count": len(s_events),
                "anomaly_count": len(s_anom),
                "human_count": s_human,
                "vehicle_count": s_vehicle,
                "summary_text": text,
            })

        # Highlighted / Notable clips list (up to 12 most important events with clips)
        notable_events_sorted = sorted(
            events,
            key=lambda e: (
                0 if e.get("event_code") in critical_codes else (1 if e in anomalies else 2),
                0 if e.get("video_analysis_summary") else 1,
                0 if e.get("clip_filename") else 1,
                -(int(e.get("id") or 0)),
            ),
        )[:12]

        import re
        def _vn_dt(val: Any) -> str:
            return re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", r"\3/\2/\1", str(val or ""))

        notable_items: List[Dict[str, Any]] = []
        for ev in notable_events_sorted:
            clip_fn = str(ev.get("clip_filename") or "").strip()
            clip_url = f"/clips/{clip_fn}" if clip_fn else ""
            code = str(ev.get("event_code") or "")
            notable_items.append({
                "id": ev.get("id"),
                "timestamp": _vn_dt(ev.get("timestamp")),
                "event_code": code,
                "event_label": EVENT_VI_LABELS.get(code, code),
                "severity": ev.get("severity") or "info",
                "description": _vn_dt(ev.get("description") or ""),
                "ai_summary": _vn_dt(ev.get("video_analysis_summary") or ""),
                "audio_transcript": ev.get("audio_transcript") or "",
                "clip_url": clip_url,
            })

        vn_report_date = _vn_dt(report_date)
        vn_window_start = _vn_dt(window_start)
        vn_window_end = _vn_dt(window_end)

        # Construct executive narrative (deterministic fallback + optional LLM refinement for active cameras)
        if total_events == 0:
            executive_summary = (
                f"Trong chu kỳ 24 giờ (từ {vn_window_start} đến {vn_window_end}), {cam_name} (Kênh {channel:02d}) "
                f"hoàn toàn yên tĩnh, không phát sinh bất kỳ sự kiện chuyển động hay cảnh báo an ninh nào."
            )
        else:
            executive_summary = (
                f"Trong chu kỳ cuốn chiếu 24 giờ ({vn_window_start} → {vn_window_end}), **{cam_name} (Kênh {channel:02d})** "
                f"ghi nhận tổng cộng **{total_events} sự kiện** ({human_count} lượt người, {vehicle_count} lượt phương tiện, "
                f"{clip_count} đoạn video trích xuất). "
            )
            if len(anomalies) > 0:
                executive_summary += (
                    f"Phát hiện **{len(anomalies)} sự kiện bất thường/cảnh báo** "
                    f"(trong đó có {len(critical_events)} cảnh báo mức độ cao). "
                )
            else:
                executive_summary += "Không ghi nhận cảnh báo xâm nhập hay bất thường an ninh nghiêm trọng nào. "

            executive_summary += f"Khung giờ hoạt động cao điểm nhất: **{peak_hour_label}**."

            if use_llm_narrative:
                llm_summary = self._synthesize_llm_executive_summary(
                    channel=channel,
                    cam_name=cam_name,
                    window_start=vn_window_start,
                    window_end=vn_window_end,
                    total_events=total_events,
                    human_count=human_count,
                    vehicle_count=vehicle_count,
                    anomaly_count=len(anomalies),
                    critical_count=len(critical_events),
                    peak_hour_label=peak_hour_label,
                    shift_summaries=shift_summaries,
                    notable_items=notable_items,
                )
                if llm_summary:
                    executive_summary = _vn_dt(llm_summary)

        generated_at = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S")

        # Build concise 1-page Markdown report
        md_lines = [
            f"# BÁO CÁO PHÂN TÍCH AI NGÀY {vn_report_date} — D{channel:02d}: {cam_name}",
            "",
            f"- **Cửa sổ thời gian cuốn chiếu:** `{vn_window_start}` → `{vn_window_end}` *(Video từ sau 22:00 được đẩy sang báo cáo ngày kế tiếp)*",
            f"- **Thời điểm xuất báo cáo:** `{generated_at}`",
            f"- **Đánh giá an ninh:** {risk_badge}",
            f"- **Thống kê nhanh:** Tổng `{total_events}` sự kiện | `{len(anomalies)}` Bất thường | `{human_count}` Lượt người | `{vehicle_count}` Phương tiện | `{clip_count}` Video Clip",
            f"- **Khung giờ cao điểm:** {peak_hour_label}",
            "",
            "---",
            "",
            "## 1. Tóm tắt Tổng quan trong Ngày",
            executive_summary,
            "",
            "## 2. Diễn biến Nối tiếp theo 4 Ca (22:00 hôm trước → 22:00 hôm nay)",
        ]

        for s in shift_summaries:
            md_lines.append(f"- **{s['title']}:** {s['summary_text']}")

        md_lines.extend([
            "",
            "## 3. Danh sách Video Sự kiện Đáng chú ý trong Kỳ",
        ])

        if not notable_items:
            md_lines.append("- *Không có video sự kiện nào trong khung thời gian này.*")
        else:
            for idx, item in enumerate(notable_items, start=1):
                clip_link = f"[Xem Video Clip]({item['clip_url']})" if item["clip_url"] else "*(Không có clip)*"
                detail_txt = item["ai_summary"] or item["description"] or "Đã ghi nhận metadata."
                md_lines.append(
                    f"{idx}. **[{item['timestamp']}] Sự kiện #{item['id']} (`{item['event_label']}` - `{item['severity'].upper()}`)** — {detail_txt} — {clip_link}"
                )

        markdown_content = "\n".join(md_lines) + "\n"

        return {
            "report_date": report_date,
            "channel": channel,
            "camera_code": f"D{channel}",
            "camera_name": cam_name,
            "window_start": vn_window_start,
            "window_end": vn_window_end,
            "generated_at": generated_at,
            "risk_level": risk_level,
            "risk_label": risk_label,
            "risk_badge": risk_badge,
            "total_events": total_events,
            "anomaly_count": len(anomalies),
            "critical_count": len(critical_events),
            "human_count": human_count,
            "vehicle_count": vehicle_count,
            "clip_count": clip_count,
            "peak_hour_label": peak_hour_label,
            "hourly_counts": hourly_counts,
            "executive_summary": executive_summary,
            "shifts": shift_summaries,
            "notable_events": notable_items,
            "markdown_content": markdown_content,
        }

    def _synthesize_llm_executive_summary(
        self,
        channel: int,
        cam_name: str,
        window_start: str,
        window_end: str,
        total_events: int,
        human_count: int,
        vehicle_count: int,
        anomaly_count: int,
        critical_count: int,
        peak_hour_label: str,
        shift_summaries: List[Dict[str, Any]],
        notable_items: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        Gọi LLM nội bộ (Qwen) để viết đoạn tóm tắt điều hành nối tiếp mạch lạc (2-4 câu)
        cho báo cáo 24h của từng camera. Tự động fallback nếu Server AI không phản hồi.
        """
        if not config.QWEN_API_KEY:
            return None
        try:
            import re
            import qwen_vision_client

            shifts_brief = "\n".join(
                f"- {s['title']}: {s['event_count']} sự kiện ({s['anomaly_count']} bất thường) — {s['summary_text']}"
                for s in shift_summaries
            )
            notable_brief = "\n".join(
                f"- [{ev['timestamp']}] #{ev['id']} ({ev['event_label']}): {ev['ai_summary'] or ev['description']}"
                for ev in notable_items[:5]
            )
            prompt = (
                f"Hãy viết 1 đoạn tóm tắt điều hành ngắn gọn (từ 2 đến 4 câu tiếng Việt chuyên nghiệp, "
                f"tuyệt đối KHÔNG dùng emoji hay biểu tượng cảm xúc, KHÔNG dùng tiêu đề markdown, "
                f"mọi ngày tháng hiển thị theo định dạng DD/MM/YYYY) "
                f"tổng kết diễn biến an ninh 24 giờ qua của {cam_name} (Kênh D{channel:02d}).\n"
                f"- Cửa sổ dữ liệu: {window_start} đến {window_end}\n"
                f"- Tổng sự kiện: {total_events} (Người: {human_count}, Phương tiện: {vehicle_count}, "
                f"Bất thường: {anomaly_count}, Nghiêm trọng: {critical_count})\n"
                f"- Khung giờ cao điểm: {peak_hour_label}\n"
                f"- Diễn biến 4 ca:\n{shifts_brief}\n"
                f"- Sự kiện tiêu biểu:\n{notable_brief or 'Không có'}"
            )
            resp = qwen_vision_client.call_qwen_chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Bạn là chuyên gia phân tích an ninh hệ thống Camera AI DNC. "
                            "Chỉ trả về đúng 1 đoạn văn tóm tắt mạch lạc bằng tiếng Việt (2-4 câu), "
                            "hiển thị ngày tháng theo định dạng DD/MM/YYYY, "
                            "không dùng emoji, không xuống dòng gạch đầu dòng."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=260,
                temperature=0.3,
                timeout=18,
            )
            text = (resp.get("content") or "").strip()
            if not text:
                return None
            # Strip any accidental emoji characters
            text = re.sub(
                r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF\U0000FE0F]+",
                "",
                text,
            ).strip()
            text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", r"\3/\2/\1", text)
            text = " ".join(line.strip() for line in text.splitlines() if line.strip())
            return text if len(text) >= 30 else None
        except Exception as exc:
            print(f"[NIGHTLY REPORT] LLM narrative fallback for channel D{channel:02d}: {exc}")
            return None


nightly_report_worker = NightlyReportWorker()

