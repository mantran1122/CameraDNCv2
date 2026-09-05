"""
Test end-to-end chức năng giám sát thư mục tự động với video THẬT.
Dùng video 3 giây để main.py có thể đi qua get_video_info và prepare_video_chunks.
Nếu model loading quá lâu (>60s), script sẽ kill subprocess để tránh treo.
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
)

TEST_WATCH_DIR = PROJ_ROOT / "tests" / "real_watch"
REAL_VIDEO = TEST_WATCH_DIR / "real_video.mp4"
TIMEOUT_SEC = 180
POLL_INTERVAL = 2
MODEL_LOADING_TIMEOUT = 60  # Kill if stuck at model loading too long


def setup():
    print("[SETUP] Preparing test watch dir...")
    if not TEST_WATCH_DIR.exists():
        TEST_WATCH_DIR.mkdir(parents=True, exist_ok=True)
    if not REAL_VIDEO.exists():
        raise FileNotFoundError(f"Real test video not found: {REAL_VIDEO}")
    print(f"[SETUP] Using real video: {REAL_VIDEO} ({REAL_VIDEO.stat().st_size} bytes)")

    (PROJ_ROOT / "outputs").mkdir(exist_ok=True)
    (PROJ_ROOT / "static").mkdir(exist_ok=True)
    sig_path = PROJ_ROOT / "outputs" / "analyzed_signatures.json"
    if sig_path.exists():
        sig_path.unlink()


def teardown():
    print("[TEARDOWN] Stopping monitor...")
    stop_folder_monitor()
    time.sleep(1)
    print("[TEARDOWN] Done.")


def main():
    print("=" * 70)
    print("REAL FOLDER MONITOR TEST WITH REAL VIDEO")
    print("=" * 70)

    setup()

    FOLDER_MONITOR["watch_dir"] = str(TEST_WATCH_DIR)
    print("[INFO] Starting folder monitor...")
    start_folder_monitor(api=None)
    time.sleep(1)

    start_ts = time.time()
    model_loading_start = None
    last_status = None

    try:
        while time.time() - start_ts < TIMEOUT_SEC:
            status = get_folder_monitor_status()
            status_str = json.dumps(status, ensure_ascii=False, default=str)
            if status_str != last_status:
                print(f"\n[{time.strftime('%H:%M:%S')}] Status:")
                for k, v in status.items():
                    print(f"  {k}: {v}")
                last_status = status_str

            # Detect if stuck at model loading
            if status.get("stage") == "model_loading":
                if model_loading_start is None:
                    model_loading_start = time.time()
                elif time.time() - model_loading_start > MODEL_LOADING_TIMEOUT:
                    print("\n[TIMEOUT] Stuck at model_loading too long, killing subprocess...")
                    proc = FOLDER_MONITOR.get("process")
                    if proc is not None and hasattr(proc, "kill"):
                        try:
                            proc.kill()
                            proc.wait(timeout=5)
                        except Exception:
                            pass
                    # After kill, monitor should treat it as failure and retry
                    model_loading_start = None
                    time.sleep(2)
                    continue
            else:
                model_loading_start = None

            if status["processed"] >= 1:
                print("\n[PASS] Video processed successfully!")
                break

            error_dir = TEST_WATCH_DIR / "error"
            if error_dir.exists() and any(error_dir.glob("*")):
                print("\n[PASS] File correctly moved to error/ after failed analysis.")
                break

            if status["skipped"] >= 1 and not REAL_VIDEO.exists():
                print("\n[PASS] File skipped and removed.")
                break

            time.sleep(POLL_INTERVAL)
        else:
            print(f"\n[TIMEOUT] Test did not complete within {TIMEOUT_SEC}s.")
            print("Final status:", get_folder_monitor_status())

    except KeyboardInterrupt:
        print("\n[INTERRUPT] Test interrupted.")
    finally:
        teardown()


if __name__ == "__main__":
    main()
