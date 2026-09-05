import PyInstaller.__main__
import os
import shutil

print("==========================================================================")
print("  Building Standalone Windows Executable (.exe) for Dahua AI Summarizer")
print("==========================================================================")

# Clean up previous builds
if os.path.exists("build"):
    shutil.rmtree("build")
if os.path.exists("dist"):
    shutil.rmtree("dist")

# PyInstaller command arguments
args = [
    'app_win.py',
    '--name=Dahua_AI_Summarizer',
    '--onefile',
    '--noconfirm',
    '--windowed',
    '--add-data=static;static',
    '--add-data=templates;templates',
    '--hidden-import=fastapi',
    '--hidden-import=uvicorn',
    '--hidden-import=pydantic',
    '--hidden-import=jinja2',
    '--hidden-import=cv2',
    '--hidden-import=requests',
    '--hidden-import=sqlite3',
    '--hidden-import=webview',
]

print("Running PyInstaller...")
PyInstaller.__main__.run(args)

print("==========================================================================")
print("  Build completed! Executable located at: dist/Dahua_AI_Summarizer.exe")
print("==========================================================================")
