@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.13 -m venv .venv
  if errorlevel 1 (
    echo Install Python 3.13 for Windows with Tcl/Tk and the Python launcher, then retry.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install -r requirements-fast.txt
if errorlevel 1 (
  echo Dependency installation failed. Check the messages above and retry Setup.bat.
  pause
  exit /b 1
)
echo EarthNG Map Builder is ready.
