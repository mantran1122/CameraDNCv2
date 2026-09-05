"""
Test chức năng giám sát thư mục tự động (folder monitor).
Chạy: python tests/test_folder_monitor.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

# Ensure project root is on path
PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJ_ROOT))

from app.streamlit_app import (
    FOLDER_MONITOR,
    _cleanup_partial_analysis,
    _clear_existing_analysis,
    _get_file_signature,
    _is_video_already_analyzed,
    _load_signature_index,
    _save_signature_index,
    _SIGNATURE_INDEX_PATH,
    start_folder_monitor,
    stop_folder_monitor,
    get_folder_monitor_status,
    RESULT_PATH,
    OUTPUTS_DIR,
)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
TEST_WATCH_DIR = PROJ_ROOT / "tests" / "test_watch_folder"
FAKE_VIDEO_NAME = "test_video.mp4"

# Backup original functions to restore later
_original_run_analysis = None


def _fake_run_analysis_subprocess(video_path, progress_callback=None):
    """
    Fake analysis subprocess that immediately creates a valid result JSON
    so the monitor thinks analysis succeeded.
    """
    # Write a fake result so the monitor can parse risk stats
    fake_result = {
        "video_id": "test_vid_001",
        "video_file": str(video_path),
        "segments": [
            {"start": "00:00:01", "end": "00:00:05", "risk_level": "high", "description": "Test high risk"},
            {"start": "00:00:06", "end": "00:00:10", "risk_level": "medium", "description": "Test medium risk"},
            {"start": "00:00:11", "end": "00:00:15", "risk_level": "low", "description": "Test low risk"},
        ],
        "video_summary": {"overview": "Test summary", "meaning": "Test meaning"},
    }
    RESULT_PATH.write_text(json.dumps(fake_result, ensure_ascii=False, indent=2), encoding="utf-8")

    # Invoke callback with some fake progress lines so stage detection runs
    if progress_callback:
        for line in ["Loading model...", "Prepared 3 segments", "Saved segment 1 / 3", "Summary done", "Complete"]:
            progress_callback(line)

    return True, None, 1.0, ["fake log"]


def setup_test_env():
    """Prepare test directories and monkey-patch analysis subprocess."""
    global _original_run_analysis

    # Clean old test watch dir
    if TEST_WATCH_DIR.exists():
        shutil.rmtree(TEST_WATCH_DIR)
    TEST_WATCH_DIR.mkdir(parents=True, exist_ok=True)

    # Backup signature index if exists
    if _SIGNATURE_INDEX_PATH.exists():
        shutil.copy(str(_SIGNATURE_INDEX_PATH), str(_SIGNATURE_INDEX_PATH) + ".backup")
        _SIGNATURE_INDEX_PATH.unlink()

    # Monkey-patch
    import app.streamlit_app as sa
    _original_run_analysis = sa._run_analysis_subprocess
    sa._run_analysis_subprocess = _fake_run_analysis_subprocess

    # Ensure static dir exists for copy target
    sa.STATIC_DIR.mkdir(exist_ok=True)


def teardown_test_env():
    """Restore patched functions and clean up test artifacts."""
    global _original_run_analysis
    import app.streamlit_app as sa
    if _original_run_analysis is not None:
        sa._run_analysis_subprocess = _original_run_analysis
        _original_run_analysis = None

    stop_folder_monitor()

    if TEST_WATCH_DIR.exists():
        shutil.rmtree(TEST_WATCH_DIR)

    # Restore signature index
    backup = Path(str(_SIGNATURE_INDEX_PATH) + ".backup")
    if backup.exists():
        shutil.copy(str(backup), str(_SIGNATURE_INDEX_PATH))
        backup.unlink()
    elif _SIGNATURE_INDEX_PATH.exists():
        _SIGNATURE_INDEX_PATH.unlink()

    # Clean fake result if created
    if RESULT_PATH.exists():
        RESULT_PATH.unlink()


def _create_fake_video(folder: Path, name: str, content: bytes = None) -> Path:
    """Create a fake video file (not a real mp4, but with correct extension)."""
    path = folder / name
    data = content or b"\x00\x00\x00\x20ftypmp42"  # minimal mp4-ish header
    path.write_bytes(data)
    return path


def _wait_for(condition, timeout=30, interval=0.5):
    """Wait until condition() is True or timeout."""
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(interval)
    return False


def test_monitor_detects_and_processes_new_video():
    print("\n[TEST 1] Monitor detects new video and processes it")
    setup_test_env()

    try:
        # Start monitor pointing to test dir
        FOLDER_MONITOR["watch_dir"] = str(TEST_WATCH_DIR)
        start_folder_monitor(api=None)

        # Wait a bit for worker to start
        time.sleep(1)
        assert FOLDER_MONITOR["running"], "Monitor should be running"
        print("  [+] Monitor started")

        # Create a fake video
        video = _create_fake_video(TEST_WATCH_DIR, FAKE_VIDEO_NAME)
        expected_sig = _get_file_signature(video)
        print(f"  [+] Created fake video: {video} | sig={expected_sig}")

        # Wait until the monitor marks it processed
        def _processed():
            return FOLDER_MONITOR["processed_count"] >= 1

        ok = _wait_for(_processed, timeout=15)
        assert ok, f"Monitor did not process video in time. Status: {get_folder_monitor_status()}"
        print("  [+] Video processed")

        # The original file should be deleted after successful analysis
        def _file_deleted():
            return not video.exists()

        ok = _wait_for(_file_deleted, timeout=10)
        assert ok, "Original video was not deleted after processing"
        print("  [+] Original video deleted")

        # Signature should be saved
        sig_index = _load_signature_index()
        assert expected_sig in sig_index, f"Signature {expected_sig} not in index {sig_index}"
        print("  [+] Signature saved to index")

        # Risk stats should be populated
        status = get_folder_monitor_status()
        assert status["high_risk_count"] == 1, f"Expected 1 high risk, got {status['high_risk_count']}"
        assert status["medium_risk_count"] == 1, f"Expected 1 medium risk, got {status['medium_risk_count']}"
        assert status["low_risk_count"] == 1, f"Expected 1 low risk, got {status['low_risk_count']}"
        print("  [+] Risk stats populated correctly")

    finally:
        teardown_test_env()
        print("  [+] Teardown complete")


def test_monitor_skips_duplicate_video():
    print("\n[TEST 2] Monitor skips duplicate video and deletes it")
    setup_test_env()

    try:
        # Pre-populate signature index with a known signature
        video = _create_fake_video(TEST_WATCH_DIR, FAKE_VIDEO_NAME, content=b"duplicate_test_content_123")
        sig = _get_file_signature(video)
        _save_signature_index({sig})
        print(f"  [+] Pre-saved signature {sig}")

        # Start monitor
        FOLDER_MONITOR["watch_dir"] = str(TEST_WATCH_DIR)
        start_folder_monitor(api=None)
        time.sleep(1)

        # Wait for monitor to detect and skip
        def _skipped():
            return FOLDER_MONITOR["skipped_count"] >= 1

        ok = _wait_for(_skipped, timeout=15)
        assert ok, f"Monitor did not skip duplicate in time. Status: {get_folder_monitor_status()}"
        print("  [+] Duplicate skipped")

        # Original should be deleted after skip
        def _file_deleted():
            return not video.exists()

        ok = _wait_for(_file_deleted, timeout=10)
        assert ok, "Duplicate video was not deleted after skipping"
        print("  [+] Duplicate video deleted")

    finally:
        teardown_test_env()
        print("  [+] Teardown complete")


def test_stop_monitor_cleans_up():
    print("\n[TEST 3] Stop monitor cleans up current file and partial results")
    setup_test_env()

    try:
        # Create a fake video
        video = _create_fake_video(TEST_WATCH_DIR, FAKE_VIDEO_NAME)
        FOLDER_MONITOR["watch_dir"] = str(TEST_WATCH_DIR)
        start_folder_monitor(api=None)
        time.sleep(1)

        # Wait until current_file is set (meaning it picked up the video)
        def _picked_up():
            return FOLDER_MONITOR.get("current_file", "") != ""

        ok = _wait_for(_picked_up, timeout=10)
        assert ok, "Monitor did not pick up video"
        print(f"  [+] Monitor picked up: {FOLDER_MONITOR['current_file']}")

        # Stop monitor
        stop_folder_monitor()
        time.sleep(1)

        assert not FOLDER_MONITOR["running"], "Monitor should not be running after stop"
        assert FOLDER_MONITOR.get("current_file", "") == "", "current_file should be cleared"
        print("  [+] Monitor stopped and state cleared")

    finally:
        teardown_test_env()
        print("  [+] Teardown complete")


def test_nonexistent_watch_dir():
    print("\n[TEST 4] Monitor handles nonexistent watch directory gracefully")
    setup_test_env()

    try:
        nonexistent = PROJ_ROOT / "tests" / "nonexistent_folder_12345"
        if nonexistent.exists():
            shutil.rmtree(nonexistent)

        FOLDER_MONITOR["watch_dir"] = str(nonexistent)
        start_folder_monitor(api=None)
        time.sleep(1)
        assert FOLDER_MONITOR["running"], "Monitor should still be running"
        print("  [+] Monitor running despite nonexistent dir")

        # Message should mention the missing directory path
        status = get_folder_monitor_status()
        msg = status["message"]
        assert "nonexistent_folder_12345" in msg, f"Unexpected message: {msg}"
        safe_msg = msg.encode("ascii", "replace").decode("ascii")
        print(f"  [+] Correct error message: {safe_msg}")

    finally:
        teardown_test_env()
        print("  [+] Teardown complete")


def main():
    print("=" * 60)
    print("FOLDER MONITOR AUTOMATED TESTS")
    print("=" * 60)

    # Ensure we are in a clean state before starting
    stop_folder_monitor()
    time.sleep(0.5)

    test_monitor_detects_and_processes_new_video()
    test_monitor_skips_duplicate_video()
    test_stop_monitor_cleans_up()
    test_nonexistent_watch_dir()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED [PASS]")
    print("=" * 60)


if __name__ == "__main__":
    main()
