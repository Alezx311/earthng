@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
set NoDefaultCurrentDirectoryInExePath=
cd /d %~dp0
cargo %*
