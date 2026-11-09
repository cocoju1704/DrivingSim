@echo off
rem Scenario ABC (glasses / phone / HUD, SAGAT): the start window. Pick the participant and the
rem block, Start runs abc_experiment.py in this console; when the run ends the window comes back
rem with the next block. Close it (or 종료) to quit. See launcher.py and README.md.
title Scenario ABC experiment
set "PY=%~dp0..\venv_carla\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0launcher.py"
if errorlevel 1 pause
