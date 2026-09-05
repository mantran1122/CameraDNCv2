@echo off
cd /d %~dp0

echo Cleaning local temporary/cache folders, keeping venv...
if exist local_env\pip_temp rmdir /s /q local_env\pip_temp
if exist local_env\pip_cache rmdir /s /q local_env\pip_cache
if exist local_env\torch_cache rmdir /s /q local_env\torch_cache

mkdir local_env\pip_temp
mkdir local_env\pip_cache
mkdir local_env\torch_cache

echo Done.
pause
