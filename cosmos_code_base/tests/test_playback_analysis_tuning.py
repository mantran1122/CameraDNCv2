from pathlib import Path

import numpy as np

from app.streamlit_app import PLAYBACK_INBOX, _analysis_args
from src.video_utils import _build_ffmpeg_chunk_command, _frame_to_image, build_direct_chunk_manifest


def _flag_value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_playback_uses_fast_analysis_defaults(monkeypatch) -> None:
    for name in (
        "COSMOS_PLAYBACK_CHUNK_SECONDS",
        "COSMOS_PLAYBACK_SAMPLE_FPS",
        "COSMOS_PLAYBACK_MAX_NEW_TOKENS",
        "COSMOS_PLAYBACK_CHUNK_ENCODER",
        "COSMOS_PLAYBACK_MAX_IMAGE_SIDE",
        "COSMOS_PLAYBACK_CLEANUP_EVERY",
        "COSMOS_PLAYBACK_DEVICE_MAP",
        "COSMOS_PLAYBACK_MODE",
    ):
        monkeypatch.delenv(name, raising=False)

    args = _analysis_args(PLAYBACK_INBOX / "recording.mp4", run_in_wsl=False)

    assert _flag_value(args, "--chunk-seconds") == "90"
    assert _flag_value(args, "--sample-fps") == "0.025"
    assert _flag_value(args, "--max-new-tokens") == "192"
    assert _flag_value(args, "--chunk-encoder") == "copy"
    assert _flag_value(args, "--max-image-side") == "768"
    assert _flag_value(args, "--cleanup-every") == "1"
    assert _flag_value(args, "--device-map") == "cuda:0"
    assert "--direct-sampling" in args


def test_regular_upload_does_not_force_playback_tuning(monkeypatch, tmp_path: Path) -> None:
    for name in (
        "COSMOS_CHUNK_SECONDS",
        "COSMOS_SAMPLE_FPS",
        "COSMOS_MAX_NEW_TOKENS",
        "COSMOS_CHUNK_ENCODER",
    ):
        monkeypatch.delenv(name, raising=False)

    args = _analysis_args(tmp_path / "upload.mp4", run_in_wsl=False)

    assert "--chunk-seconds" not in args
    assert "--sample-fps" not in args
    assert "--max-new-tokens" not in args
    assert "--chunk-encoder" not in args
    assert "--direct-sampling" not in args


def test_playback_balanced_mode_can_be_selected(monkeypatch) -> None:
    monkeypatch.setenv("COSMOS_PLAYBACK_MODE", "balanced")
    for name in (
        "COSMOS_PLAYBACK_CHUNK_SECONDS",
        "COSMOS_PLAYBACK_SAMPLE_FPS",
        "COSMOS_PLAYBACK_MAX_NEW_TOKENS",
        "COSMOS_PLAYBACK_MAX_IMAGE_SIDE",
    ):
        monkeypatch.delenv(name, raising=False)

    args = _analysis_args(PLAYBACK_INBOX / "recording.mp4", run_in_wsl=False)

    assert _flag_value(args, "--chunk-seconds") == "30"
    assert _flag_value(args, "--sample-fps") == "0.1"
    assert _flag_value(args, "--max-image-side") == "960"


def test_copy_encoder_does_not_reencode_video(tmp_path: Path) -> None:
    command = _build_ffmpeg_chunk_command(
        ffmpeg="ffmpeg",
        video_path=tmp_path / "source.mp4",
        chunk_path=tmp_path / "chunk.mp4",
        start_seconds=30,
        duration_seconds=30,
        encoder="copy",
    )

    assert command[command.index("-c:v") + 1] == "copy"
    assert "h264_nvenc" not in command
    assert "libx264" not in command


def test_direct_manifest_does_not_create_chunk_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.video_utils.get_video_info",
        lambda _path: {"duration_seconds": 65.0},
    )

    chunks = build_direct_chunk_manifest(tmp_path / "source.mp4", chunk_seconds=30)

    assert len(chunks) == 3
    assert [chunk["path"] for chunk in chunks] == ["", "", ""]
    assert chunks[-1]["start_seconds"] == 60.0
    assert chunks[-1]["end_seconds"] == 65.0


def test_sampled_frame_is_downscaled_before_model_input() -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    image = _frame_to_image(frame, max_image_side=960)

    assert image.size == (960, 540)
