@echo off
cd /d %~dp0

set TEMP=%CD%\local_env\pip_temp
set TMP=%CD%\local_env\pip_temp
set PIP_CACHE_DIR=%CD%\local_env\pip_cache
set HF_HOME=%CD%\local_env\hf_cache
set HUGGINGFACE_HUB_CACHE=%CD%\local_env\hf_cache\hub
set TRANSFORMERS_CACHE=%CD%\local_env\hf_cache\transformers
set TORCH_HOME=%CD%\local_env\torch_cache

call local_env\.venv\Scripts\activate

python -c "import sys, torch; print('python:', sys.executable); print('torch:', torch.__version__); print('torch cuda:', torch.version.cuda); print('cuda available:', torch.cuda.is_available()); print('gpu:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA'); print('capability:', torch.cuda.get_device_capability(0) if torch.cuda.is_available() else 'NO CUDA'); print('recommended profile: rtx5070ti_16gb')"

pause
