#!/usr/bin/env bash
set -e

echo "=============================================================================="
echo "      KHOI DONG HE THONG CAMERA AI DNC - MO HINH DOCKER (LINUX/SERVER)"
echo "=============================================================================="

if ! command -v docker &> /dev/null; then
    echo "[LOI] Docker chua duoc cai dat tren may nay."
    exit 1
fi

echo "[1/2] Dang build va khoi dong container..."
docker compose up -d --build

echo ""
echo "[2/2] Khoi dong thanh cong!"
echo "=============================================================================="
echo "  Truy cap he thong tai: http://localhost:8000/login"
echo "  - Tai khoan can bo giam sat: user  /  Mat khau: 123"
echo "  - Tai khoan quan tri vien:  admin  /  Mat khau: namcantho@168"
echo "=============================================================================="
