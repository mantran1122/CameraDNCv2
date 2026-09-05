"""
Test nhanh (mock): Folder monitor tu dong phat hien file moi them vao
ngay ca khi dang chay, khong can khoi dong lai app.
Kich ban: xu ly xong file 1 -> them file 2 -> worker phat hien va xu ly file 2.
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
    _SIGNATURE_INDEX_PATH,
    RESULT_PATH,
)

TEST_DIR = PROJ_ROOT / "tests" / "mock_dynamic"
TIMEOUT = 30


def setup():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    if _SIGNATURE_INDEX_PATH.exists():
        _SIGNATURE_INDEX_PATH.unlink()
    if RESULT_PATH.exists():
        RESULT_PATH.unlink()


def teardown():
    stop_folder_monitor()
    time.sleep(0.5)
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    if _SIGNATURE_INDEX_PATH.exists():
        _SIGNATURE_INDEX_PATH.unlink()
    if RESULT_PATH.exists():
        RESULT_PATH.unlink()


def _fake_run_analysis_subprocess(video_path, progress_callback=None):
    """Fake analysis: write a valid result JSON and return ok."""
    fake = {
        "video_id": f"demo-{video_path.stem}",
        "video_file": str(video_path),
        "segments": [
            {"start": "00:00:01", "end": "00:00:05", "risk_level": "low", "description": "Test"}
        ],
        "video_summary": {"overview": "Test summary", "meaning": "Test meaning"},
    }
    RESULT_PATH.write_text(json.dumps(fake, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress_callback:
        for line in ["Prepared 1 segment", "Saved segment 1 / 1", "Done. Result saved to: /tmp/x.json"]:
            progress_callback(line)
    return True, None, 1.0, ["fake"]


def _create_fake_video(name: str, content: bytes) -> Path:
    path = TEST_DIR / name
    path.write_bytes(content)
    return path


def _wait_for(condition, timeout=30, interval=0.3):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(interval)
    return False


def main():
    print("=" * 70)
    print("MOCK DYNAMIC FILE DETECTION TEST")
    print("=" * 70)

    import app.streamlit_app as sa
    orig_run = sa._run_analysis_subprocess
    sa._run_analysis_subprocess = _fake_run_analysis_subprocess

    setup()
    try:
        # Pre-place video1
        v1 = _create_fake_video("v1.mp4", b"fake_video_content_111")
        FOLDER_MONITOR["watch_dir"] = str(TEST_DIR)
        start_folder_monitor(api=None)
        time.sleep(0.5)

        # Wait for video1 processed
        ok = _wait_for(lambda: FOLDER_MONITOR["processed_count"] >= 1, timeout=TIMEOUT)
        assert ok, f"Video1 not processed. Status: {get_folder_monitor_status()}"
        print("[+] Video1 processed")
        assert not v1.exists(), "Video1 should be deleted"
        print("[+] Video1 deleted")

        # Now add video2 while monitor is still running
        v2 = _create_fake_video("v2.mp4", b"fake_video_content_222")
        print("[+] Video2 added to watch dir")

        # Wait for video2 processed
        ok = _wait_for(lambda: FOLDER_MONITOR["processed_count"] >= 2, timeout=TIMEOUT)
        assert ok, f"Video2 not processed. Status: {get_folder_monitor_status()}"
        print("[+] Video2 processed")
        assert not v2.exists(), "Video2 should be deleted"
        print("[+] Video2 deleted")

        # Verify signatures
        sigs = json.loads(_SIGNATURE_INDEX_PATH.read_text(encoding="utf-8"))
        assert len(sigs) == 2, f"Expected 2 signatures, got {len(sigs)}"
        print(f"[+] Signature index has {len(sigs)} entries")

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED [PASS]")
        print("=" * 70)
    finally:
        sa._run_analysis_subprocess = orig_run
        teardown()


if __name__ == "__main__":
    main()
