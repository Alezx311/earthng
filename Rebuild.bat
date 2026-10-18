@echo off
rem Rebuild earthng_planet.zip and copy it into the BeamNG mods folder.
rem English UI. A saved settings\earthng.json language still wins after the game starts.
set "PY=%~dp0python\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Python for this repository was not found.
  echo   %~dp0python\python.exe
  echo   %~dp0.venv\Scripts\python.exe
  echo Create the environment in the EarthNG root:
  echo   py -3.13 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements-fast.txt
  pause
  exit /b 1
)
set "USER=%LOCALAPPDATA%\BeamNG\BeamNG.drive\current"
if not exist "%USER%\mods" set "USER=%LOCALAPPDATA%\BeamNG.drive\current"
if not exist "%USER%" (
  echo BeamNG user folder was not found.
  echo   %LOCALAPPDATA%\BeamNG\BeamNG.drive\current
  pause
  exit /b 1
)
tasklist /FI "IMAGENAME eq BeamNG.drive.exe" | find /I "BeamNG.drive.exe" >nul
if not errorlevel 1 echo BeamNG.drive is open. Close it if the copy is refused, then run this again.
"%PY%" "%~dp0earthng\build_mod.py" --out "%~dp0out\mod" --install "%USER%" --lang en
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo Installed %USER%\mods\earthng_planet.zip
echo Restart BeamNG so it reads the new planet zip.
pause
