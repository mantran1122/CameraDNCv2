"""
Test end-to-end chức năng giám sát thư mục tự động với video THẬT + kiểm tra lịch sử.
Dùng video 3 giây để main.py chạy qua pipeline thật.
Kiểm tra:
  - result_demo.json tồn tại và hợp lệ
  - outputs/history/ có file snapshot
  - outputs/analyzed_signatures.json có signature
  - File gốc bị xóa
  - Monitor stage đúng
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

TEST_WATCH_DIR = PROJ_ROOT / "tests" / "real_watch"
REAL_VIDEO = TEST_WATCH_DIR / "real_video.mp4"
TIMEOUT_SEC = 300
POLL_INTERVAL = 2


def setup():
    print("[SETUP] Preparing test watch dir...")
    if not TEST_WATCH_DIR.exists():
        TEST_WATCH_DIR.mkdir(parents=True, exist_ok=True)
    if not REAL_VIDEO.exists():
        raise FileNotFoundError(f"Real test video not found: {REAL_VIDEO}")
    print(f"[SETUP] Using real video: {REAL_VIDEO} ({REAL_VIDEO.stat().st_size} bytes)")

    (PROJ_ROOT / "outputs").mkdir(exist_ok=True)
    (PROJ_ROOT / "static").mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(exist_ok=True)

    # Clean previous signatures and result to avoid skip
    sig_path = PROJ_ROOT / "outputs" / "analyzed_signatures.json"
    if sig_path.exists():
        sig_path.unlink()
    if RESULT_PATH.exists():
        RESULT_PATH.unlink()


def teardown():
    print("[TEARDOWN] Stopping monitor...")
    stop_folder_monitor()
    time.sleep(1)
    print("[TEARDOWN] Done.")


def _wait_for(condition, timeout=30, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(interval)
    return False


def main():
    print("=" * 70)
    print("REAL FOLDER MONITOR TEST WITH HISTORY CHECK")
    print("=" * 70)

    setup()

    FOLDER_MONITOR["watch_dir"] = str(TEST_WATCH_DIR)
    print("[INFO] Starting folder monitor...")
    start_folder_monitor(api=None)
    time.sleep(1)

    start_ts = time.time()
    last_status = None
    passed = False

    try:
        while time.time() - start_ts < TIMEOUT_SEC:
            status = get_folder_monitor_status()
            status_str = json.dumps(status, ensure_ascii=False, default=str)
            if status_str != last_status:
                print(f"\n[{time.strftime('%H:%M:%S')}] Status:")
                for k, v in status.items():
                    print(f"  {k}: {v}")
                last_status = status_str

            if status["processed"] >= 1:
                print("\n[INFO] Monitor reported processed. Verifying artifacts...")
                break

            error_dir = TEST_WATCH_DIR / "error"
            if error_dir.exists() and any(error_dir.glob("*")):
                print("\n[FAIL] File moved to error/ after failed analysis.")
                return

            time.sleep(POLL_INTERVAL)
        else:
            print(f"\n[FAIL] Timeout after {TIMEOUT_SEC}s.")
            return

        # Verification 1: result_demo.json exists and valid
        assert RESULT_PATH.exists(), f"Result file missing: {RESULT_PATH}"
        result_data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        video_id = result_data.get("video_id", "")
        assert video_id, "Result missing video_id"
        print(f"  [OK] Result file exists with video_id={video_id}")

        # Verification 2: history snapshot exists
        history_file = HISTORY_DIR / f"{video_id}.json"
        assert history_file.exists(), f"History snapshot missing: {history_file}"
        hist_data = json.loads(history_file.read_text(encoding="utf-8"))
        assert hist_data.get("video_id") == video_id, "History video_id mismatch"
        print(f"  [OK] History snapshot saved: {history_file}")

        # Verification 3: signature index exists and contains signature
        sig_path = PROJ_ROOT / "outputs" / "analyzed_signatures.json"
        assert sig_path.exists(), f"Signature index missing: {sig_path}"
        sigs = json.loads(sig_path.read_text(encoding="utf-8"))
        assert isinstance(sigs, list) and len(sigs) > 0, "Signature index empty"
        print(f"  [OK] Signature index has {len(sigs)} entries")

        # Verification 4: original video deleted
        assert not REAL_VIDEO.exists(), f"Original video was NOT deleted: {REAL_VIDEO}"
        print(f"  [OK] Original video deleted from watch dir")

        # Verification 5: risk stats present in monitor status
        status = get_folder_monitor_status()
        assert status["stage"] == "completed", f"Unexpected final stage: {status['stage']}"
        print(f"  [OK] Final stage is 'completed'")

        passed = True
        print("\n" + "=" * 70)
        print("ALL CHECKS PASSED [PASS]")
        print("=" * 70)

    finally:
        teardown()
        if not passed:
            print("\n[FAIL] Test failed. See logs above.")
            sys.exit(1)


if __name__ == "__main__":
    main()
