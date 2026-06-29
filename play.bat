@echo off
REM ============================================================
REM  Tetris Duel - You vs an LLM
REM  Double-click this file to play.
REM ============================================================
cd /d "%~dp0"

python run.py %*

if errorlevel 1 (
  echo.
  echo The game exited with an error.
  echo If Python modules are missing, install them with:
  echo     pip install -r requirements.txt
  echo.
  pause
)
