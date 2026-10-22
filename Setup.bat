@echo off
setlocal
cd /d "%~dp0"
rem Creates .venv with Python 3.13 and installs requirements-fast.txt.
rem MapBuilder.bat passes /launcher: no pause after success, it opens the window next.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo The existing .venv cannot start its Python; it is recreated.
    goto create
  )
  goto install
)

:create
py -3.13 -m venv --clear .venv
if errorlevel 1 (
  echo.
  echo Python 3.13 was not found through the "py" launcher.
  echo Install Python 3.13 for Windows from https://www.python.org/downloads/windows/
  echo and tick "tcl/tk and IDLE" and "py launcher" in the installer, then run MapBuilder.bat again.
  pause
  exit /b 1
)

:install
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-fast.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Check the messages above, your internet connection
  echo and antivirus, then run Setup.bat again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "%~dp0earthng\launch_builder.py" --check --after-setup
if errorlevel 1 (
  pause
  exit /b 1
)
echo EarthNG Map Builder is ready.
if /i not "%~1"=="/launcher" (
  echo Run MapBuilder.bat to open the window.
  pause
)
exit /b 0
