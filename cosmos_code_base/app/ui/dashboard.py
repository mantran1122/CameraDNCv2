import html
import io
import json
import os
from functools import lru_cache
from string import Template
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import streamlit as st

EventList = List[Dict[str, Any]]
TEMPLATE_DIR = Path(__file__).with_name("templates")
# Chiều cao tile Timeline khớp cụm Video đang xem + Video & phân tích ở desktop.
TIMELINE_BENTO_HEIGHT = 730


@lru_cache(maxsize=None)
def _template_source(name: str) -> str:
    """Đọc template UI từ file để HTML/CSS không nằm trong mã Python."""
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _load_template(name: str, *, css: bool = False, **values: Any) -> str:
    source = _template_source(name)
    if css:
        return f"<style>\n{source}\n</style>"
    return Template(source).safe_substitute(**values)


def _load_local_config() -> Dict[str, Any]:
    cfg_path = Path(__file__).resolve().parents[1] / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@dataclass
class UiApi:
    semantic_search: Callable[[str, int, str], Tuple[EventList, str]]
    keyword_search: Callable[[str], EventList]
    rebuild_index: Callable[[], Dict[str, Any]]
    reset_search: Callable[[], EventList]
    save_uploaded_video: Callable[[Any], None]
    available_server_videos: Callable[[], List[Path]]
    use_server_video: Callable[[Path], None]
    run_analysis: Callable[[Path], bool]
    clear_outputs: Callable[[], Dict[str, Any]]
    clear_vector_db: Callable[[], Dict[str, Any]]
    has_existing_result: Callable[[], bool]
    clear_video_data: Callable[[str], Dict[str, Any]]
    save_email_config: Callable[[Dict[str, Any]], None]
    start_folder_monitor: Callable[[Any], None]
    stop_folder_monitor: Callable[[], None]
    get_folder_monitor_status: Callable[[], Dict[str, Any]]


def render_page_style() -> None:
    """Nạp CSS từ template ngoài, không giữ CSS/HTML trong Python."""
    st.markdown(_load_template("dashboard.css", css=True), unsafe_allow_html=True)

def render_header(app_dir: Path) -> None:
    """App bar gọn; logo được giữ ở sidebar để không lặp thị giác trong nội dung."""
    st.markdown(_load_template("header.html"), unsafe_allow_html=True)


def render_upload_view(video_path: Path, api: UiApi) -> None:
    st.markdown(_load_template("empty_state.html", icon="movie", title="Chọn video để phân tích", description="Tải video MP4 lên hoặc chọn video có sẵn trên server. Sau đó bắt đầu phân tích để xem timeline sự kiện."), unsafe_allow_html=True)
    render_video_input_panel(video_path, api, has_result=False)


def render_result_view(video_path: Path, events: EventList, search_answer: str, api: UiApi) -> None:
    st.markdown(_load_template("analysis_header.html", video_name=html.escape(video_path.name), segment_count=len(events)), unsafe_allow_html=True)
    # Hai nhánh bento độc lập: tận dụng phần dưới video cho công cụ phân tích,
    # thay vì để cột video bị rỗng vì timeline dài hơn.
    video_col, timeline_col = st.columns(2, gap="large")
    with video_col:
        st.markdown(_load_template("section_heading.html", icon="videocam", title="Video đang xem", meta="Đồng bộ theo phân đoạn đã chọn"), unsafe_allow_html=True)
        render_left_column(video_path, events, api)
        st.markdown(_load_template("section_heading.html", icon="tune", title="Video & phân tích", meta="Chọn nguồn video hoặc chạy lại phân tích"), unsafe_allow_html=True)
        render_video_input_panel(video_path, api, has_result=True)
    with timeline_col:
        st.markdown(_load_template("section_heading.html", icon="timeline", title="Timeline sự kiện", meta=f"{len(_apply_filters(events))}/{len(events)} phân đoạn"), unsafe_allow_html=True)
        with st.expander("Tìm kiếm & lọc timeline", expanded=False):
            render_search_card(events, search_answer, api)
            render_filters(events)
        _render_timeline_new(events, height=TIMELINE_BENTO_HEIGHT)

    # Inspector dùng trọn chiều ngang ở hàng cuối; hai cột giúp đọc chi tiết
    # phân đoạn và đối chiếu số liệu/xác thực cùng lúc.
    render_right_panel(events, search_answer, api)


def _handle_pending_reanalyze(api: UiApi) -> bool:
    if st.session_state.get("_confirm_reanalyze"):
        video_path = Path(st.session_state.pop("_reanalyze_path", ""))
        st.session_state.pop("_confirm_reanalyze", None)
        if video_path.exists():
            with st.spinner("Đang phân tích lại..."):
                if api.run_analysis(video_path):
                    st.rerun()
        return True
    return False


def render_video_input_panel(video_path: Path, api: UiApi, has_result: bool) -> None:
    if _handle_pending_reanalyze(api):
        return
    with st.container(border=True):
        col_upload, col_server, col_action = st.columns([1.5, 1.5, 1], gap="medium")
        video_valid = _is_valid_video_file(video_path)
        with col_upload:
            st.markdown("##### :material/upload_file: Upload video")
            uploaded = st.file_uploader("Chọn file MP4", type=["mp4"], label_visibility="collapsed", key="main_uploader")
            if uploaded is not None:
                uploaded_key = f"{uploaded.name}:{uploaded.size}"
                processed_key = st.session_state.get("_last_uploaded", "")
                if uploaded_key != processed_key:
                    try:
                        api.save_uploaded_video(uploaded)
                        st.session_state._last_uploaded = uploaded_key
                        st.session_state.video_token = uploaded_key
                        st.session_state.events = []
                        st.toast(f"Đã upload: {uploaded.name} ({_format_bytes(uploaded.size)})", icon=":material/videocam:")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Lỗi upload: {exc}", icon=":material/error:")
        with col_server:
            st.markdown("##### :material/folder_open: Chọn từ server")
            server_videos = api.available_server_videos()
            if server_videos:
                labels = [f"{p.name} ({_format_bytes(p.stat().st_size)})" for p in server_videos]
                selected = st.selectbox("Video có sẵn", ["-- Chọn --"] + labels, label_visibility="collapsed", key="server_select")
                if selected != "-- Chọn --":
                    idx = labels.index(selected)
                    if st.button("Sử dụng", icon=":material/check_circle:", key="use_server_btn"):
                        try:
                            api.use_server_video(server_videos[idx])
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Lỗi: {exc}", icon=":material/error:")
            else:
                st.caption("Không có video trong thư mục server")
        with col_action:
            st.markdown("##### :material/play_circle: Hành động")
            btn_icon = ":material/refresh:" if has_result else ":material/play_arrow:"
            btn_label = "Phân tích lại" if has_result else "Bắt đầu phân tích"
            disabled = not video_valid
            if disabled:
                st.warning("Chưa có video hợp lệ", icon=":material/warning:")
            elif st.button(btn_label, icon=btn_icon, type="primary", use_container_width=True, key="btn_analyze"):
                if has_result and api.has_existing_result():
                    show_reanalyze_confirm(video_path, api)
                else:
                    st.session_state.last_analysis_report = None
                    if api.run_analysis(video_path):
                        st.rerun()
        if video_valid:
            st.caption(f"`{video_path.name}` · {_format_bytes(video_path.stat().st_size)}")
    render_folder_path_setting()


def render_left_column(video_path: Path, events: EventList, api: UiApi) -> None:
    if not video_path.exists():
        st.warning("Không tìm thấy file video", icon=":material/warning:")
        return

    selected_idx = _selected_event_index(events)
    start_time = 0
    if events and selected_idx < len(events):
        start_time = int(events[selected_idx].get("sec", 0))
    playback_media_url = str(st.session_state.get("playback_media_url", "")).strip()
    playback_media_path = str(st.session_state.get("playback_media_path", "")).strip()
    is_current_playback = False
    if playback_media_path:
        try:
            is_current_playback = Path(playback_media_path).resolve() == video_path.resolve()
        except OSError:
            pass
    if playback_media_url and st.session_state.get("playback_token") and is_current_playback:
        st.video(playback_media_url, format="video/mp4", start_time=max(0, start_time))
    else:
        st.video(str(video_path), start_time=max(0, start_time))

