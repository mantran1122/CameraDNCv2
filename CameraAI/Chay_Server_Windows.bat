@echo off
setlocal
title CameraAI Web Server - Port 8000
cd /d "%~dp0"

set "CAMERAAI_IP=localhost"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$u=[Net.Sockets.UdpClient]::new(); try {$u.Connect('8.8.8.8',53); $u.Client.LocalEndPoint.Address.IPAddressToString} finally {$u.Dispose()}"`) do set "CAMERAAI_IP=%%I"

netstat -ano -p tcp | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
    echo CameraAI da chay san tren cong 8000.
    echo May nay: http://localhost:8000/login
    echo May khac: http://%CAMERAAI_IP%:8000/login
    echo Khong can mo them mot server thu hai.
    pause
    exit /b 0
)

echo CameraAI dang lang nghe tren tat ca card mang tai cong 8000.
echo May nay: http://localhost:8000/login
echo May khac: http://%CAMERAAI_IP%:8000/login
echo Nhan Ctrl+C de dung server.
python -m uvicorn main:app --host 0.0.0.0 --port 8000
if errorlevel 1 pause
