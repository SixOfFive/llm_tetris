@echo off
REM ============================================================
REM  Tetris Duel - You vs an LLM
REM  Double-click to play. On first run this creates a local
REM  virtual environment (.venv) and installs dependencies;
REM  later runs reuse it and start immediately.
REM ============================================================
setlocal
cd /d "%~dp0"

REM --- locate a Python 3 interpreter -------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo Python 3 was not found on your PATH.
  echo Install it from https://www.python.org/downloads/ ^(check "Add to PATH"^) and retry.
  echo.
  pause
  exit /b 1
)

set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"

REM --- create the virtual environment on first run ----------
if not exist "%VPY%" (
  echo Creating virtual environment in .venv ...
  %PY% -m venv "%VENV%"
  if errorlevel 1 (
    echo Failed to create the virtual environment.
    pause
    exit /b 1
  )
)

REM --- install dependencies once ----------------------------
if not exist "%VENV%\.deps_installed" (
  echo Installing dependencies ^(first run only, needs internet^) ...
  "%VPY%" -m pip install --upgrade pip
  "%VPY%" -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 (
    echo.
    echo Dependency installation failed. Check your internet connection and retry.
    pause
    exit /b 1
  )
  echo installed> "%VENV%\.deps_installed"
)

REM --- launch the game --------------------------------------
"%VPY%" "%~dp0run.py" %*
if errorlevel 1 (
  echo.
  echo The game exited with an error.
  pause
)
endlocal