def render_right_panel(events: EventList, search_answer: str, api: UiApi) -> None:
    """Inspector chứa segment đang xem và các công cụ tìm/lọc liên quan."""
    st.markdown(_load_template("section_heading.html", icon="search_insights", title="Inspector", meta="Chi tiết và công cụ theo dõi"), unsafe_allow_html=True)
    # Khóa tỷ lệ 1:1 để Inspector luôn là hai cột ngang cân bằng.
    detail_col, insights_col = st.columns([1, 1], gap="large")
    with detail_col:
        render_current_segment(events)
    with insights_col:
        render_validation_panel(events)
        with st.expander("Tùy chọn dữ liệu", expanded=False):
            render_reset_panel(api)


def _render_timeline_new(events: EventList, height: int = 560) -> None:
    filtered = _apply_filters(events)
    if not filtered:
        st.markdown(_load_template("empty_state.html", icon="filter_alt_off", title="Không có phân đoạn phù hợp", description="Thử thay đổi điều kiện tìm kiếm hoặc bộ lọc để xem lại timeline."), unsafe_allow_html=True)
        return
    _RISK_LABEL = {"none": "BÌNH THƯỜNG", "low": "THẤP", "medium": "TRUNG BÌNH", "high": "CAO"}
    with st.container(height=height, border=True):
        for idx, ev in enumerate(filtered):
            is_active = int(ev.get("_orig_idx", idx)) == _selected_event_index(events)
            risk = ev.get("risk_level", "none")
            detected = ev.get("_detected_actions", [])
            _chip_labels = {"phone": "Điện thoại", "leave_desk": "Rời bàn", "crowd": "Tụ tập"}
            chips_html = "".join(_load_template("chip.html", label=_chip_labels.get(action, action)) for action in detected)
            vstatus_icon = "✓" if detected else "⚠"
            risk_label = _RISK_LABEL.get(risk, risk)
            active_cls = "is-active" if is_active else ""
            now_html = _load_template("now_playing.html") if is_active else ""
            st.markdown(_load_template(
                "timeline_segment.html", risk=risk, active_class=active_cls,
                index=idx + 1, start=html.escape(str(ev.get("start", ""))),
                end=html.escape(str(ev.get("end", ""))), risk_label=risk_label,
                validation_icon=vstatus_icon, now_html=now_html,
                description=html.escape(str(ev.get("desc", ""))[:160]), chips_html=chips_html,
            ), unsafe_allow_html=True)
            label = f"Chọn phân đoạn #{idx + 1}: {ev.get('start', '')} → {ev.get('end', '')}"
            if st.button(label, icon=":material/play_circle:", key=f"jump_{ev.get('_orig_idx', idx)}", use_container_width=True, help="Chọn phân đoạn và đưa video đến đúng thời điểm"):
                st.session_state.selected_event_index = int(ev.get("_orig_idx", idx))
                st.session_state.timeline_start_seconds = int(ev.get("sec", 0))
                st.rerun()


def render_current_segment(events: EventList) -> None:
    """Render dữ liệu segment được chọn trong inspector, không thay đổi dữ liệu nguồn."""
    selected_idx = _selected_event_index(events)
    if not events or selected_idx >= len(events):
        st.markdown(_load_template("empty_state.html", icon="touch_app", title="Chọn một phân đoạn", description="Chọn bất kỳ sự kiện nào trên timeline để xem chi tiết và mở video đúng thời điểm."), unsafe_allow_html=True)
        return
    ev = events[selected_idx]
    risk = str(ev.get("risk_level", "none"))
    detected = _detect_actions(str(ev.get("desc", "")))
    labels = {"phone": "Điện thoại", "leave_desk": "Rời bàn", "crowd": "Tụ tập"}
    chips_html = "".join(_load_template("chip.html", label=labels.get(action, action)) for action in detected)
    status_html = _load_template("validation_status.html", color="var(--risk-low-fg)" if detected else "var(--risk-med-fg)", icon="✓" if detected else "⚠", label="Đã xác thực" if detected else "Chưa xác thực")
    st.markdown(_load_template("current_segment.html", index=selected_idx + 1, start=html.escape(str(ev.get("start", ""))), end=html.escape(str(ev.get("end", ""))), risk_html=_load_template("risk_badge.html", risk=risk, label=risk.upper()), status_html=status_html, description=html.escape(str(ev.get("desc", ""))), chips_html=chips_html), unsafe_allow_html=True)
    if st.button("Nhảy đến thời điểm", icon=":material/skip_next:", use_container_width=True, key="inspector_jump"):
        st.session_state.timeline_start_seconds = int(ev.get("sec", 0))
        st.rerun()


def render_middle_column(events: EventList, api: UiApi) -> None:
    st.markdown("### :material/view_timeline: Timeline")
    filtered = _apply_filters(events)
    selected_idx = _selected_event_index(filtered)
    if not filtered:
        st.caption("Không có phân đoạn nào phù hợp.")
        return
    st.caption(f"{len(filtered)}/{len(events)} đoạn")
    with st.container(height=680, border=False):
        for idx, ev in enumerate(filtered):
            active = "active" if idx == selected_idx else ""
            risk = ev.get("risk_level", "none")
            detected = ev.get("_detected_actions", [])
            # Validation CSS class
            validation_cls = ""
            if detected:
                validation_cls = "validated"
            elif st.session_state.get("search_answer", ""):
                validation_cls = "unvalidated"
            badge_html = _action_badges(detected) if detected else ""
            # Validation icon
            val_icon = "✅" if detected else ("⚠️" if st.session_state.get("search_answer", "") else "")
            st.markdown(_load_template(
                "legacy_timeline_segment.html", active=active,
                validation_class=validation_cls, index=idx, number=idx + 1,
                validation_icon=val_icon, start=html.escape(str(ev.get("start", ""))),
                end=html.escape(str(ev.get("end", ""))), risk=risk,
                risk_label=risk.upper(), description=html.escape(str(ev.get("desc", ""))[:140]),
                badges=badge_html,
            ), unsafe_allow_html=True)
            if st.button(f"Xem", icon=":material/visibility:", key=f"jump_{idx}", use_container_width=True):
                st.session_state.selected_event_index = int(ev.get("_orig_idx", idx))
                st.session_state.timeline_start_seconds = int(ev.get("sec", 0))
                st.rerun()


def render_right_column(events: EventList, search_answer: str, api: UiApi, data: Dict[str, Any]) -> None:
    render_validation_panel(events)
    st.markdown(_load_template("spacer.html", style="margin:4px 0;"), unsafe_allow_html=True)
    render_search_card(events, search_answer, api)
    st.markdown(_load_template("spacer.html", style="margin:4px 0;"), unsafe_allow_html=True)
    render_filters(events)
    st.markdown(_load_template("spacer.html", style="margin:4px 0;"), unsafe_allow_html=True)
    render_chat_box(search_answer)
    st.markdown(_load_template("spacer.html", style="margin:4px 0;"), unsafe_allow_html=True)
    render_reset_panel(api)


