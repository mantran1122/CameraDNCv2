@echo off
title Kiem Tra Ket Noi O Dia NAS Z: - AI Camera DNC
color 0B
cls

echo ==============================================================================
echo        CONG CU KIEM TRA KET NOI KHO VIDEO NAS (O DIA Z: VSS BLUEPRINT)
echo ==============================================================================
echo.

echo [1] Kiem tra ket noi o dia Z: trong Windows...
net use | findstr /I "Z:"
if %errorlevel% equ 0 (
    echo     -^> Windows da ghi nhan o dia Z:.
) else (
    echo     -^> [CANH BAO] Windows chua ket noi o dia Z:!
)
echo.

echo [2] Kiem tra thu muc video Z:\dataCameraAI...
if exist "Z:\dataCameraAI" (
    echo     -^> [OK] Thu muc Z:\dataCameraAI ton tai va doc duoc!
    echo     -^> Danh sach cac thu muc con:
    dir /b "Z:\dataCameraAI"
) else (
    echo     -^> [LOI] Khong the truy cap Z:\dataCameraAI!
    echo     Nguyen nhan: Chua dang nhap mat khau mang noi bo hoac o Z bi ngat ket noi.
)
echo.

echo [3] Kiem tra duong dan mang truc tiep \\192.168.100.3\Common\dataCameraAI...
if exist "\\192.168.100.3\Common\dataCameraAI" (
    echo     -^> [OK] Duong dan mang LAN truc tiep hoat dong tot!
) else (
    echo     -^> [LOI] Khong the truy cap duong dan mang LAN!
    echo     Kiem tra xem may da cam day mang LAN hoac ket noi Wi-Fi noi bo chua.
)
echo.

echo [4] Kiem tra qua Python Backend (CLIPS_DIR va resolve_clip_path)...
python "%~dp0CameraAI\check_nas.py"
echo.

echo ==============================================================================
echo HUONG DAN XU LY NEU BAO LOI:
echo   1. Nhan to hop phim: Windows + R
echo   2. Nhap: \\192.168.100.3\Common roi Enter
echo   3. Neu hoi User/Pass: Nhap thong tin mang noi bo va tich Remember my credentials
echo ==============================================================================
echo.
pause

