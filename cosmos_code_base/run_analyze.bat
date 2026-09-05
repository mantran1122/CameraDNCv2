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
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

call local_env\.venv\Scripts\activate

python main.py ^
  --video static/demo.mp4 ^
  --model nvidia/Cosmos-Reason2-2B ^
  --model-backend vllm ^
  --gpu-memory-utilization 0.77 ^
  --max-model-len 52224 ^
  --vllm-batch-size 2 ^
  --hardware-profile rtx5070ti_16gb ^
  --output outputs/result_demo.json ^
  --chunks-dir outputs/chunks ^
  --vector-db outputs/lancedb

pause