def render_validation_panel(events: EventList) -> None:
    if not events:
        return
    total = len(events)
    validated = sum(1 for ev in events if _detect_actions(str(ev.get("desc", ""))))
    unvalidated = total - validated
    phone = sum(1 for ev in events if "phone" in _detect_actions(str(ev.get("desc", ""))))
    leave = sum(1 for ev in events if "leave_desk" in _detect_actions(str(ev.get("desc", ""))))
    crowd = sum(1 for ev in events if "crowd" in _detect_actions(str(ev.get("desc", ""))))
    st.markdown(_load_template("stats_row.html", total=total, validated=validated, validated_percent=round(validated / total * 100) if total else 0, abnormal=unvalidated, high=sum(1 for ev in events if ev.get("risk_level") == "high")), unsafe_allow_html=True)
    if validated > 0:
        st.markdown(_load_template("validation_summary.html", phone=phone, leave=leave, crowd=crowd), unsafe_allow_html=True)


_ACTION_KEYWORDS: Dict[str, List[str]] = {
    "phone": ["điện thoại", "phone", "smartphone", "mobile", "cầm điện thoại", "sử dụng điện thoại", "gọi điện", "nhắn tin"],
    "leave_desk": ["rởi khỏi", "bàn làm việc", "leave desk", "absent", "không có mặt", "vắng mặt", "rởi bàn", "không tại chỗ", "bỏ vị trí", "đi ra ngoài"],
    "crowd": ["tụ tập", "đông ngưởi", "crowd", "tập trung", "nhiều ngưởi", "nhóm ngưởi", "đám đông", "tụ họp"],
}


def _detect_actions(desc: str) -> List[str]:
    d = str(desc).lower()
    found: List[str] = []
    for action, kws in _ACTION_KEYWORDS.items():
        if any(kw in d for kw in kws):
            found.append(action)
    return found


def _action_badges(actions: List[str]) -> str:
    labels = {"phone": "Điện thoại", "leave_desk": "Rởi bàn", "crowd": "Tụ tập"}
    parts = []
    for a in actions:
        parts.append(_load_template("action_badge.html", label=labels.get(a, a)))
    return " ".join(parts)


def _get_event_date(ev: Dict[str, Any]) -> Any:
    from datetime import datetime
    vf = ev.get("video_file", "")
    if vf:
        try:
            p = Path(vf)
            if p.exists():
                return datetime.fromtimestamp(p.stat().st_mtime).date()
        except Exception:
            pass
    cp = ev.get("chunk_path", "")
    if cp:
        try:
            p = Path(cp)
            if p.exists():
                return datetime.fromtimestamp(p.stat().st_mtime).date()
        except Exception:
            pass
    return None


def _apply_filters(events: EventList) -> EventList:
    actions = st.session_state.get("filter_actions", [])
    today_only = st.session_state.get("filter_today", False)
    from_date = st.session_state.get("filter_from_date")
    to_date = st.session_state.get("filter_to_date")
    validated_only = st.session_state.get("filter_validated_only", False)
    filtered = []
    for i, ev in enumerate(events):
        desc = str(ev.get("desc", "")).lower()
        detected = _detect_actions(desc)
        if actions:
            label_to_key = {
                "Cầm điện thoại": "phone",
                "Rởi khỏi bàn làm việc": "leave_desk",
                "Tụ tập đông ngưởi": "crowd"
            }
            target_keys = {label_to_key.get(a, a) for a in actions}
            if not target_keys.intersection(set(detected)):
                continue
        if validated_only and not detected:
            continue
        if today_only:
            from datetime import date
            ev_date = _get_event_date(ev)
            if ev_date != date.today():
                continue
        elif from_date and to_date and from_date != to_date:
            ev_date = _get_event_date(ev)
            if ev_date is None or not (from_date <= ev_date <= to_date):
                continue
        filtered.append({"_orig_idx": i, "_detected_actions": detected, **ev})
    return filtered


def render_filters(events: EventList) -> None:
    with st.container(border=False):
        st.markdown("##### Lọc nhanh")
        c1, c2 = st.columns([2, 1])
        with c1:
            st.multiselect("Loại hành động", ["Cầm điện thoại", "Rởi khỏi bàn làm việc", "Tụ tập đông ngưởi"], key="filter_actions", label_visibility="collapsed")
        with c2:
            st.checkbox("Hôm nay", key="filter_today", help="Chỉ hiện hôm nay")
        c3, c4 = st.columns(2)
        with c3:
            st.date_input("Từ ngày", key="filter_from_date", label_visibility="collapsed")
        with c4:
            st.date_input("Đến ngày", key="filter_to_date", label_visibility="collapsed")
        st.checkbox("Chỉ kết quả xác thực", key="filter_validated_only", help="Chỉ hiện đoạn có hành động nhận diện được")
        filtered = _apply_filters(events)
        if len(filtered) != len(events):
            st.caption(f"{len(filtered)}/{len(events)} đoạn phù hợp")


def render_metrics_sidebar(data: Dict[str, Any]) -> None:
    segments = _segments(data)
    total = len(segments)
    abnormal = sum(1 for s in segments if s.get("abnormal"))
    high_risk = sum(1 for s in segments if s.get("risk_level") == "high")
    indexed = (data.get("vector_index") or {}).get("indexed", False)
    st.markdown("### :material/analytics: Thống kê")
    row1 = st.columns(2)
    row1[0].metric("Tổng đoạn", total)
    row1[1].metric("Bất thường", abnormal)
    row2 = st.columns(2)
    row2[0].metric("Rủi ro cao", high_risk)
    row2[1].metric("Đã index", "Có" if indexed else "Không")


def render_summary_card(data: Dict[str, Any]) -> None:
    summary = data.get("video_summary") or {}
    if not summary:
        return
    st.markdown("### :material/summarize: Tóm tắt")
    st.markdown(_load_template("summary.html", overview=html.escape(summary.get("overview", ""))), unsafe_allow_html=True)
    st.markdown(f"**Ý nghĩa:** {summary.get('meaning', '')}")


def render_search_card(events: EventList, search_answer: str, api: UiApi) -> None:
    st.markdown("##### Tìm kiếm ngữ nghĩa")
    query = st.text_area("Câu hỏi", value="đoạn nào có nhiều ngưởi tụ tập hoặc dùng điện thoại", height=44, label_visibility="collapsed", key="search_query")
    c1, c2, c3 = st.columns([1.1, 1.3, 1.6])
    with c1:
        limit = st.slider("Số KQ", 3, 20, 8, key="search_limit", label_visibility="collapsed")
    with c2:
        mode = st.selectbox("Chế độ", ["hybrid_lancedb", "openai_metadata"], format_func=lambda x: "Vector" if x == "hybrid_lancedb" else "LLM", key="search_mode", label_visibility="collapsed")
    with c3:
        if st.button("Tìm", icon=":material/search:", use_container_width=True):
            try:
                loading_slot = st.empty()
                loading_slot.markdown(_load_template("spinner.html", title="Đang tìm kiếm", description="Đối chiếu nội dung video và metadata để tìm các phân đoạn phù hợp."), unsafe_allow_html=True)
                try:
                    found_events, answer = api.semantic_search(query, limit, mode)
                finally:
                    loading_slot.empty()
                # Validate search results with action detection
                validated = 0
                for ev in found_events:
                    detected = _detect_actions(str(ev.get("desc", "")))
                    if detected:
                        validated += 1
                st.session_state.events = found_events
                st.session_state.search_answer = answer
                if validated < len(found_events):
                    st.session_state.search_answer = f"{answer}\n\nLưu ý: {validated}/{len(found_events)} kết quả đã xác thực hành động."
                chat_history = st.session_state.get("chat_history", [])
                chat_history.append({"role": "user", "content": query})
                chat_history.append({"role": "assistant", "content": answer or "Đã tìm thấy kết quả phù hợp."})
                st.session_state.chat_history = chat_history
                st.rerun()
            except Exception as exc:
                st.error(f"Lỗi: {exc}", icon=":material/error:")
    if search_answer:
        st.markdown(_load_template("search_answer.html", answer=html.escape(search_answer)), unsafe_allow_html=True)


