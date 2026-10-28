@echo off
rem The experiment with a start window: pick the scenario, intervention, glasses, NDRT chat and the
rem other options, then Start runs takeover_experiment.py in this console. When the run ends the
rem window comes back for the next one; close it (or Exit) to quit. See launcher.py.
title TOR experiment
set "PY=%~dp0..\venv_carla\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0launcher.py"
if errorlevel 1 pause
