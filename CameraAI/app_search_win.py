import sys
import os
import time
import socket
import threading
import urllib.request
import webview
import uvicorn

from main import app as fastapi_app
import config

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if port is already listening."""
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

def wait_for_server(url: str = "http://127.0.0.1:8000/search", max_wait: float = 20.0) -> bool:
    """Poll until server responds, printing progress."""
    start_time = time.time()
    print(f"[Windows App] Waiting for server at {url} to become ready...")
    while time.time() - start_time < max_wait:
        if is_server_ready(url):
            print(f"[Windows App] Server is READY and responding! (took {time.time() - start_time:.1f}s)")
            return True
        time.sleep(0.4)
    return False

def start_fastapi_server():
    """Starts FastAPI background server on localhost:8000"""
    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000, log_level="warning")

def main():
    print("==========================================================================")
    print("    AI CAMERA VSS - VIDEO SEARCH AND SUMMARIZATION (WINDOWS APP DEMO)     ")
    print("==========================================================================")

    target_url = "http://127.0.0.1:8000/search"

    if is_server_ready(target_url):
        print("[Windows App] Detected existing server on port 8000. Connecting directly...")
    else:
        print("[Windows App] Starting background API server on http://127.0.0.1:8000 ...")
        server_thread = threading.Thread(target=start_fastapi_server, daemon=True)
        server_thread.start()
        time.sleep(1.5)
        if not wait_for_server(target_url, max_wait=20.0):
            print("[Windows App] Warning: Server took too long to respond. Opening window anyway...")

    print(f"[Windows App] Opening Search Studio App Window ({target_url})...")
    
    window = webview.create_window(
        title="AI Camera VSS - Video Search Studio",
        url=target_url,
        width=1440,
        height=900,
        resizable=True,
        min_size=(960, 640)
    )

    webview.start(private_mode=False)

if __name__ == "__main__":
    main()
