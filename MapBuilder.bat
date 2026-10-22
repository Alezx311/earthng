@echo off
setlocal
cd /d "%~dp0"
rem Map pack window. Python is this checkout only: python\ or .venv.
rem launch_builder.py checks Python, Tk and packages in this console, opens the window
rem and waits until it is shown; any failure stays on screen and in out\mapbuilder\startup.log.
if not exist "%~dp0earthng\launch_builder.py" (
  echo Map Builder files are missing next to MapBuilder.bat.
  echo Extract the ENTIRE EarthNG-MapBuilder.zip to a writable folder and run MapBuilder.bat there.
  pause
  exit /b 1
)
call :find
if not defined PY (
  call "%~dp0Setup.bat" /launcher
  if errorlevel 1 exit /b 1
  call :find
)
if not defined PY (
  echo Setup.bat did not create .venv\Scripts\python.exe.
  pause
  exit /b 1
)
"%PY%" "%~dp0earthng\launch_builder.py"
set "RC=%errorlevel%"
if "%RC%"=="0" exit /b 0
if "%RC%"=="2" goto done
rem 3: packages missing; anything else: this .venv Python cannot start. Setup.bat repairs both.

:setup
echo Running Setup.bat to repair .venv and install packages.
call "%~dp0Setup.bat" /launcher
if errorlevel 1 exit /b 1
rem Setup.bat repairs .venv only, so retry with it even when python\ was tried first.
set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" "%~dp0earthng\launch_builder.py" --after-setup
set "RC=%errorlevel%"

:done
if "%RC%"=="0" exit /b 0
if not "%RC%"=="2" (
  echo.
  echo Python at "%PY%" failed with code %RC%.
  echo Delete the .venv folder here and run MapBuilder.bat again.
)
pause
exit /b %RC%

:find
set "PY="
if exist "%~dp0python\python.exe" (
  set "PY=%~dp0python\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
)
exit /b 0