def render_chat_box(search_answer: str) -> None:
    st.markdown("**💬 AI Chat**")
    chat_history = st.session_state.get("chat_history", [])
    chat_container = st.container(height=200, border=False)
    with chat_container:
        if not chat_history:
            st.caption("Đặt câu hỏi để chat với AI.")
        for msg in chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
    user_input = st.chat_input("Hỏi AI...", key="chat_input")
    if user_input:
        chat_history.append({"role": "user", "content": user_input})
        assistant_reply = f"Tôi đã nhận: **{user_input}**. Dùng ô tìm kiếm bên trên để tìm chính xác."
        if search_answer:
            assistant_reply += f"\n\n_Kết quả gần nhất:_ {search_answer}"
        chat_history.append({"role": "assistant", "content": assistant_reply})
        st.session_state.chat_history = chat_history
        st.rerun()


def render_folder_path_setting() -> None:
    with st.expander("Thiết lập đường dẫn folder input mặc định", expanded=False):
        current = st.session_state.get("server_video_dir", "")
        path_input = st.text_input(
            "Đường dẫn thư mục video",
            value=current,
            placeholder=r"VD: D:\dev\dnc\data_test_cam",
            key="server_video_dir_input",
            help="Thư mục chứa video để chọn từ server. Để trống để dùng mặc định.",
        )
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Lưu đường dẫn", icon=":material/save:", use_container_width=True, key="save_folder_path"):
                trimmed = path_input.strip()
                if trimmed:
                    p = Path(trimmed)
                    if p.exists() and p.is_dir():
                        st.session_state.server_video_dir = trimmed
                        os.environ["COSMOS_SERVER_VIDEO_DIR"] = trimmed
                        st.success(f"Đã lưu: `{trimmed}`", icon=":material/check_circle:")
                    else:
                        st.warning("Đường dẫn không tồn tại hoặc không phải thư mục.", icon=":material/warning:")
                else:
                    st.session_state.pop("server_video_dir", None)
                    os.environ.pop("COSMOS_SERVER_VIDEO_DIR", None)
                    st.info("Đã đặt lại về mặc định.", icon=":material/info:")
        with c2:
            if st.button("Mở thư mục", icon=":material/folder_open:", use_container_width=True, key="open_folder_path"):
                import subprocess
                target = path_input.strip() or os.getenv("COSMOS_SERVER_VIDEO_DIR", r"D:\dev\dnc\data_test_cam")
                try:
                    subprocess.run(["explorer", target], check=False)
                except Exception:
                    st.warning("Không thể mở thư mục.", icon=":material/warning:")
        if current:
            st.caption(f"Hiện tại: `{current}`")


@st.dialog("Xác nhận phân tích lại")
def show_reanalyze_confirm(video_path: Path, api: UiApi) -> None:
    st.warning("Video này đã được phân tích trước đó.", icon=":material/warning:")
    st.markdown("""
    Nếu phân tích lại, hệ thống sẽ:
    - Xóa kết quả phân tích cũ
    - Xóa dữ liệu vector DB liên quan
    - Xóa file chunks đã tạo
    - Phân tích lại từ đầu
    """)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Hủy", use_container_width=True, key="dlg_cancel"):
            st.rerun()
    with c2:
        if st.button("Đồng ý phân tích lại", icon=":material/check:", type="primary", use_container_width=True, key="dlg_confirm"):
            try:
                info = api.clear_video_data(video_path.name)
                st.success(f"Đã xóa dữ liệu cũ: {info.get('deleted', 0)} file/DB", icon=":material/check_circle:")
                st.session_state.last_analysis_report = None
                st.session_state._confirm_reanalyze = True
                st.session_state._reanalyze_path = str(video_path)
                st.rerun()
            except Exception as exc:
                st.error(f"Lỗi xóa dữ liệu: {exc}", icon=":material/error:")


def render_reset_panel(api: UiApi) -> None:
    with st.container(border=False):
        st.markdown("**Đặt lại**")
        # Show success message from previous reset (survives one rerun)
        if st.session_state.pop("_reset_success", None):
            st.success(st.session_state.get("_reset_msg", "Đã xóa thành công!"), icon=":material/check_circle:")
        with st.expander("Chọn mức độ xóa", expanded=False):
            st.caption("Thao tác không thể hoàn tác!")
            if st.button("Reset session (dữ liệu tạm)", icon=":material/refresh:", use_container_width=True, key="reset_session"):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
            if st.button("Xóa file video & kết quả phân tích", icon=":material/delete_forever:", use_container_width=True, key="reset_files"):
                try:
                    info = api.clear_outputs()
                    msg = f"Đã xóa: {info.get('deleted', 0)} file"
                    st.session_state._reset_success = True
                    st.session_state._reset_msg = msg
                    for key in list(st.session_state.keys()):
                        if key not in ("_reset_success", "_reset_msg"):
                            del st.session_state[key]
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi xóa file: {exc}", icon=":material/error:")
            if st.button("Xóa toàn bộ + Database", icon=":material/database_off:", type="primary", use_container_width=True, key="reset_all"):
                try:
                    info_files = api.clear_outputs()
                    info_db = api.clear_vector_db()
                    msg = f"Đã xóa: {info_files.get('deleted', 0)} file + {info_db.get('deleted', 0)} DB"
                    st.session_state._reset_success = True
                    st.session_state._reset_msg = msg
                    for key in list(st.session_state.keys()):
                        if key not in ("_reset_success", "_reset_msg"):
                            del st.session_state[key]
                    st.rerun()
                except Exception as exc:
                    st.error(f"Lỗi xóa toàn bộ: {exc}", icon=":material/error:")


# ────────────────────────
# REPORT / EXPORT
# ────────────────────────

def render_report_tab(data: Dict[str, Any], events: EventList, api: UiApi) -> None:
    tab_cfg, tab_email, tab_folder, tab_export = st.tabs([":material/description: Template", ":material/email: Email", ":material/folder: Thư mục Input", ":material/bar_chart: Xuất Báo cáo"])
    with tab_cfg:
        render_report_template_config(api)
    with tab_email:
        render_email_config(api)
    with tab_folder:
        render_inprogress_folder_config(api)
    with tab_export:
        render_report_export(events, data)


