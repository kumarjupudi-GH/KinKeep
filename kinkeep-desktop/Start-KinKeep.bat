@echo off
rem Double-click this file to start KinKeep. The first time it also sets itself up (a few minutes, needs internet once).
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed yet.
  echo A download page will open. Install Python, TICK "Add python.exe to PATH" on the first screen, then double-click this file again.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup. Please wait, this takes a few minutes...
  py -3 -m venv .venv
  if errorlevel 1 goto fail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m kinkeep_desktop
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo Something went wrong. Please take a photo or screenshot of this window and send it to whoever is helping you.
pause
exit /b 1
