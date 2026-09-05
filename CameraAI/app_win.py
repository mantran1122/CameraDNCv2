import sys
import os
import time
import threading
import webview
import uvicorn

from main import app as fastapi_app
import config

def start_fastapi_server():
    """Starts FastAPI background server on localhost:8000"""
    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000, log_level="error")

def main():
    print("==========================================================================")
    print("  Dahua AI DHI-NVR5832-EI2 - Metadata & Anomaly Summarizer (Windows App)")
    print("==========================================================================")
    print("[Windows App] Starting background API server on http://127.0.0.1:8000 ...")

    # Start FastAPI server in daemon thread
    server_thread = threading.Thread(target=start_fastapi_server, daemon=True)
    server_thread.start()

    # Give server a second to bind to port
    time.sleep(1.5)

    print("[Windows App] Opening Native Windows App Window...")
    
    # Create Native Windows Application Window using pywebview
    window = webview.create_window(
        title="Dahua WizMind AI NVR5832-EI2 - Metadata & 10s Clip Summarizer",
        url="http://127.0.0.1:8000",
        width=1380,
        height=880,
        resizable=True,
        min_size=(900, 600)
    )

    # Start native Windows UI event loop
    webview.start(private_mode=False)

if __name__ == "__main__":
    main()
