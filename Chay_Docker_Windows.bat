@echo off
title Khoi Dong AI Camera DNC (Docker)
color 0B
cls

echo ==============================================================================
echo       KHOI DONG HE THONG CAMERA AI DNC - MO HINH DOCKER CONTAINER
echo ==============================================================================
echo.

docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Docker tren may tinh nay!
    echo Vui long mo Docker Desktop hoac cai dat Docker truoc khi chay.
    echo.
    pause
    exit /b 1
)

:: [Tu dong kiem tra va ket noi o dia mang Common NAS Z:]
if exist "Z:\" goto HAS_DRIVE_Z

echo [*] Dang tu dong ket noi o dia mang Common NAS...
net use Z: \\192.168.100.3\Common /persistent:yes >nul 2>&1
if exist "Z:\" (
    echo [OK] Da ket noi thanh cong o dia mang Z: - Common NAS!
) else (
    echo [!] Chua the ket noi o Z:. Neu xem clip bao thieu file, hay dam bao may dang cam mang LAN.
)
goto DRIVE_Z_DONE

:HAS_DRIVE_Z
echo [OK] O dia mang Z: - Common NAS da san sang.

:DRIVE_Z_DONE
echo.

echo [1/3] Dang build va khoi dong cac container (PostgreSQL + CameraAI)...
docker compose up -d --build

if %errorlevel% neq 0 (
    echo.
    echo [LOI] Khong the khoi dong Docker Compose.
    echo Vui long kiem tra xem Docker Desktop da chay (Running) chua.
    echo.
    pause
    exit /b 1
)

echo.
echo [2/3] Docker container da duoc khoi dong thanh cong!
echo [3/3] Dang mo trinh duyet truy cap he thong...
echo.
timeout /t 3 >nul
start http://localhost:8000/login

echo ==============================================================================
echo   HE THONG SAN SANG HOAT DONG:
echo   - Dia chi Web: http://localhost:8000/login
echo   - Tai khoan can bo giam sat: user  /  Mat khau: 123
echo   - Tai khoan quan tri vien:  admin  /  Mat khau: namcantho@168
echo ==============================================================================
echo.
pause

