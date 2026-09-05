from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from audio_to_text import transcribe_video


PROJ_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJ_ROOT / "outputs" / "audio_demo"
DEFAULT_MODEL = "openai/whisper-base"


def _normalize_result(result: dict) -> tuple[str, list[dict]]:
    transcript = str(result.get("text", "")).strip()
    segments: list[dict] = []

    chunks = result.get("chunks") or []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue

        timestamp = chunk.get("timestamp")
        start = end = None
        if isinstance(timestamp, (list, tuple)) and len(timestamp) >= 2:
            try:
                start = float(timestamp[0]) if timestamp[0] is not None else None
                end = float(timestamp[1]) if timestamp[1] is not None else None
            except (TypeError, ValueError):
                start = end = None

        segments.append({
            "start": start,
            "end": end,
            "text": text,
        })

    if not transcript and segments:
        transcript = "\n".join(segment["text"] for segment in segments)

    return transcript, segments


def _save_result(video_path: Path, transcript: str, segments: list[dict]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = OUTPUT_DIR / f"{video_path.stem}_transcript.json"
    payload = {
        "video": str(video_path),
        "model": DEFAULT_MODEL,
        "transcript": transcript,
        "segments": segments,
    }
    saved_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return saved_path


st.set_page_config(page_title="Video to text demo", page_icon="🎧", layout="wide")

st.title("🎧 Demo: Phân tích âm thanh từ video thành text")
st.caption("Chọn video MP4/AVI/MOV đến từ máy tính, trích xuất âm thanh và chuyển thành text bằng Whisper.")

col1, col2 = st.columns([1.5, 1])
with col1:
    uploaded_file = st.file_uploader("Chọn video", type=["mp4", "mov", "avi", "mkv", "wmv"], help="Tải file video từ máy tính để phân tích")
with col2:
    manual_path = st.text_input("Hoặc nhập đường dẫn video trên máy", value="")

selected_video = None
if uploaded_file is not None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target_path = OUTPUT_DIR / uploaded_file.name
    target_path.write_bytes(uploaded_file.getvalue())
    selected_video = target_path
    st.success(f"Đã chọn file upload: {target_path.name}")
elif manual_path.strip():
    candidate = Path(manual_path.strip())
    if candidate.exists():
        selected_video = candidate
        st.info(f"Đã chọn đường dẫn: {candidate}")
    else:
        st.warning("Đường dẫn video không tồn tại. Vui lòng chọn lại.")

if selected_video is not None:
    st.video(str(selected_video))

    # Options to reduce hallucination / prioritize fidelity
    fidelity = st.checkbox("Ưu tiên độ chính xác (giảm bịa lời, ngôn ngữ gốc)", value=True, help="Tắt dịch/translate, dùng giải thuật sinh xác định để tránh tạo nội dung không có trong âm thanh.")
    language_opt = st.selectbox("Ngôn ngữ (nếu biết)", ["auto", "vi", "en"], index=0, help="Chọn ngôn ngữ nguồn nếu biết (giúp giảm lỗi nhận dạng). Chọn 'auto' để để model tự phát hiện.")
    max_tokens = st.slider("Giới hạn tokens sinh (max_new_tokens)", min_value=64, max_value=2048, value=512)
    chunk_len = st.slider("Độ dài chunk (giây)", min_value=5, max_value=60, value=30)

    if st.button("Phân tích âm thanh → text", type="primary"):
        with st.spinner("Đang trích xuất audio từ video và dịch thành text..."):
            lang = None if language_opt == "auto" else language_opt
            try:
                result = transcribe_video(
                    str(selected_video),
                    model_id=DEFAULT_MODEL,
                    translate=not fidelity and False,
                    language=lang,
                    max_new_tokens=max_tokens,
                    chunk_length_s=chunk_len,
                )
            except Exception as exc:
                st.error(f"Lỗi khi phân tích: {exc}")
                result = {"text": "", "chunks": []}

            transcript, segments = _normalize_result(result)
            st.session_state["transcript"] = transcript
            st.session_state["segments"] = segments
            st.session_state["saved_path"] = _save_result(selected_video, transcript, segments)

    if "transcript" in st.session_state:
        transcript = st.session_state["transcript"]
        segments = st.session_state.get("segments", [])
        saved_path = st.session_state.get("saved_path")

        st.subheader("Kết quả transcription")
        st.text_area("Text đã chuyển đổi", transcript, height=220, disabled=True)

        if saved_path is not None:
            st.download_button(
                label="Tải file text",
                data=transcript.encode("utf-8"),
                file_name=saved_path.name.replace(".json", ".txt"),
                mime="text/plain",
            )

        if segments:
            st.subheader("Theo từng đoạn")
            rows = []
            for idx, seg in enumerate(segments, start=1):
                start = seg.get("start")
                end = seg.get("end")
                rows.append({
                    "#": idx,
                    "Thời gian": f"{start:.2f}s - {end:.2f}s" if start is not None and end is not None else "-",
                    "Nội dung": seg.get("text", ""),
                })
            st.dataframe(rows, use_container_width=True)
        else:
            st.info("Không tìm thấy đoạn âm thanh nào để hiển thị chi tiết.")

else:
    st.info("Vui lòng chọn một video để bắt đầu phân tích.")