def render_inprogress_folder_config(api: UiApi) -> None:
    st.markdown("### Thư mục Input mặc định")
    st.info("Thư mục này chứa video đầu vào để phân tích. Thay đổi path bên dưới và nhấn **Lưu** để cập nhật.")
    # Show current saved path
    current_path = st.session_state.get("inprogress_dir", r"D:\dev\dnc\data_test_cam")
    st.markdown(f"**Path hiện tại:** `{current_path}`")
    # Use a non-widget state key so we can mutate it freely (e.g., from Browse/Reset)
    state_key = "_inprogress_dir_value"
    if state_key not in st.session_state:
        st.session_state[state_key] = current_path
    # Input row with Browse button
    c_in, c_br = st.columns([4, 1])
    with c_in:
        # No widget key here — value is driven by session_state[state_key]
        new_path = st.text_input("Đường dẫn thư mục", value=st.session_state[state_key], label_visibility="collapsed")
    with c_br:
        st.markdown(_load_template("spacer.html", style="height:28px"), unsafe_allow_html=True)
        if st.button("📂 Browse", use_container_width=True, key="btn_browse_inprogress"):
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                selected = filedialog.askdirectory(initialdir=new_path.strip() or current_path, title="Chọn thư mục video")
                root.destroy()
                if selected:
                    st.session_state[state_key] = selected
                    st.rerun()
            except Exception as exc:
                st.warning(f"Không thể mở file browser: {exc}. Vui lòng nhập path thủ công.", icon=":material/warning:")
    # Action buttons
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("💾 Lưu path", type="primary", use_container_width=True, key="btn_save_inprogress"):
            trimmed = new_path.strip()
            if trimmed:
                p = Path(trimmed)
                if p.exists() and p.is_dir():
                    st.session_state.inprogress_dir = trimmed
                    st.session_state[state_key] = trimmed
                    os.environ["COSMOS_SERVER_VIDEO_DIR"] = trimmed
                    cfg = {"inprogress_dir": trimmed}
                    api.save_email_config(cfg)
                    st.success(f"Đã lưu thư mục: `{trimmed}`", icon=":material/check_circle:")
                else:
                    st.warning("Đường dẫn không tồn tại hoặc không phải thư mục. Vẫn lưu lại?", icon=":material/warning:")
                    st.session_state.inprogress_dir = trimmed
                    st.session_state[state_key] = trimmed
                    os.environ["COSMOS_SERVER_VIDEO_DIR"] = trimmed
                    cfg = {"inprogress_dir": trimmed}
                    api.save_email_config(cfg)
            else:
                st.error("Path không được để trống.", icon=":material/error:")
    with c2:
        if st.button("Mặc định", use_container_width=True, key="btn_reset_inprogress"):
            default_path = r"D:\dev\dnc\data_test_cam"
            st.session_state.inprogress_dir = default_path
            st.session_state[state_key] = default_path
            os.environ["COSMOS_SERVER_VIDEO_DIR"] = default_path
            cfg = {"inprogress_dir": default_path}
            api.save_email_config(cfg)
            st.rerun()
    with c3:
        if st.button("📂 Mở thư mục", use_container_width=True, key="btn_open_inprogress"):
            import subprocess
            target = new_path.strip() or current_path
            try:
                subprocess.run(["explorer", target], check=False)
            except Exception:
                st.warning("Không thể mở thư mục.", icon=":material/warning:")

    st.divider()
    st.markdown("#### Giám sát thư mục tự động")

    # Validate saved config before allowing monitor
    cfg = _load_local_config()
    saved_inprogress = cfg.get("inprogress_dir", "")

    # Determine initial toggle state from monitor + persisted config
    status_now = api.get_folder_monitor_status()
    monitor_on = status_now["running"] or st.session_state.get("folder_monitor_enabled", False)

    monitor_enabled = st.toggle("Bật giám sát tự động", value=monitor_on, key="folder_monitor_toggle")

    prev_monitor = st.session_state.get("_prev_folder_monitor_toggle", False)
    if monitor_enabled and not prev_monitor:
        if not saved_inprogress:
            st.session_state["folder_monitor_toggle"] = False
            st.session_state["_prev_folder_monitor_toggle"] = False
            st.session_state["folder_monitor_enabled"] = False
            st.error("Vui lòng lưu đường dẫn thư mục Input trước khi bật giám sát tự động.", icon=":material/error:")
            st.rerun()
        elif not Path(saved_inprogress).exists():
            st.session_state["folder_monitor_toggle"] = False
            st.session_state["_prev_folder_monitor_toggle"] = False
            st.session_state["folder_monitor_enabled"] = False
            st.error(f"Thư mục `{saved_inprogress}` không tồn tại. Vui lòng kiểm tra lại.", icon=":material/error:")
            st.rerun()
        else:
            api.start_folder_monitor(api)
            st.session_state["folder_monitor_enabled"] = True
            api.save_email_config({"folder_monitor_enabled": True})
            st.toast("Đã bật giám sát thư mục", icon=":material/play_circle:")
    elif not monitor_enabled and prev_monitor:
        api.stop_folder_monitor()
        st.session_state["folder_monitor_enabled"] = False
        api.save_email_config({"folder_monitor_enabled": False})
        st.toast("Đã tắt giám sát thư mục", icon=":material/stop_circle:")

    st.session_state["_prev_folder_monitor_toggle"] = monitor_enabled

    # Re-read status AFTER start/stop so display is accurate immediately
    status = api.get_folder_monitor_status()

    # Status display
    if status["running"]:
        # Stage badge
        stage = status.get("stage", "idle")
        stage_labels = {
            "idle": "Đang chạy", "waiting": "Chờ file", "model_loading": "Nạp model",
            "chunking": "Cắt chunk", "analyzing": "Phân tích", "summarizing": "Tóm tắt",
            "indexing": "Index", "alerting": "Gửi cảnh báo", "completed": "Hoàn tất", "error": "Lỗi"
        }
        stage_label = stage_labels.get(stage, stage)
        st.success(f"{stage_label} — {status['message']}", icon=":material/autorenew:")

        if status.get("watch_dir"):
            st.caption(f"Đang giám sát: `{status['watch_dir']}`")

        if status["current_file"]:
            with st.container(border=False):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"**File**  \n`{status['current_file']}`")
                with c2:
                    size = status.get('video_size', 0)
                    duration = status.get('video_duration', 0)
                    mins = int(duration // 60)
                    secs = int(duration % 60)
                    st.markdown(f"**Thời gian**  \n`{mins:02d}:{secs:02d}` ({_format_bytes(size)})")
                with c3:
                    if status.get('elapsed_seconds', 0) > 0:
                        st.markdown(f"**Đã chạy**  \n`{int(status['elapsed_seconds'])} giây`")

        # Status detail
        detail = status.get("status_detail", "")
        if detail:
            st.info(detail, icon=":material/info:")

        # Chunk progress
        if status.get("total_chunks", 0) > 0:
            chunk_pct = status["current_chunk"] / status["total_chunks"] * 100
            st.progress(chunk_pct / 100, text=f"Chunk {status['current_chunk']}/{status['total_chunks']} ({chunk_pct:.0f}%)")

        # Risk summary (shown when completed or analyzing)
        if stage in ("completed", "analyzing", "summarizing", "indexing", "alerting"):
            risk = status.get("risk_level", "none")
            risk_label = {"high": "Cao", "medium": "Trung bình", "low": "Thấp", "none": "Không"}.get(risk, risk)
            high = status.get("high_risk_count", 0)
            med = status.get("medium_risk_count", 0)
            low = status.get("low_risk_count", 0)
            if high or med or low:
                st.caption(f"Rủi ro: {risk_label} | cao {high} | vừa {med} | thấp {low}")

        st.caption(f"Đã xử lý: {status['processed']}  |  Bỏ qua: {status.get('skipped', 0)}  |  Lỗi: {status['errors']}")

        # Last log line (for debugging)
        log_tail = status.get("log_tail", "")
        if log_tail:
            st.caption(f"`{log_tail[:100]}`")
    else:
        st.info("Giám sát đang tắt. Bật toggle để tự động phân tích video từ thư mục.", icon=":material/info:")

    # ── Email alert toggle ──
    st.divider()
    st.markdown("#### Gửi email cảnh báo tự động")
    st.caption("Bật để tự động gửi email khi phát hiện rủi ro trong video được phân tích.")

    if "_folder_email_notify_enabled" not in st.session_state:
        st.session_state["_folder_email_notify_enabled"] = st.session_state.get("email_notify_enabled", False)

    notify_toggle = st.toggle("Bật gửi email cảnh báo rủi ro", key="_folder_email_notify_enabled")

    prev_notify = st.session_state.get("_prev_folder_email_notify_enabled", False)
    if notify_toggle and not prev_notify:
        sender = st.session_state.get("smtp_sender", "").strip()
        password = st.session_state.get("smtp_password", "").strip()
        recipients = st.session_state.get("report_recipients", "").strip()
        if not sender or not password or not recipients:
            st.session_state["_folder_email_notify_enabled"] = False
            st.session_state["_prev_folder_email_notify_enabled"] = False
            st.error("Vui lòng cấu hình đầy đủ Email gửi, Mật khẩu ứng dụng và Email nhận trong tab Email trước khi bật cảnh báo.", icon=":material/error:")
            st.rerun()
        else:
            st.session_state.email_notify_enabled = True
            st.session_state["_cfg_email_notify_enabled"] = True
            cfg = {
                "email_notify_enabled": True,
                "email_notify_threshold": st.session_state.get("_cfg_email_notify_threshold", "low"),
            }
            api.save_email_config(cfg)
            st.toast("Đã bật gửi email cảnh báo và lưu cấu hình.", icon=":material/check_circle:")
    elif not notify_toggle and prev_notify:
        st.session_state.email_notify_enabled = False
        st.session_state["_cfg_email_notify_enabled"] = False
        cfg = {
            "email_notify_enabled": False,
            "email_notify_threshold": st.session_state.get("_cfg_email_notify_threshold", "low"),
        }
        api.save_email_config(cfg)
        st.toast("Đã tắt gửi email cảnh báo và lưu cấu hình.", icon=":material/check_circle:")

    st.session_state["_prev_folder_email_notify_enabled"] = notify_toggle

    if notify_toggle:
        threshold = st.session_state.get("_cfg_email_notify_threshold", "low")
        label = {"low": "Thấp (low)", "medium": "Trung bình (medium)", "high": "Cao (high)"}.get(threshold, threshold)
        st.caption(f"Ngưỡng cảnh báo: **{label}** — Chỉnh sửa trong tab Email")


def render_report_template_config(api: UiApi) -> None:
    st.markdown("### Cấu hình Template Báo cáo")
    st.info("Chỉnh sửa các trường bên dưới để tùy chỉnh nội dung báo cáo xuất ra. Các thay đổi sẽ tự động lưu vào config.json.")
    # Use keys matching session_state so Streamlit auto-syncs values
    st.text_input("Tiêu đề báo cáo", key="report_title")
    st.text_area("Nội dung đầu trang (header)", height=80, key="report_header")
    st.text_area("Nội dung cuối trang (footer)", height=80, key="report_footer")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.checkbox("Thống kê hành động", key="report_include_stats")
    with c2:
        st.checkbox("Danh sách sự kiện", key="report_include_events")
    with c3:
        st.checkbox("Chi tiết mô tả", key="report_include_details")
    # Auto-save template config
    cfg = {
        "report_title": st.session_state.get("report_title", "BÁO CÁO GIÁM SÁT VIDEO"),
        "report_header": st.session_state.get("report_header", ""),
        "report_footer": st.session_state.get("report_footer", ""),
        "report_include_stats": st.session_state.get("report_include_stats", True),
        "report_include_events": st.session_state.get("report_include_events", True),
        "report_include_details": st.session_state.get("report_include_details", True),
    }
    api.save_email_config(cfg)
    st.success("Template đã được lưu tự động.", icon=":material/check_circle:")


def render_email_config(api: UiApi) -> None:
    st.markdown("### Cấu hình Gửi Email Báo cáo")
    st.info("Cấu hình SMTP Gmail mặc định. Nhấn **Lưu cấu hình** để áp dụng. Mật khẩu ứng dụng (App Password) được lưu trong biến môi trường `SMTP_PASSWORD`.")

    # Show current saved config
    with st.container(border=False):
        st.caption("📌 Cấu hình đang lưu:")
        saved_sender = st.session_state.get("smtp_sender", "")
        saved_server = st.session_state.get("smtp_server", "")
        saved_port = st.session_state.get("smtp_port", 587)
        saved_ssl = st.session_state.get("smtp_enable_ssl", True)
        saved_recipients = st.session_state.get("report_recipients", "")
        c_info1, c_info2 = st.columns(2)
        with c_info1:
            st.markdown(f"**Server:** `{saved_server or 'smtp.gmail.com'}`<br>**Port:** `{saved_port}`<br>**SSL:** `{'Bật' if saved_ssl else 'Tắt'}`", unsafe_allow_html=True)
        with c_info2:
            st.markdown(f"**Sender:** `{saved_sender or 'Chưa cấu hình'}`<br>**Recipients:** `{saved_recipients or 'Chưa cấu hình'}`<br>**Password:** `{'Đã lưu' if st.session_state.get('smtp_password') else 'Chưa lưu'}`", unsafe_allow_html=True)

    st.divider()

    # Sync saved values into temp keys so widgets show current config
    # IMPORTANT: only set defaults when key does NOT exist yet, otherwise Streamlit will override on next rerun
    defaults = {
        "_cfg_report_recipients": st.session_state.get("report_recipients", ""),
        "_cfg_smtp_server": st.session_state.get("smtp_server", "smtp.gmail.com"),
        "_cfg_smtp_port": st.session_state.get("smtp_port", 587),
        "_cfg_smtp_sender": st.session_state.get("smtp_sender", "tttien@nctu.edu.vn"),
        "_cfg_smtp_password": st.session_state.get("smtp_password", os.getenv("SMTP_PASSWORD", "")),
        "_cfg_smtp_enable_ssl": st.session_state.get("smtp_enable_ssl", True),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Input fields — use ONLY key (no value=), so Streamlit reads/writes session_state correctly
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("SMTP Server", key="_cfg_smtp_server")
        st.number_input("SMTP Port", min_value=1, max_value=65535, key="_cfg_smtp_port")
    with c2:
        st.text_input("Email gửi (sender)", key="_cfg_smtp_sender")
        st.text_input("Mật khẩu ứng dụng (App Password)", type="password", key="_cfg_smtp_password")
    st.checkbox("Bật SSL/TLS (STARTTLS)", key="_cfg_smtp_enable_ssl")
    st.text_area("Email nhận báo cáo (phân cách bằng dấu phẩy)", placeholder="vd: user1@example.com, user2@example.com", key="_cfg_report_recipients", height=60)

    st.divider()
    st.markdown("#### Thông báo tự động khi phát hiện rủi ro")
    if "_cfg_email_notify_enabled" not in st.session_state:
        st.session_state["_cfg_email_notify_enabled"] = st.session_state.get("email_notify_enabled", False)
    if "_cfg_email_notify_threshold" not in st.session_state:
        st.session_state["_cfg_email_notify_threshold"] = st.session_state.get("email_notify_threshold", "low")

    st.selectbox("Ngưỡng rủi ro tối thiểu để gửi", options=["low", "medium", "high"], format_func=lambda x: {"low": "Thấp (low) trở lên", "medium": "Trung bình (medium) trở lên", "high": "Cao (high)"}[x], key="_cfg_email_notify_threshold")

    st.caption("💡 Lưu ý: Với Gmail, bạn cần tạo [App Password](https://myaccount.google.com/apppasswords) thay vì dùng mật khẩu tài khoản thường.")

    c_btn1, c_btn2, c_btn3 = st.columns([1, 1, 2])
    with c_btn1:
        if st.button("💾 Lưu cấu hình", type="primary", use_container_width=True, key="btn_save_email_cfg"):
            # Read latest values directly from session_state to ensure we get user input
            st.session_state.smtp_server = str(st.session_state.get("_cfg_smtp_server", "")).strip()
            st.session_state.smtp_port = int(st.session_state.get("_cfg_smtp_port", 587))
            st.session_state.smtp_sender = str(st.session_state.get("_cfg_smtp_sender", "")).strip()
            st.session_state.smtp_password = str(st.session_state.get("_cfg_smtp_password", "")).strip()
            st.session_state.smtp_enable_ssl = bool(st.session_state.get("_cfg_smtp_enable_ssl", True))
            st.session_state.report_recipients = str(st.session_state.get("_cfg_report_recipients", "")).strip()
            st.session_state.email_notify_enabled = bool(st.session_state.get("_cfg_email_notify_enabled", False))
            st.session_state.email_notify_threshold = str(st.session_state.get("_cfg_email_notify_threshold", "low")).strip()
            # Persist to JSON file
            cfg = {
                "smtp_server": st.session_state.smtp_server,
                "smtp_port": st.session_state.smtp_port,
                "smtp_sender": st.session_state.smtp_sender,
                "smtp_password": st.session_state.smtp_password,
                "smtp_enable_ssl": st.session_state.smtp_enable_ssl,
                "report_recipients": st.session_state.report_recipients,
                "report_title": st.session_state.get("report_title", "BÁO CÁO GIÁM SÁT VIDEO"),
                "report_header": st.session_state.get("report_header", ""),
                "report_footer": st.session_state.get("report_footer", ""),
                "report_include_stats": st.session_state.get("report_include_stats", True),
                "report_include_events": st.session_state.get("report_include_events", True),
                "report_include_details": st.session_state.get("report_include_details", True),
                "email_notify_enabled": st.session_state.email_notify_enabled,
                "email_notify_threshold": st.session_state.email_notify_threshold,
            }
            api.save_email_config(cfg)
            # Update env vars
            os.environ["SMTP_SENDER"] = st.session_state.smtp_sender
            os.environ["SMTP_PASSWORD"] = st.session_state.smtp_password
            os.environ["SMTP_SERVER"] = st.session_state.smtp_server
            os.environ["SMTP_PORT"] = str(st.session_state.smtp_port)
            st.success("Đã lưu cấu hình email vào file config.json!", icon=":material/check_circle:")
    with c_btn2:
        if st.button("Mặc định Gmail", use_container_width=True, key="btn_reset_email_cfg"):
            st.session_state.smtp_server = "smtp.gmail.com"
            st.session_state.smtp_port = 587
            st.session_state.smtp_sender = os.getenv("SMTP_SENDER", "tttien@nctu.edu.vn")
            st.session_state.smtp_enable_ssl = True
            st.session_state._cfg_smtp_server = "smtp.gmail.com"
            st.session_state._cfg_smtp_port = 587
            st.session_state._cfg_smtp_sender = os.getenv("SMTP_SENDER", "tttien@nctu.edu.vn")
            st.session_state._cfg_smtp_enable_ssl = True
            # Clear password and recipients on reset
            st.session_state._cfg_smtp_password = ""
            st.session_state._cfg_report_recipients = ""
            st.rerun()
    with c_btn3:
        st.markdown(_load_template("spacer.html", style="height:4px"), unsafe_allow_html=True)


def render_report_export(events: EventList, data: Dict[str, Any]) -> None:
    st.markdown("### Xuất Báo cáo")
    if not events and not data:
        st.warning("Chưa có dữ liệu phân tích để xuất báo cáo. Hãy phân tích video trước.", icon=":material/warning:")
        return

    # Filters
    c1, c2 = st.columns(2)
    with c1:
        report_mode = st.selectbox("Thời gian", ["Hôm nay", "Tùy chỉnh", "Tất cả"], key="report_time_mode")
    with c2:
        export_format = st.selectbox("Định dạng xuất", ["Excel (.xlsx)", "PDF (.pdf)", "HTML (.html)"], key="report_format")
    action_filter = st.multiselect("Lọc theo hành động", ["Cầm điện thoại", "Rởi khỏi bàn làm việc", "Tụ tập đông ngưởi"], key="report_action_filter")

    from_date = None
    to_date = None
    if report_mode == "Tùy chỉnh":
        c4, c5 = st.columns(2)
        with c4:
            from_date = st.date_input("Từ ngày", key="report_from_date")
        with c5:
            to_date = st.date_input("Đến ngày", key="report_to_date")

    # Prepare filtered events
    filtered = list(events) if events else []
    # Apply action filter
    if action_filter:
        label_to_key = {"Cầm điện thoại": "phone", "Rởi khỏi bàn làm việc": "leave_desk", "Tụ tập đông ngưởi": "crowd"}
        target_keys = {label_to_key.get(a, a) for a in action_filter}
        filtered = [ev for ev in filtered if target_keys.intersection(set(_detect_actions(str(ev.get("desc", "")))))]
    # Apply date filter
    if report_mode == "Hôm nay":
        filtered = [ev for ev in filtered if _get_event_date(ev) == date.today()]
    elif report_mode == "Tùy chỉnh" and from_date and to_date:
        filtered = [ev for ev in filtered if _get_event_date(ev) is not None and from_date <= _get_event_date(ev) <= to_date]

    st.caption(f"{len(filtered)} sự kiện sẽ được xuất")

    if not filtered:
        st.caption("Không có sự kiện nào phù hợp với bộ lọc.")
        return

    # Stats for report
    stats = {"phone": 0, "leave_desk": 0, "crowd": 0}
    for ev in filtered:
        for a in _detect_actions(str(ev.get("desc", ""))):
            if a in stats:
                stats[a] += 1

    # Build report data
    report_data = {
        "title": st.session_state.get("report_title", "BÁO CÁO GIÁM SÁT VIDEO"),
        "header": st.session_state.get("report_header", ""),
        "footer": st.session_state.get("report_footer", "").replace("{date}", datetime.now().strftime("%d/%m/%Y")),
        "date_range": _format_report_date_range(report_mode, from_date, to_date),
        "total_events": len(filtered),
        "events": filtered,
        "stats": stats,
        "include_stats": st.session_state.get("report_include_stats", True),
        "include_events": st.session_state.get("report_include_events", True),
        "include_details": st.session_state.get("report_include_details", True),
    }

    c_dl, c_mail = st.columns([1, 1])
    with c_dl:
        if st.button("📥 Tạo & Tải báo cáo", type="primary", use_container_width=True, key="btn_export_report"):
            if export_format == "Excel (.xlsx)":
                _export_report_excel(report_data)
            elif export_format == "PDF (.pdf)":
                _export_report_pdf(report_data)
            else:
                _export_report_html(report_data)
    with c_mail:
        if st.button("Gửi Email báo cáo", icon=":material/send:", type="primary", use_container_width=True, key="btn_email_report"):
            _send_report_email(report_data, export_format)
    # Show configured recipient below buttons
    _recipients = st.session_state.get("report_recipients", "").strip()
    if _recipients:
        st.caption(f"Email nhận: `{_recipients}`", help="Cấu hình trong tab Email")
    else:
        st.caption(":warning: Chưa cấu hình email nhận. Vào tab **Email** để thiết lập.")


def _send_report_email(report_data: Dict[str, Any], export_format: str) -> None:
    recipients = st.session_state.get("report_recipients", "").strip()
    if not recipients:
        st.error("Vui lòng nhập email nhận báo cáo trong tab Email.", icon=":material/error:")
        return
    sender = st.session_state.get("smtp_sender", "")
    password = st.session_state.get("smtp_password", "")
    if not sender or not password:
        st.error("Vui lòng cấu hình Email gửi và Mật khẩu ứng dụng trong tab Email.", icon=":material/error:")
        return
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders
    except ImportError:
        st.error("Thiếu thư viện smtplib (built-in). Kiểm tra môi trường Python.", icon=":material/error:")
        return
    # Build attachment
    filename = f"bao_cao_giam_sat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    mime_type = "text/html"
    buffer = io.BytesIO()
    if export_format == "Excel (.xlsx)":
        _build_excel_buffer(report_data, buffer)
        filename += ".xlsx"
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif export_format == "PDF (.pdf)":
        _build_pdf_buffer(report_data, buffer)
        filename += ".pdf"
        mime_type = "application/pdf"
    else:
        buffer.write(_build_html_content(report_data).encode("utf-8"))
        filename += ".html"
    buffer.seek(0)
    # Compose email
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipients
    _ts = datetime.now().strftime('%H:%M:%S %d/%m/%Y')
    _uid = datetime.now().strftime('%Y%m%d%H%M%S')
    msg["Subject"] = f"[BÁO CÁO DNC-VSS #{_uid}] {report_data['title']} – {report_data['date_range']} – Gửi lúc {_ts}"
    body = f"""
    <p>Xin chào,</p>
    <p>Báo cáo giám sát video được gửi tự động từ hệ thống DNC - VSS.</p>
    <p><strong>Thờigian:</strong> {report_data['date_range']}<br>
       <strong>Tổng sự kiện:</strong> {report_data['total_events']}<br>
       <strong>Điện thoại:</strong> {report_data['stats']['phone']} | <strong>Rởi bàn:</strong> {report_data['stats']['leave_desk']} | <strong>Tụ tập:</strong> {report_data['stats']['crowd']}
    </p>
    <p>Vui lòng xem file đính kèm.</p>
    <p><em>{report_data['footer'].replace(chr(10), '<br>')}</em></p>
    """
    msg.attach(MIMEText(body, "html", "utf-8"))
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(buffer.read())
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", f"attachment; filename={filename}")
    msg.attach(attachment)
    # Send
    try:
        server = smtplib.SMTP(st.session_state.get("smtp_server", "smtp.gmail.com"), int(st.session_state.get("smtp_port", 587)))
        if st.session_state.get("smtp_enable_ssl", True):
            server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [r.strip() for r in recipients.split(",") if r.strip()], msg.as_string())
        server.quit()
        st.toast(f"Đã gửi báo cáo đến: {recipients}", icon=":material/check_circle:")
    except Exception as exc:
        st.error(f"Lỗi gửi email: {exc}", icon=":material/error:")


def _format_report_date_range(mode: str, from_date: Any, to_date: Any) -> str:
    if mode == "Hôm nay":
        return datetime.now().strftime("%d/%m/%Y")
    elif mode == "Tùy chỉnh" and from_date and to_date:
        return f"{from_date.strftime('%d/%m/%Y')} - {to_date.strftime('%d/%m/%Y')}"
    return "Tất cả"


def _build_excel_buffer(report_data: Dict[str, Any], buffer: io.BytesIO) -> None:
    import pandas as pd
    rows = []
    for ev in report_data["events"]:
        actions = ", ".join(_detect_actions(str(ev.get("desc", ""))))
        rows.append({
            "Video ID": ev.get("video_id", ""),
            "Bắt đầu": ev.get("start", ""),
            "Kết thúc": ev.get("end", ""),
            "Rủi ro": ev.get("risk_level", "none"),
            "Hành động": actions,
            "Mô tả": ev.get("desc", ""),
        })
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary_data = {
            "Tiêu đề": [report_data["title"]],
            "Thờigian": [report_data["date_range"]],
            "Tổng sự kiện": [report_data["total_events"]],
        }
        if report_data["include_stats"]:
            summary_data["Điện thoại"] = [report_data["stats"]["phone"]]
            summary_data["Rởi bàn"] = [report_data["stats"]["leave_desk"]]
            summary_data["Tụ tập"] = [report_data["stats"]["crowd"]]
        pd.DataFrame(summary_data).T.to_excel(writer, sheet_name="Tổng quan", header=False)
        if report_data["include_events"]:
            df.to_excel(writer, sheet_name="Chi tiết", index=False)


def _build_pdf_buffer(report_data: Dict[str, Any], buffer: io.BytesIO) -> None:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    font_path = r"C:\Windows\Fonts\arial.ttf"
    if not Path(font_path).exists():
        font_path = r"C:\Windows\Fonts\calibri.ttf"
    if Path(font_path).exists():
        pdf.add_font("SysFont", "", font_path, uni=True)
        pdf.set_font("SysFont", size=12)
    else:
        pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, report_data["title"], ln=True, align="C")
    if Path(font_path).exists():
        pdf.set_font("SysFont", size=10)
    else:
        pdf.set_font("Arial", size=10)
    for line in report_data["header"].split("\n"):
        pdf.cell(0, 6, line, ln=True, align="C")
    pdf.ln(5)
    pdf.cell(0, 8, f"Thờigian: {report_data['date_range']}", ln=True)
    pdf.cell(0, 8, f"Tổng sự kiện: {report_data['total_events']}", ln=True)
    if report_data["include_stats"]:
        pdf.cell(0, 8, f"Điện thoại: {report_data['stats']['phone']}  Rởi bàn: {report_data['stats']['leave_desk']}  Tụ tập: {report_data['stats']['crowd']}", ln=True)
    pdf.ln(5)
    if report_data["include_events"]:
        if Path(font_path).exists():
            pdf.set_font("SysFont", size=9)
        else:
            pdf.set_font("Arial", size=9)
        for ev in report_data["events"]:
            pdf.cell(0, 6, f"{ev.get('start','')} -> {ev.get('end','')} | {ev.get('risk_level','none')} | {ev.get('desc','')[:100]}", ln=True)
    pdf.ln(5)
    for line in report_data["footer"].split("\n"):
        pdf.cell(0, 6, line, ln=True, align="C")
    pdf.output(buffer)


