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

:: [Tu dong kiem tra va ket noi kho video Common NAS Z:]
if exist "Z:\dataCameraAI" goto HAS_DRIVE_Z

echo [*] Dang kiem tra ket noi o dia mang Common NAS (\\192.168.100.3\Common)...
net use Z: \\192.168.100.3\Common /persistent:yes >nul 2>&1

if exist "Z:\dataCameraAI" (
    echo [OK] Da ket noi thanh cong o dia mang Z:\dataCameraAI - Kho video Common NAS!
    goto DRIVE_Z_DONE
)

if exist "\\192.168.100.3\Common\dataCameraAI" (
    echo [OK] Da tim thay kho video qua dia chi mang \\192.168.100.3\Common\dataCameraAI!
    goto DRIVE_Z_DONE
)

echo.
echo [!] CHU Y KHO VIDEO NAS:
echo   Chua the doc thu muc video 'dataCameraAI' tu \\192.168.100.3\Common.
echo   - Neu ban dang dung may moi/may con: Hay mo File Explorer, go:
echo     \\192.168.100.3\Common roi Enter de nhap User/Pass mang noi bo (neu duoc hoi).
echo   - Luu y: Chay qua Docker can chia se thu muc mang voi Docker Desktop.
echo     Neu muon xem video nhanh nhat, hay dung 'Chay_Search_Windows.bat'.
echo.
goto DRIVE_Z_DONE

:HAS_DRIVE_Z
echo [OK] O dia mang Z:\dataCameraAI - Kho video Common NAS da san sang.

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

