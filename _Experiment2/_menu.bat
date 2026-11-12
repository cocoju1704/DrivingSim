@echo off
rem Scenario ABC on the experiment PC: the menu window (menu.py), a button for each step run by hand
rem (the start window, the preflight check, the Glasses 2 fit, calibration and validation). Each step
rem opens a console of its own; the menu stays open.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%PATH%"
set "PYW=%~dp0..\venv_carla\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0menu.py"