def _build_html_content(report_data: Dict[str, Any]) -> str:
    """Tạo báo cáo từ các template HTML trong ``app/ui/templates``."""
    rows = []
    for event in report_data["events"]:
        actions = _detect_actions(str(event.get("desc", "")))
        badges = " ".join(
            _load_template("report_badge.html", label=html.escape(action)) for action in actions
        )
        rows.append(_load_template(
            "report_row.html",
            start=html.escape(str(event.get("start", ""))),
            end=html.escape(str(event.get("end", ""))),
            risk=html.escape(str(event.get("risk_level", "none"))),
            badges=badges,
            description=html.escape(str(event.get("desc", ""))),
        ))
    events_table = _load_template("report_events_table.html", rows="".join(rows)) if report_data["include_events"] else ""
    stats = report_data["stats"]
    stats_html = _load_template(
        "report_stats.html", phone=stats["phone"], leave_desk=stats["leave_desk"], crowd=stats["crowd"],
    ) if report_data["include_stats"] else ""
    return _load_template(
        "report.html",
        title=html.escape(str(report_data["title"])),
        header=html.escape(str(report_data["header"])).replace("\n", "<br>"),
        date_range=html.escape(str(report_data["date_range"])),
        total_events=report_data["total_events"],
        stats_html=stats_html,
        events_table=events_table,
        footer=html.escape(str(report_data["footer"])).replace("\n", "<br>"),
    )

