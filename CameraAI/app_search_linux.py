import sys
import os
import shutil
import subprocess
import time
import socket
import threading
import urllib.request

TARGET_URL = "http://127.0.0.1:8000/search"

def is_server_ready(url: str = TARGET_URL, timeout: float = 1.0) -> bool:
    """Check if the backend server is responding."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CameraAI-Desktop/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 302, 307)
    except Exception:
        return False

def wait_for_server(url: str = TARGET_URL, max_wait: float = 20.0) -> bool:
    """Poll until server responds."""
    start_time = time.time()
    print(f"[Linux App] Dang ket noi toi server tai {url}...")
    while time.time() - start_time < max_wait:
        if is_server_ready(url):
            print(f"[Linux App] Server da SAN SANG! (mat {time.time() - start_time:.1f}s)")
            return True
        time.sleep(0.4)
    return False

def start_backend_if_needed():
    """Starts backend if neither Docker container nor local uvicorn is running."""
    if is_server_ready(TARGET_URL):
        print("[Linux App] Phat hien server backend (Docker/Uvicorn) dang chay tren port 8000.")
        return

    # Thu bat bang docker compose neu co docker
    if shutil.which("docker"):
        print("[Linux App] Khoi dong backend qua Docker Compose...")
        try:
            subprocess.run(["docker", "compose", "up", "-d"], check=False)
            if wait_for_server(TARGET_URL, max_wait=15.0):
                return
        except Exception as e:
            print(f"[Linux App] Khong the bat qua docker: {e}")

    # Neu khong co docker hoac docker chua chay, bat bang uvicorn trong thread
    print("[Linux App] Khoi dong FastAPI backend server truc tiep...")
    def run_uvicorn():
        try:
            import uvicorn
            from main import app as fastapi_app
            uvicorn.run(fastapi_app, host="0.0.0.0", port=8000, log_level="warning")
        except Exception as e:
            print(f"[Linux App] Loi khoi chay uvicorn: {e}")

    t = threading.Thread(target=run_uvicorn, daemon=True)
    t.start()
    wait_for_server(TARGET_URL, max_wait=20.0)

def open_standalone_window(url: str):
    """Opens a standalone Desktop App window."""
    # 1. Thu mo bang pywebview truoc
    try:
        import webview
        print("[Linux App] Dang mo cua so Desktop App (PyWebView)...")
        window = webview.create_window(
            title="AI Camera VSS - Video Search & Summarization Studio",
            url=url,
            width=1440,
            height=900,
            resizable=True,
            min_size=(960, 640)
        )
        webview.start(private_mode=False)
        return
    except Exception as e:
        print(f"[Linux App] PyWebView khong kha dung ({e}). Chuyen sang che do Standalone App Mode...")

    # 2. Fallback sang Chrome/Chromium App Mode (giao dien cua so desktop doc lap, khong co thanh dia chi)
    browsers = [
        "google-chrome",
        "google-chrome-stable",
        "chromium-browser",
        "chromium",
        "microsoft-edge",
        "brave-browser"
    ]
    for b in browsers:
        path = shutil.which(b)
        if path:
            print(f"[Linux App] Khoi dong cua so Desktop rieng biet bang {b} (--app)...")
            proc = subprocess.Popen([path, f"--app={url}", "--window-size=1440,900"])
            proc.wait()
            return

    # 3. Neu khong co cac trinh duyet tren, mo trinh duyet mac dinh
    print("[Linux App] Mo qua trinh duyet he thong mac dinh...")
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", url])
    else:
        import webbrowser
        webbrowser.open(url)

def main():
    print("==========================================================================")
    print("    AI CAMERA VSS - VIDEO SEARCH AND SUMMARIZATION (LINUX DESKTOP APP)    ")
    print("==========================================================================")
    start_backend_if_needed()
    open_standalone_window(TARGET_URL)

if __name__ == "__main__":
    main()

