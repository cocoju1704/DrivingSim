@echo off
rem Starts the CARLA server without its own sound (the audio engine plays the car sounds)
rem and without its window (-RenderOffScreen): the experiment's cameras still render, the
rem server just does not draw its own spectator view, which saves GPU time.
rem Not CARLA's no-rendering mode: that would turn the cameras off too.
rem
rem With no window of its own, a minimized console "CARLA server - running" stays in the
rem taskbar while the server runs and closes when it exits. If the server is already
rem running, only that console is opened.

setlocal
rem full paths: System32 is not on this PC's PATH
set "SYS=%SystemRoot%\System32"
if defined CARLA_SERVER_CONSOLE goto console
set CARLA_SERVER_CONSOLE=1
rem cmd /c: the console closes when this script ends (start on a .bat would keep it open)
start "CARLA server" /min "%SYS%\cmd.exe" /c ""%~f0" %*"
exit /b

:console
title CARLA server - starting
"%SYS%\tasklist.exe" /fi "imagename eq CarlaUE4-Win64-Shipping.exe" | "%SYS%\find.exe" /i "CarlaUE4" >nul
if errorlevel 1 (
    echo Starting CARLA: -nosound -RenderOffScreen %*
    start "" "%~dp0CarlaUE4.exe" -nosound -RenderOffScreen %*
) else (
    echo CARLA is already running.
)

set /a tries=0
:appear
"%SYS%\tasklist.exe" /fi "imagename eq CarlaUE4-Win64-Shipping.exe" | "%SYS%\find.exe" /i "CarlaUE4" >nul
if not errorlevel 1 goto running
set /a tries+=1
if %tries% geq 30 (
    echo CARLA did not start within 60 s.
    pause
    exit /b 1
)
"%SYS%\timeout.exe" /t 2 /nobreak >nul
goto appear

:running
title CARLA server - running
echo CARLA server is running. This window closes when it stops.
echo Closing this window does not stop CARLA (Task Manager: CarlaUE4-Win64-Shipping).
:wait
"%SYS%\timeout.exe" /t 5 /nobreak >nul
"%SYS%\tasklist.exe" /fi "imagename eq CarlaUE4-Win64-Shipping.exe" | "%SYS%\find.exe" /i "CarlaUE4" >nul
if not errorlevel 1 goto wait