def _export_report_excel(report_data: Dict[str, Any]) -> None:
    try:
        buffer = io.BytesIO()
        _build_excel_buffer(report_data, buffer)
        buffer.seek(0)
        st.download_button(
            label="Tải Excel",
            data=buffer,
            file_name=f"bao_cao_giam_sat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except ImportError:
        st.error("Thiếu thư viện pandas. Hãy cài: pip install pandas openpyxl", icon=":material/error:")


def _export_report_pdf(report_data: Dict[str, Any]) -> None:
    try:
        buffer = io.BytesIO()
        _build_pdf_buffer(report_data, buffer)
        buffer.seek(0)
        st.download_button(
            label="Tải PDF",
            data=buffer,
            file_name=f"bao_cao_giam_sat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    except ImportError:
        st.warning("Thiếu thư viện fpdf. Chuyển sang xuất HTML.", icon=":material/info:")
        _export_report_html(report_data)


def _export_report_html(report_data: Dict[str, Any]) -> None:
    html_content = _build_html_content(report_data)
    buffer = io.BytesIO(html_content.encode("utf-8"))
    buffer.seek(0)
    st.download_button(
        label="Tải HTML",
        data=buffer,
        file_name=f"bao_cao_giam_sat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
        mime="text/html",
        use_container_width=True,
    )


def _segments(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [item for item in data.get("segments", []) if isinstance(item, dict)]


def _selected_event_index(events: EventList) -> int:
    if not events:
        return 0
    selected = int(st.session_state.get("selected_event_index", 0) or 0)
    return min(max(selected, 0), len(events) - 1)


def _resolve_chunk(path_value: str) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("\\", "/")
    candidates = [Path(raw), Path(normalized)]
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue
    return None


def _is_valid_video_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.2f} TB"

