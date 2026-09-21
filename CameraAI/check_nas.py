import sys
from pathlib import Path

# Add CameraAI to sys.path
base_dir = Path(__file__).resolve().parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

import config
import clip_storage
import sqlite3

print(f"    [>] config.CLIPS_DIR: {config.CLIPS_DIR}")
print(f"    [>] Thu muc co ton tai va doc duoc: {config.CLIPS_DIR.is_dir()}")

db_path = base_dir / "storage" / "camera_metadata.db"
if db_path.is_file():
    try:
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("SELECT id, channel, timestamp, clip_filename FROM events WHERE clip_filename IS NOT NULL AND clip_filename != '' ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        if row:
            ev_id, ch, ts, clip_name = row
            resolved = clip_storage.resolve_clip_path(clip_name)
            exists = resolved.is_file()
            print(f"    [>] Su kien gan nhat trong CSDL: #{ev_id} (Kenh {ch} luc {ts})")
            print(f"    [>] Ten clip CSDL: {clip_name}")
            print(f"    [>] Duong dan thuc te tim thay: {resolved}")
            status_text = "[OK] File video ton tai san sang phat!" if exists else "[!] KHONG TIM THAY file video nay tren o dia."
            print(f"    [>] Ket qua kiem tra: {status_text}")
        else:
            print("    [>] CSDL chua co ban ghi video nao.")
    except Exception as e:
        print(f"    [!] Loi doc CSDL: {e}")
else:
    print("    [!] Chua tim thay file camera_metadata.db.")
