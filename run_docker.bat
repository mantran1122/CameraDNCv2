@echo off
title CameraAI - Docker Container Launcher
color 0B
cls

echo ==============================================================================
echo          KHOI DONG CAMERAAI DAHUA SUMMARIZER QUA DOCKER CONTAINER            
echo ==============================================================================
echo.

where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo [Loi] Khong tim thay Docker! Vui long cai Docker Desktop tren Windows truoc.
    echo Hoac tiep tuc chay bang file Chay_Search_Windows.bat hien tai.
    pause
    exit /b 1
)

if not exist "CameraAI\.env" (
    if exist "CameraAI\.env.example" (
        echo [Khoi tao] Tao file CameraAI\.env tu file mau CameraAI\.env.example...
        copy "CameraAI\.env.example" "CameraAI\.env" >nul
    )
)

echo [1/3] Kiem tra va dung container cu (neu co)...
docker compose down

echo [2/3] Build va khoi chay CameraAI container...
docker compose up -d --build

echo [3/3] Khoi dong thanh cong!
echo.
echo -> Truy cap Web App tai: http://localhost:8000/search
echo -> Xem log: docker compose logs -f
echo -> Dung container: docker compose down
echo ==============================================================================
echo.
pause

