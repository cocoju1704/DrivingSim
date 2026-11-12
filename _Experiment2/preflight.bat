@echo off
setlocal
rem Windows' own folders first: on the experiment PC the system PATH has lost System32 (chcp, ping,
rem timeout, powershell not found)
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\WindowsPowerShell\v1.0;%PATH%"
rem Before a block: CARLA, the wheel, the video server and the glasses app, Glasses 2, the SAGAT
rem tablet (preflight.py). Uses the start window's last settings. Run it while the start window is
rem open (not while a block runs: SAGAT is then checked by the block itself).
title Scenario ABC - preflight check
chcp 65001 >nul
set "PY=%~dp0..\venv_carla\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0preflight.py" %*
echo.
pause
