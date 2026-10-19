# Starts the CARLA audio engine next to a running CARLA server.
# Run CarlaUE4.exe and your driving script (ego vehicle role_name = 'hero') as usual, then:
#   powershell -ExecutionPolicy Bypass -File carla-audio-engine\run_audio.ps1   (from the CARLA_0.9.16 folder)
# If FMOD Engine is installed somewhere else, set $env:FMOD_API_DIR to the folder that contains "api".

$Python = Join-Path $PSScriptRoot "..\venv_carla\Scripts\python.exe"
$Src = Join-Path $PSScriptRoot "src"

# FMOD side: listens on UDP 127.0.0.1:5005 and plays the sounds
$fmod = Start-Process $Python -ArgumentList "fmain.py" -WorkingDirectory (Join-Path $Src "FMOD") -PassThru
# CARLA side: reads the hero vehicle state, sends it over UDP, opens the small weather window
$carla = Start-Process $Python -ArgumentList "cmain.py" -WorkingDirectory (Join-Path $Src "CARLA") -PassThru

Write-Host "Audio engine running (FMOD pid $($fmod.Id), CARLA pid $($carla.Id)). Press Enter to stop."
Read-Host | Out-Null
# /T also stops the real interpreter that the venv python.exe launcher starts as a child
taskkill /T /F /PID $fmod.Id /PID $carla.Id 2>$null | Out-Null
