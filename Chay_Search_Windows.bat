@echo off
title AI Camera VSS - Video Search ^& Summarizer Studio
color 0B
cls

cd /d "%~dp0CameraAI"

echo ==============================================================================
echo           AI CAMERA VSS - VIDEO SEARCH ^& SUMMARIZATION STUDIO DEMO
echo ==============================================================================
echo.

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
echo   - Dam bao may tinh dang cam day mang LAN hoac ket noi Wi-Fi noi bo co quan.
echo.
goto DRIVE_Z_DONE

:HAS_DRIVE_Z
echo [OK] O dia mang Z:\dataCameraAI - Kho video Common NAS da san sang.

:DRIVE_Z_DONE
echo.

:: [Tu dong dong bo CSDL su kien tu Common NAS neu may con chua co]
if exist "Z:\dataCameraAI\camera_metadata.db" (
    if not exist "storage\camera_metadata.db" (
        echo [*] Phat hien may con chua co CSDL su kien. Dang dong bo tu Common NAS...
        if not exist "storage" mkdir "storage"
        copy /y "Z:\dataCameraAI\camera_metadata.db" "storage\camera_metadata.db" >nul
        echo [OK] Da dong bo thanh cong toan bo CSDL su kien tu may chu!
        echo.
    )
)

echo [1/2] Kiem tra va khoi dong FastAPI Backend Server (Port 8000)...
echo [2/2] Dang mo Cua so Desktop Search Studio (pywebview)...
echo.

python app_search_win.py

if %errorlevel% neq 0 (
    echo.
    echo [LOI] Co loi khi chay ung dung.
    echo.
    pause
)
