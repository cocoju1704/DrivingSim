@echo off
rem Starts the CARLA server without its own sound (the audio engine plays the car sounds).
start "" "%~dp0CarlaUE4.exe" -nosound %*
