@echo off
rem Starts the CARLA server without its own sound (the audio engine plays the car sounds)
rem and without its window (-RenderOffScreen): the experiment's cameras still render, the
rem server just does not draw its own spectator view, which saves GPU time.
rem Not CARLA's no-rendering mode: that would turn the cameras off too.
start "" "%~dp0CarlaUE4.exe" -nosound -RenderOffScreen %*
