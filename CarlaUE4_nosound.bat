@echo off
rem Starts the CARLA server without its own sound (the audio engine plays the car sounds)
rem in a small window: it shows in the taskbar while the server runs, and drawing its own
rem spectator view at this size costs little GPU time (the experiment's cameras render as usual).
rem Not CARLA's no-rendering mode: that would turn the cameras off too.
rem Town04, the experiment's map, right away. Epic quality (the default): -quality-level=Low
rem would give 30 instead of about 26 frames per second, but it renders no fog.
start "" "%~dp0CarlaUE4.exe" /Game/Carla/Maps/Town04 -nosound -windowed -ResX=400 -ResY=225 %*
