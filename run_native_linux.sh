#!/bin/bash
# Script chay CameraAI truc tiep bang Python native tren Linux (khong can Docker)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/CameraAI"

echo "=============================================================================="
echo "          KHOI DONG CAMERAAI DAHUA SUMMARIZER (PYTHON NATIVE LINUX)           "
echo "=============================================================================="

# 1. Kiem tra Python 3
if ! command -v python3 &> /dev/null; then
    echo "[Loi] Khong tim thay Python 3. Vui long cai dat bang lenh:"
    echo "  sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg"
    exit 1
fi

# 2. Kiem tra FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "[Canh bao] Chua cai dat FFmpeg! Vui long cai dat: sudo apt install -y ffmpeg"
fi

# 3. Tao va kich hoat virtual environment
if [ ! -d "venv" ]; then
    echo "[1/3] Tao moi truong ao Python venv..."
    python3 -m venv venv
fi

echo "[2/3] Kich hoat venv va cai dat dependencies..."
source venv/bin/activate
pip install -U pip setuptools wheel
pip install -r requirements.txt

# 4. Dam bao thu muc storage ton tai
mkdir -p storage/clips

# 5. Khoi dong FastAPI server
echo "[3/3] Khoi dong server tai cong 8000..."
echo ""
echo "-> Truy cap Web App tai: http://localhost:8000/search (hoac http://<IP_MAY>:8000/search)"
echo "-> Nhan Ctrl + C de dung server."
echo "=============================================================================="

exec uvicorn main:app --host 0.0.0.0 --port 8000

