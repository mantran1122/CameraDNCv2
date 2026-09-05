"""Time-based rules; never infer attendance or exit from one frame."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import CameraProfile
from .zones import point_in_polygon


@dataclass(frozen=True)
class TrackObservation:
    track_id: int
    footpoint: tuple[float, float]
    yellow_score: float


class StudentAffairsRules:
    """Per-camera state machine for desk coverage and waiting-area crowding."""

    def __init__(self, profile: CameraProfile, staff_yellow_threshold: float = 0.55) -> None:
        self.profile = profile
        self.staff_yellow_threshold = staff_yellow_threshold
        self._uncovered_since: dict[str, datetime] = {}
        self._crowded_since: datetime | None = None
        self._active_alerts: set[str] = set()

    def update(self, captured_at: datetime, tracks: list[TrackObservation], *, scene_changed: bool = False) -> dict:
        """Process one tracked frame and return the UI contract payload."""
        if captured_at.tzinfo is None:
            raise ValueError("captured_at must include timezone information")
        if scene_changed:
            self._uncovered_since.clear()
            self._crowded_since = None
            self._active_alerts.clear()
            return {"camera_id": self.profile.camera_id, "captured_at": captured_at.isoformat(), "scene_status": "needs_recalibration", "desks": [], "waiting": {"people": 0, "status": "disabled"}, "exits": [], "alerts": []}

        alerts: list[dict] = []
        desk_results: list[dict] = []
        staff_tracks = [track for track in tracks if track.yellow_score >= self.staff_yellow_threshold]
        for desk in self.profile.desks:
            assigned = [track.track_id for track in staff_tracks if point_in_polygon(track.footpoint, desk.polygon)]
            alert_id = f"{desk.id}_uncovered"
            if len(assigned) >= desk.expected_staff:
                self._uncovered_since.pop(desk.id, None)
                self._active_alerts.discard(alert_id)
                status = "overstaff" if len(assigned) > desk.expected_staff else "covered"
                desk_results.append({"id": desk.id, "status": status, "staff_tracks": assigned})
                continue
            since = self._uncovered_since.setdefault(desk.id, captured_at)
            elapsed = max(0.0, (captured_at - since).total_seconds())
            status = "uncovered_alert" if elapsed >= self.profile.thresholds.absent_after_seconds else "uncovered_pending"
            result = {"id": desk.id, "status": status, "staff_tracks": assigned, "since_seconds": int(elapsed)}
            desk_results.append(result)
            if status == "uncovered_alert" and alert_id not in self._active_alerts:
                alerts.append({"id": alert_id, "risk_level": "medium", "summary": f"Bàn trực {desk.id} chưa có đủ nhân viên áo vàng trong hơn {int(self.profile.thresholds.absent_after_seconds)} giây.", "replay_seconds": 30})
                self._active_alerts.add(alert_id)

        waiting_people = sum(point_in_polygon(track.footpoint, self.profile.waiting) for track in tracks)
        if waiting_people >= self.profile.thresholds.crowd_warn_people:
            self._crowded_since = self._crowded_since or captured_at
        else:
            self._crowded_since = None
            self._active_alerts.discard("waiting_crowded")
        crowd_seconds = 0 if self._crowded_since is None else max(0, int((captured_at - self._crowded_since).total_seconds()))
        crowded = self._crowded_since is not None and crowd_seconds >= self.profile.thresholds.crowd_confirm_seconds
        if crowded and "waiting_crowded" not in self._active_alerts:
            alerts.append({"id": "waiting_crowded", "risk_level": "low", "summary": "Khu vực chờ đang đông, cần theo dõi thêm.", "replay_seconds": 30})
            self._active_alerts.add("waiting_crowded")
        return {"camera_id": self.profile.camera_id, "captured_at": captured_at.isoformat(), "scene_status": "ready", "desks": desk_results, "waiting": {"people": waiting_people, "status": "crowded" if crowded else "normal"}, "exits": [], "alerts": alerts}
