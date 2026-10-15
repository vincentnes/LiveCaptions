@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Live Captions Setup

rem ---------------------------------------------------------------
rem  Step 0: choose language / 選擇語言
rem ---------------------------------------------------------------
echo ============================================
echo   Live Captions Setup
echo ============================================
echo.
echo   1. English
echo   2. 中文
echo.
choice /c 12 /n /m "Select language (1/2): "
if errorlevel 2 (set "LANGCODE=zh") else (set "LANGCODE=en")
cls

if "%LANGCODE%"=="zh" (
  set "M_TITLE=即時字幕 安裝程式"
  set "M_NET=第一次安裝需要網路，約 5 到 15 分鐘"
  set "M_NOPY=找不到合適的 Python，正在自動安裝 Python 3.12 ..."
  set "M_PYFAIL1=自動安裝失敗。請到 https://www.python.org/downloads/ 下載 Python 3.12 安裝，"
  set "M_PYFAIL2=安裝時記得勾選 Add python.exe to PATH，然後再執行一次 install.bat"
  set "M_PYOK=Python 安裝完成。請關閉這個視窗，再點兩下 install.bat 一次。"
  set "M_USING=使用"
  set "M_VENV=建立程式專用環境..."
  set "M_VENVFAIL=建立環境失敗"
  set "M_PKGS=安裝需要的元件..."
  set "M_PKGFAIL=元件安裝失敗，請確認網路後再執行一次 install.bat"
  set "M_NOGPU=沒有偵測到 NVIDIA 顯示卡，將使用 CPU 模式。"
  set "M_GPU=偵測到 NVIDIA 顯示卡，安裝 GPU 加速元件，檔案較大請稍候..."
  set "M_GPUFAIL=GPU 元件安裝失敗，程式仍可用 CPU 模式執行。"
) else (
  set "M_TITLE=Live Captions Setup"
  set "M_NET=First install needs internet and takes about 5-15 minutes"
  set "M_NOPY=Python 3.10-3.12 not found. Installing Python 3.12 with winget..."
  set "M_PYFAIL1=Automatic install failed. Please install Python 3.12 from https://www.python.org/downloads/"
  set "M_PYFAIL2=tick Add python.exe to PATH during setup, then run install.bat again."
  set "M_PYOK=Python installed. Please close this window and run install.bat again."
  set "M_USING=Using"
  set "M_VENV=Creating virtual environment..."
  set "M_VENVFAIL=Failed to create the virtual environment."
  set "M_PKGS=Installing required packages..."
  set "M_PKGFAIL=Package installation failed. Check your internet connection and run install.bat again."
  set "M_NOGPU=No NVIDIA GPU detected - CPU mode will be used."
  set "M_GPU=NVIDIA GPU detected - installing GPU acceleration, this is a large download..."
  set "M_GPUFAIL=GPU packages failed to install; the program will still work in CPU mode."
)

title !M_TITLE!
echo ============================================
echo   !M_TITLE!
echo   !M_NET!
echo ============================================
echo.

rem ---------------------------------------------------------------
rem  Step 1: Python
rem ---------------------------------------------------------------
set "PY="
for %%V in (3.12 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)

if not defined PY (
  echo !M_NOPY!
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo !M_PYFAIL1!
    echo !M_PYFAIL2!
    pause
    exit /b 1
  )
  echo.
  echo !M_PYOK!
  pause
  exit /b 0
)

echo !M_USING!: !PY!
if not exist "venv\Scripts\python.exe" (
  echo !M_VENV!
  !PY! -m venv venv
  if errorlevel 1 (
    echo !M_VENVFAIL!
    pause
    exit /b 1
  )
)

rem ---------------------------------------------------------------
rem  Step 2: packages
rem ---------------------------------------------------------------
echo.
echo !M_PKGS!
"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo !M_PKGFAIL!
  pause
  exit /b 1
)

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo.
  echo !M_NOGPU!
) else (
  echo.
  echo !M_GPU!
  "venv\Scripts\python.exe" -m pip install -r requirements-gpu.txt
  if errorlevel 1 echo !M_GPUFAIL!
)

rem ---------------------------------------------------------------
rem  Step 3: icon, models, shortcuts (in the chosen language)
rem ---------------------------------------------------------------
echo.
"venv\Scripts\python.exe" setup_helper.py --lang %LANGCODE%
echo.
pause
