"""
Test: Folder monitor phat hien va xu ly file moi NGAY LAP TUC khi dang chay.
Khong can khoi dong lai app.
Kich ban 1: Monitor chay tren thu muc trong -> them file -> phan tich ngay.
Kich ban 2: Monitor xu ly xong file 1 -> them file 2 -> phan tich file 2 ngay.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJ_ROOT))

from app.streamlit_app import (
    FOLDER_MONITOR,
    start_folder_monitor,
    stop_folder_monitor,
    get_folder_monitor_status,
    RESULT_PATH,
    HISTORY_DIR,
)

TEST_WATCH_DIR = PROJ_ROOT / "tests" / "dynamic_watch"
VIDEO1 = TEST_WATCH_DIR / "video1.mp4"
VIDEO2 = TEST_WATCH_DIR / "video2.mp4"
TIMEOUT_SEC = 400
POLL_INTERVAL = 2


def _create_test_video(path: Path, duration_sec: int = 3):
    """Create a small real H.264 video using ffmpeg."""
    cmd = (
        f'ffmpeg -f lavfi -i testsrc=duration={duration_sec}:size=320x240:rate=1 '
        f'-pix_fmt yuv420p "{path}" -y'
    )
    ret = os.system(cmd)
    if ret != 0 or not path.exists():
        raise RuntimeError(f"Failed to create test video: {path}")


def _clean():
    if TEST_WATCH_DIR.exists():
        shutil.rmtree(TEST_WATCH_DIR)
    TEST_WATCH_DIR.mkdir(parents=True, exist_ok=True)
    (PROJ_ROOT / "outputs").mkdir(exist_ok=True)
    (PROJ_ROOT / "static").mkdir(exist_ok=True)
    if HISTORY_DIR.exists():
        shutil.rmtree(HISTORY_DIR)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    sig_path = PROJ_ROOT / "outputs" / "analyzed_signatures.json"
    if sig_path.exists():
        sig_path.unlink()
    if RESULT_PATH.exists():
        RESULT_PATH.unlink()


def teardown():
    print("[TEARDOWN] Stopping monitor...")
    stop_folder_monitor()
    time.sleep(1)
    if TEST_WATCH_DIR.exists():
        shutil.rmtree(TEST_WATCH_DIR)
    print("[TEARDOWN] Done.")


def test_monitor_detects_file_added_while_running():
    print("\n[TEST 1] Monitor detects new file added while running (empty -> file)")
    _clean()

    # Start monitor on empty dir
    FOLDER_MONITOR["watch_dir"] = str(TEST_WATCH_DIR)
    start_folder_monitor(api=None)
    time.sleep(2)
    assert FOLDER_MONITOR["running"], "Monitor should be running"
    print("  [+] Monitor started on empty dir")

    # Create and copy video into watch dir
    _create_test_video(VIDEO1, duration_sec=3)
    print(f"  [+] Created video1: {VIDEO1} ({VIDEO1.stat().st_size} bytes)")

    # Wait for monitor to process it
    def _done():
        return FOLDER_MONITOR["processed_count"] >= 1

    ok = _wait_for(_done, timeout=TIMEOUT_SEC)
    assert ok, f"Monitor did not process newly added video. Status: {get_folder_monitor_status()}"
    print("  [+] Video1 processed")

    # Verify result exists
    assert RESULT_PATH.exists(), "Result file missing after processing"
    print("  [+] Result file exists")

    # Verify history
    result_data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    vid = result_data.get("video_id", "")
    assert (HISTORY_DIR / f"{vid}.json").exists(), "History snapshot missing"
    print(f"  [+] History saved: {vid}")

    # Verify video1 deleted
    assert not VIDEO1.exists(), "Original video1 was not deleted"
    print("  [+] Original video1 deleted")


def test_monitor_processes_second_file_immediately():
    print("\n[TEST 2] Monitor processes second file immediately after first")
    _clean()

    # Pre-create video1 and video2 with DIFFERENT durations so signatures differ
    _create_test_video(VIDEO1, duration_sec=3)
    _create_test_video(VIDEO2, duration_sec=5)

    # Start monitor (video1 already exists)
    FOLDER_MONITOR["watch_dir"] = str(TEST_WATCH_DIR)
    start_folder_monitor(api=None)
    time.sleep(1)

    # Wait for video1 to be processed
    def _v1_done():
        return FOLDER_MONITOR["processed_count"] >= 1
    ok = _wait_for(_v1_done, timeout=TIMEOUT_SEC)
    assert ok, "Monitor did not process video1"
    print("  [+] Video1 processed")
    assert not VIDEO1.exists(), "Video1 was not deleted"

    # Now copy video2 into the same watch dir
    # (It was created above but outside watch dir; copy it in now)
    dest2 = TEST_WATCH_DIR / VIDEO2.name
    shutil.copy(str(VIDEO2), str(dest2))
    print(f"  [+] Copied video2 into watch dir: {dest2}")

    # Wait for video2 to be processed
    def _v2_done():
        return FOLDER_MONITOR["processed_count"] >= 2
    ok = _wait_for(_v2_done, timeout=TIMEOUT_SEC)
    assert ok, f"Monitor did not process video2. Status: {get_folder_monitor_status()}"
    print("  [+] Video2 processed")

    # Verify video2 deleted
    assert not dest2.exists(), "Original video2 was not deleted"
    print("  [+] Original video2 deleted")

    # Verify signatures has 2 entries
    sig_path = PROJ_ROOT / "outputs" / "analyzed_signatures.json"
    sigs = json.loads(sig_path.read_text(encoding="utf-8"))
    assert len(sigs) == 2, f"Expected 2 signatures, got {len(sigs)}"
    print(f"  [+] Signature index has {len(sigs)} entries")


def _wait_for(condition, timeout=30, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(interval)
    return False


def main():
    print("=" * 70)
    print("FOLDER MONITOR DYNAMIC FILE DETECTION TEST")
    print("=" * 70)
    try:
        test_monitor_detects_file_added_while_running()
        test_monitor_processes_second_file_immediately()
        print("\n" + "=" * 70)
        print("ALL TESTS PASSED [PASS]")
        print("=" * 70)
    finally:
        teardown()


if __name__ == "__main__":
    main()
