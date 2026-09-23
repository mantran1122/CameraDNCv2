@echo off
setlocal
title CameraAI Web Server Host - Port 8000
color 0A
cd /d "%~dp0"

echo ==============================================================================
echo           CAMERAAI VSS - HOST SERVER LAUNCHER (PORT 8000)
echo ==============================================================================
echo.

:: 1. Kiem tra Python
where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay Python tren may tinh!
    echo Vui long cai dat Python 3.10 hoac 3.11 va tich chon "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:: 2. Tu dong tao file .env neu chua co
if not exist ".env" (
    if exist ".env.example" (
        echo [*] Chua co file .env, dang tu dong tao tu .env.example...
        copy /y ".env.example" ".env" >nul
        echo [OK] Da khoi tao file .env thanh cong!
    )
)

:: 3. Tu dong tao thu muc storage
if not exist "storage" mkdir storage
if not exist "storage\clips" mkdir storage\clips

:: 4. Kiem tra va tu dong cai dat thu vien Python neu thieu
python -c "import fastapi, uvicorn, requests, pydantic, jinja2, cv2, imageio, psycopg, dotenv" >nul 2>nul
if errorlevel 1 (
    echo [*] Dang kiem tra va cai dat cac goi thu vien can thiet tu requirements.txt...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [CANH BAO] Co loi khi cai dat requirements. Dang thu khoi dong...
    )
)

:: 5. Tim dia chi IP LAN cua may chu
set "CAMERAAI_IP=localhost"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$u=[Net.Sockets.UdpClient]::new(); try {$u.Connect('8.8.8.8',53); $u.Client.LocalEndPoint.Address.IPAddressToString} finally {$u.Dispose()}" 2^>nul`) do set "CAMERAAI_IP=%%I"

:: 6. Kiem tra cong 8000 da chay chua
netstat -ano -p tcp | findstr /R /C:":8000 .*LISTENING" >nul
if not errorlevel 1 (
    echo.
    echo [THONG BAO] CameraAI da va dang chay tren cong 8000!
    echo   - Truy cap tren may nay : http://localhost:8000/login
    echo   - May khac trong mang LAN : http://%CAMERAAI_IP%:8000/login
    echo.
    pause
    exit /b 0
)

echo.
echo ==============================================================================
echo [OK] SERVER DANG HOAT DONG TREN TAT CA CARD MANG (0.0.0.0:8000)
echo ==============================================================================
echo.
echo   [+] Truy cap tren MAY CHU nay  : http://localhost:8000/login
echo   [+] Truy cap tu CAC MAY KHAC   : http://%CAMERAAI_IP%:8000/login
echo.
echo   [*] Nhan Ctrl+C de dung server bat cu luc nao.
echo ==============================================================================
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8000

if errorlevel 1 (
    echo.
    echo [LOI] Server bi dung dot ngot hoac gap su co.
    pause
)
