"""Comprehensive system diagnostic script for Camera AI.
Run locally or inside docker container:
    python diagnose_system.py
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

# Force UTF-8 stdout
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import config

def banner(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def diagnose_sqlite():
    banner("1. KIEM TRA CO SO DU LIEU SQLITE (camera_metadata.db)")
    db_path = config.STORAGE_DIR / "camera_metadata.db"
    print(f"[+] Duong dan DB: {db_path}")
    if not db_path.is_file():
        print(f"[-] FILE DB KHONG TON TAI: {db_path}")
        return

    size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"[+] Kich thuoc DB: {size_mb:.2f} MB")

    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM events")
        total_events = c.fetchone()[0]
        print(f"[+] Tong so su kien da luu: {total_events}")

        # Count events by day for recent dates
        print("\n--- Phan bo su kien theo ngay (7 ngay gan nhat) ---")
        c.execute("""
            SELECT substr(timestamp, 1, 10) as dt, COUNT(*),
                   SUM(CASE WHEN clip_filename IS NOT NULL THEN 1 ELSE 0 END) as with_clips
            FROM events
            GROUP BY dt
            ORDER BY dt DESC
            LIMIT 10
        """)
        rows = c.fetchall()
        for r in rows:
            print(f"    Ngay {r[0]}: {r[1]} su kien (co {r[2]} video clips)")

        # Specifically check 2026-09-25
        print("\n--- Chi tiet ngay 25/09/2026 ---")
        c.execute("""
            SELECT COUNT(*) FROM events 
            WHERE timestamp >= '2026-09-25 00:00:00' AND timestamp <= '2026-09-25 23:59:59'
        """)
        cnt_25 = c.fetchone()[0]
        print(f"    Tong su kien ngay 25/09: {cnt_25}")

        c.execute("""
            SELECT MIN(timestamp), MAX(timestamp) FROM events 
            WHERE timestamp >= '2026-09-25 00:00:00' AND timestamp <= '2026-09-25 23:59:59'
        """)
        min_ts, max_ts = c.fetchone()
        print(f"    Su kien dau tien ngay 25/09 : {min_ts}")
        print(f"    Su kien CUOI CUNG ngay 25/09: {max_ts}")

        # Events after 14:38 on 25/09
        c.execute("""
            SELECT COUNT(*) FROM events WHERE timestamp >= '2026-09-25 14:38:00'
        """)
        cnt_after_1438 = c.fetchone()[0]
        print(f"    So su kien ghi nhan SAU 14h38 ngay 25/09: {cnt_after_1438}")

        # Check latest 5 events overall
        print("\n--- 5 SU KIEN MOI NHAT HE THONG GHI NHAN ---")
        c.execute("""
            SELECT id, timestamp, event_code, channel, severity, clip_filename
            FROM events
            ORDER BY id DESC
            LIMIT 5
        """)
        latest = c.fetchall()
        for row in latest:
            print(f"    ID={row[0]} | Thoi gian={row[1]} | Code={row[2]} | Cam Ch={row[3]} | Clip={row[5]}")

        # Audio analyses status
        print("\n--- Trang thai Audio Analyses ---")
        c.execute("""
            SELECT status, COUNT(*) FROM audio_analyses GROUP BY status
        """)
        for r in c.fetchall():
            print(f"    Trang thai '{r[0]}': {r[1]}")

        conn.close()
    except Exception as e:
        print(f"[-] Loi truy van SQLite: {e}")

def diagnose_local_storage():
    banner("2. KIEM TRA BO NHO LOCAL MAY CHU (storage/clips)")
    clips_dir = Path(config.CLIPS_DIR).resolve()
    print(f"[+] Thu muc luu tru local: {clips_dir}")

    if not clips_dir.is_dir():
        print(f"[-] Thu muc khong ton tai: {clips_dir}")
        return

    # Count all mp4 files
    mp4_files = list(clips_dir.rglob("*.mp4"))
    total_bytes = sum(f.stat().st_size for f in mp4_files)
    total_mb = total_bytes / (1024 * 1024)
    print(f"[+] Tong so video clip mp4 tren may chu: {len(mp4_files)} files ({total_mb:.2f} MB)")

    # Sort by modification time
    mp4_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    print("\n--- 5 Video Clip moi nhat tren o dia local may chu ---")
    for f in mp4_files[:5]:
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size_kb = f.stat().st_size / 1024
        rel = f.relative_to(clips_dir)
        print(f"    - [{mtime}] {size_kb:.1f} KB: {rel}")

    # Check clips created around 25/09
    clips_25 = [
        f for f in mp4_files 
        if "2026/09/25" in f.as_posix() or "20260925" in f.name
    ]
    print(f"\n[+] So clip luu ngay 25/09 tren o dia may chu: {len(clips_25)} clips")
    if clips_25:
        clips_25.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        newest_25 = clips_25[0]
        mtime_newest = datetime.fromtimestamp(newest_25.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"    -> Clip cuoi cung ngay 25/09 tren disk: {newest_25.name} (mtime: {mtime_newest})")

def diagnose_nas():
    banner("3. KIEM TRA KET NOI SYNOLOGY NAS")
    import synology_storage
    print(f"[+] STORAGE_BACKEND: {config.STORAGE_BACKEND}")
    print(f"[+] NAS URL        : {config.SYNOLOGY_URL}")
    print(f"[+] NAS Username   : {config.SYNOLOGY_USERNAME}")
    print(f"[+] NAS Share      : {config.SYNOLOGY_SHARE}")
    print(f"[+] NAS Root       : {config.SYNOLOGY_ROOT}")
    print(f"[+] Verify TLS     : {config.SYNOLOGY_VERIFY_TLS}")

    if not synology_storage.enabled():
        print("[-] Synology NAS KHONG DUOC BAT trong cau hinh!")
        return

    try:
        with synology_storage.client() as api:
            print("[+] Dang nhap Synology FileStation API THANH CONG! SID:", api.sid[:8] + "...")
            # Try to list root
            root_path = synology_storage.remote_path(".").rstrip("/.")
            print(f"[+] Dang kiem tra thu muc NAS: {root_path}")
            try:
                res = api.list_folder(root_path)
                files = res.get("files", [])
                print(f"[+] Thu muc goc tren NAS hop le. Co {len(files)} muc con:")
                for item in files[:5]:
                    is_dir = "[DIR]" if item.get("isdir") else "[FILE]"
                    print(f"    - {is_dir} {item.get('name')}")
            except Exception as e:
                print(f"[-] Loi doc thu muc NAS {root_path}: {e}")

            # Check day folder for 2026/09/25
            print("\n--- Kiem tra thu muc ngay 2026/09/25 tren NAS ---")
            found_any = False
            for ch in range(1, 33):
                cam_code = f"cam-{ch:03d}"
                day_path = synology_storage.remote_path(f"cameras/{cam_code}/2026/09/25")
                try:
                    day_res = api.list_folder(day_path)
                    day_files = [f for f in day_res.get("files", []) if not f.get("isdir")]
                    if day_files:
                        print(f"    [+] Cam {ch:02d} co {len(day_files)} clips tren NAS ngay 25/09")
                        found_any = True
                except Exception:
                    pass
            if not found_any:
                print("    [-] Khong tim thay thu muc/clip nao ngay 25/09 tren NAS.")
    except Exception as exc:
        print(f"[-] LOI KET NOI SYNOLOGY NAS: {exc}")

def diagnose_nvr():
    banner("4. KIEM TRA KET NOI DAHUA NVR")
    import requests
    from requests.auth import HTTPDigestAuth

    protocol = "https" if (config.USE_HTTPS or config.NVR_PORT in (443, 4443, 8443)) else "http"
    nvr_url = f"{protocol}://{config.NVR_HOST}:{config.NVR_PORT}"
    print(f"[+] NVR Host: {config.NVR_HOST}:{config.NVR_PORT} ({protocol.upper()})")
    print(f"[+] NVR User: {config.NVR_USER}")
    print(f"[+] RTSP Port: {config.RTSP_PORT}")

    # Test HTTP connection
    event_url = f"{nvr_url}/cgi-bin/eventManager.cgi?action=attach&codes=[All]"
    print(f"[+] Thu ket noi eventManager: {event_url}")
    try:
        auth = HTTPDigestAuth(config.NVR_USER, config.NVR_PASSWORD)
        r = requests.get(event_url, auth=auth, stream=True, timeout=10, verify=False)
        print(f"[+] NVR Tra ve HTTP Status Code: {r.status_code}")
        if r.status_code == 200:
            print("[+] Ket noi luong su kien NVR THANH CONG!")
            r.close()
        elif r.status_code == 401:
            print("[-] NVR tu choi xac thuc (401 Unauthorized)! Kiem tra NVR_USER / NVR_PASSWORD.")
        else:
            print(f"[-] NVR tra ve ma loi: {r.status_code}")
    except Exception as e:
        print(f"[-] LOI KET NOI NVR: {e}")

if __name__ == "__main__":
    banner("BAT DAU CHUAN DOAN TOAN DIEN HE THONG CAMERA AI")
    print("Thoi gian chay:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    diagnose_sqlite()
    diagnose_local_storage()
    diagnose_nas()
    diagnose_nvr()
    banner("KET THUC CHUAN DOAN")
