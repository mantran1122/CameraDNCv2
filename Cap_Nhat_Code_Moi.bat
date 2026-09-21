@echo off
title Cap Nhat Phien Ban Moi - AI Camera DNC
color 0B
cls

echo ==============================================================================
echo             DANG DONG BO VA CAP NHAT BAN MOI NHAT TU GITHUB
echo ==============================================================================
echo.

git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] May tinh chua cai dat Git!
    echo Vui long tai va cai dat Git tai: https://git-scm.com/downloads
    echo.
    pause
    exit /b 1
)

echo [*] Dang keo ma nguon moi nhat tu nhanh main...
git fetch origin main
git reset --hard origin/main

if %errorlevel% equ 0 (
    echo.
    echo ==============================================================================
    echo [OK] DA CAP NHAT THANH CONG BAN MOI NHAT TU GITHUB!
    echo Ban co the chay lai 'Chay_Search_Windows.bat' hoac 'Chay_Docker_Windows.bat'.
    echo ==============================================================================
) else (
    echo.
    echo [LOI] Khong the keo code tu GitHub. Vui long kiem tra ket noi Internet.
)
echo.
pause
