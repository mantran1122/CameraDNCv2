@echo off
title AI Camera VSS - Video Search ^& Summarizer Studio
color 0B
cls

echo ==============================================================================
echo           AI CAMERA VSS - VIDEO SEARCH ^& SUMMARIZATION STUDIO DEMO
echo ==============================================================================
echo.

:: [Tu dong kiem tra va ket noi o dia mang Common NAS Z:]
if not exist "Z:\" (
    echo [*] Dang tu dong ket noi o dia mang Common (\\192.168.100.3\Common sang o Z:)...
    net use Z: \\192.168.100.3\Common /persistent:yes >nul 2>&1
    if exist "Z:\" (
        echo [OK] Da ket noi thanh cong o dia mang Z: (Common NAS)!
    ) else (
        echo [!] Chua the ket noi o Z:. Neu xem clip bao thieu file, hay dam bao may dang cam mang LAN noi bo.
    )
) else (
    echo [OK] O dia mang Z: (Common NAS) da san sang.
)
echo.

echo [1/2] Kiem tra va khoi dong FastAPI Backend Server (Port 8000)...
echo [2/2] Dang mo Cua so Desktop Search Studio (pywebview)...
echo.

python app_search_win.py

pause

