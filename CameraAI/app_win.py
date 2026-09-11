import sys
import os
import time
import socket
import threading
import subprocess
import urllib.request
import webview
import uvicorn

from main import app as fastapi_app
import config

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if port is already active."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0
def is_server_ready(url: str = "http://127.0.0.1:8000/search", timeout: float = 1.0) -> bool:
    """Check if the backend server is actually responding with valid HTTP status."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CameraAI-Desktop/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 302, 307)
    except Exception:
        return False

def free_port_if_dead(port: int = 8000):
    """If port is held by an unresponsive process, terminate it to allow clean startup."""
    if not is_server_ready():
        try:
            out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True)
            for line in out.strip().splitlines():
                if "LISTENING" in line:
                    parts = line.strip().split()
                    pid = int(parts[-1])
                    if pid > 0 and pid != os.getpid():
                        print(f"[Windows App] Freeing unresponsive process (PID {pid}) on port {port}...")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        time.sleep(0.5)
        except Exception:
            pass

def wait_for_server(url: str = "http://127.0.0.1:8000/search", max_wait: float = 20.0) -> bool:
    """Poll until server responds, printing progress."""
    start_time = time.time()
    print(f"[Windows App] Dang cho Web Server khoi dong tai {url} ...")
    while time.time() - start_time < max_wait:
        if is_server_ready(url):
            print(f"[Windows App] Server da SAN SANG! (mat {time.time() - start_time:.1f} giay)")
            return True
        time.sleep(0.4)
    return False

def start_fastapi_server():
    """Starts FastAPI background server on localhost:8000"""
    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000, log_level="error")
    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000, log_level="warning")

def main():
    print("==========================================================================")
    print("  AI CAMERA VSS - METADATA, SEARCH & VIDEO SUMMARIZER (WINDOWS APP)")
    print("==========================================================================")

    target_url = "http://127.0.0.1:8000/search"

    if is_port_in_use(8000):
        print("[Windows App] Detected existing server on port 8000. Connecting directly...")
    if is_server_ready(target_url):
        print("[Windows App] Tim thay server dang chay tren port 8000. Ket noi truc tiep...")
    else:
        print("[Windows App] Starting background API server on http://127.0.0.1:8000 ...")
        # Start FastAPI server in daemon thread
        free_port_if_dead(8000)
        print("[Windows App] Dang khoi dong FastAPI background server tren http://127.0.0.1:8000 ...")
        server_thread = threading.Thread(target=start_fastapi_server, daemon=True)
        server_thread.start()
        # Give server a second to bind to port
        time.sleep(1.5)
        
        # Doi server san sang thuc su roi moi mo cua so
        if not wait_for_server(target_url, max_wait=20.0):
            print("[Windows App] Canh bao: Server khoi dong lau hon du kien. Tiep tuc mo cua so...")

    print(f"[Windows App] Opening Native Windows App Window ({target_url})...")
    print(f"[Windows App] Dang mo cua so ung dung Desktop ({target_url})...")
    
    # Create Native Windows Application Window using pywebview
    # Tao cua so Native Windows pywebview
    window = webview.create_window(
        title="AI Camera VSS - Video Search & Summarizer Studio",
        url=target_url,
        width=1440,
        height=900,
        resizable=True,
        min_size=(960, 640)
    )

    # Start native Windows UI event loop
    webview.start(private_mode=False)
    # Bat dau UI loop
    webview.start(private_mode=False, debug=True)

if __name__ == "__main__":
    main()
