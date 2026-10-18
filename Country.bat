@echo off
setlocal
cd /d "%~dp0"
rem Country pack window. Python is this checkout only: python\ or .venv.
set "PYW=%~dp0python\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  call "%~dp0Setup.bat"
  if errorlevel 1 exit /b 1
  set "PYW=%~dp0.venv\Scripts\pythonw.exe"
)
start "" "%PYW%" "%~dp0earthng\country_ui.py"
