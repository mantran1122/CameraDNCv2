@echo off
cd /d %~dp0

echo ============================================================
echo  Cosmos Video Analyzer - Install on D/project local folders
echo ============================================================

if not exist local_env mkdir local_env
if not exist local_env\pip_temp mkdir local_env\pip_temp
if not exist local_env\pip_cache mkdir local_env\pip_cache
if not exist local_env\hf_cache mkdir local_env\hf_cache
if not exist local_env\torch_cache mkdir local_env\torch_cache

set TEMP=%CD%\local_env\pip_temp
set TMP=%CD%\local_env\pip_temp
set PIP_CACHE_DIR=%CD%\local_env\pip_cache
set HF_HOME=%CD%\local_env\hf_cache
set HUGGINGFACE_HUB_CACHE=%CD%\local_env\hf_cache\hub
set TRANSFORMERS_CACHE=%CD%\local_env\hf_cache\transformers
set SENTENCE_TRANSFORMERS_HOME=%CD%\local_env\hf_cache\sentence_transformers
set TORCH_HOME=%CD%\local_env\torch_cache

echo TEMP=%TEMP%
echo PIP_CACHE_DIR=%PIP_CACHE_DIR%
echo HF_HOME=%HF_HOME%
echo SENTENCE_TRANSFORMERS_HOME=%SENTENCE_TRANSFORMERS_HOME%
echo TORCH_HOME=%TORCH_HOME%

if exist local_env\.venv (
    echo Removing old venv...
    rmdir /s /q local_env\.venv
)

set "PYTHON_CMD="
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.12"

if not defined PYTHON_CMD (
    python -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 12) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo No compatible Python found. Python 3.11 or 3.12 is required.
    echo Current Python, if available:
    python --version
    echo Install Python 3.12, reopen the terminal, then run this script again.
    pause
    exit /b 1
)

echo Using Python command: %PYTHON_CMD%
echo Creating venv...
%PYTHON_CMD% -m venv local_env\.venv
if errorlevel 1 (
    echo Failed to create venv with: %PYTHON_CMD%
    pause
    exit /b 1
)

call local_env\.venv\Scripts\activate

python -m pip install --upgrade pip setuptools wheel

echo Removing old conflicting packages if any...
pip uninstall -y torch torchvision torchaudio transformers accelerate

echo Installing PyTorch CUDA 13.0...
pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130

if errorlevel 1 (
    echo.
    echo CUDA 13.0 install failed. Trying CUDA 12.8...
    pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
)

echo Installing project dependencies...
pip install --no-cache-dir --upgrade -r requirements_windows.txt
if errorlevel 1 (
    echo Failed to install Windows dependencies.
    pause
    exit /b 1
)

echo.
echo Checking GPU...
python -c "import torch; print('torch:', torch.__version__); print('torch cuda:', torch.version.cuda); print('cuda available:', torch.cuda.is_available()); print('gpu:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"

echo.
echo Install finished.
pause
