#!/bin/bash
# Script chay CameraAI bang Docker tren Linux / WSL

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================================================="
echo "          KHOI DONG CAMERAAI DAHUA SUMMARIZER QUA DOCKER CONTAINER            "
echo "=============================================================================="

# Kiem tra docker
if ! command -v docker &> /dev/null; then
    echo "[Loi] Khong tim thay Docker! Vui long cai dat Docker truoc khi chay:"
    echo "  Ubuntu/Debian: sudo apt update && sudo apt install -y docker.io docker-compose-plugin"
    exit 1
fi

echo "[1/3] Kiem tra va dung container cu neu dang chay..."
docker compose down || true

echo "[2/3] Build va khoi chay CameraAI container..."
docker compose up -d --build

echo "[3/3] Dang khoi dong thanh cong!"
echo ""
echo "-> Truy cap Web App tai: http://localhost:8000/search (hoac http://<IP_MAY>:8000/search)"
echo "-> Xem logs thoi gian thuc: docker compose logs -f"
echo "-> Dung he thong: docker compose down"
echo "=============================================================================="

