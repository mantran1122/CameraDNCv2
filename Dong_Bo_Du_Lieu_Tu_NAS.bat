@echo off
title Dong Bo CSDL Tu Common NAS - AI Camera DNC
color 0B
cls

echo ==============================================================================
echo           DONG BO CSDL SU KIEN CAMERA TU KHO CHUNG (COMMON NAS Z:)
echo ==============================================================================
echo.

if not exist "Z:\dataCameraAI\camera_metadata.db" (
    echo [LOI] Khong tim thay file CSDL tren o NAS: Z:\dataCameraAI\camera_metadata.db
    echo Vui long dam bao o Z: da ket noi dung va co quyen truy cap.
    echo.
    pause
    exit /b 1
)

echo [*] Dang sao chep CSDL su kien (camera_metadata.db) tu Common NAS...
if not exist "CameraAI\storage" mkdir "CameraAI\storage"
copy /y "Z:\dataCameraAI\camera_metadata.db" "CameraAI\storage\camera_metadata.db"

if %errorlevel% equ 0 (
    echo.
    echo ==============================================================================
    echo [OK] DA DONG BO CSDL THANH CONG!
    echo May con bay gio da co toan bo su kien va lien ket video clip tu may chu.
    echo Ban co the mo 'Chay_Search_Windows.bat' de tim kiem va hoi Vision Agent.
    echo ==============================================================================
) else (
    echo.
    echo [LOI] Co loi trong qua trinh sao chep CSDL. Vui long thu lai.
)
echo.
pause

