#!/bin/bash
# Script khoi dong Desktop App cho CameraAI tren Linux

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================================================="
echo "          KHOI DONG CAMERAAI SEARCH STUDIO (LINUX DESKTOP APP)                "
echo "=============================================================================="

# 1. Kiem tra va khoi dong Docker backend neu chua chay
if command -v docker &> /dev/null; then
    if ! docker ps --format '{{.Names}}' | grep -q "camera-ai-service"; then
        echo "[1/2] Khoi dong backend container qua Docker Compose..."
        docker compose up -d
    else
        echo "[1/2] Backend Docker container dang chay san sang."
    fi
fi

# 2. Khoi dong Cua so Desktop App
echo "[2/2] Mo cua so ung dung Desktop..."
python3 CameraAI/app_search_linux.py || {
    echo "[Thong bao] Mo bang trinh duyet o che do App..."
    if command -v google-chrome &> /dev/null; then
        google-chrome --app="http://localhost:8000/search"
    elif command -v chromium-browser &> /dev/null; then
        chromium-browser --app="http://localhost:8000/search"
    elif command -v chromium &> /dev/null; then
        chromium --app="http://localhost:8000/search"
    else
        xdg-open "http://localhost:8000/search"
    fi
}
