@echo off
cd /d %~dp0

set TEMP=%CD%\local_env\pip_temp
set TMP=%CD%\local_env\pip_temp
set PIP_CACHE_DIR=%CD%\local_env\pip_cache
set HF_HOME=%CD%\local_env\hf_cache
set HUGGINGFACE_HUB_CACHE=%CD%\local_env\hf_cache\hub
set TRANSFORMERS_CACHE=%CD%\local_env\hf_cache\transformers
set SENTENCE_TRANSFORMERS_HOME=%CD%\local_env\hf_cache\sentence_transformers
set TORCH_HOME=%CD%\local_env\torch_cache
set CUDA_MODULE_LOADING=LAZY
set PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.85,max_split_size_mb:256
set TRANSFORMERS_VERBOSITY=error
set TOKENIZERS_PARALLELISM=false
set OMP_NUM_THREADS=8
set MKL_NUM_THREADS=8
set COSMOS_HARDWARE_PROFILE=rtx5070ti_16gb
set COSMOS_MODEL_BACKEND=transformers
set COSMOS_GPU_MEMORY_UTILIZATION=0.77
set COSMOS_MAX_MODEL_LEN=52224
set COSMOS_VLLM_BATCH_SIZE=2
set COSMOS_PLAYBACK_MODE=fast
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set VENV_PYTHON=%CD%\local_env\.venv\Scripts\python.exe
if not exist "%VENV_PYTHON%" (
  echo Missing venv python: %VENV_PYTHON%
  echo Run install_D.bat first.
  pause
  exit /b 1
)

"%VENV_PYTHON%" -m streamlit run app\streamlit_app.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true --browser.gatherUsageStats=false

pause
