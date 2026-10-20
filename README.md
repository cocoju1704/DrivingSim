# DrivingSim: CARLA takeover (TOR) experiment

A takeover (TOR, Takeover Request) experiment environment built on CARLA 0.9.16 (Windows). An autonomous vehicle loops the Town04 figure-8 highway. When a scenario event approaches, the system issues a **PRE-ALERT → TOR**, and it records the driver's takeover behavior.

- Driver input: steering wheel + pedals (Logitech etc., with force feedback) or keyboard
- 3-monitor (default) or 1-monitor driving view, side and rear-view mirrors
- Vehicle sounds ([carla-audio-engine](carla-audio-engine/), FMOD) + alert sounds
- Alerts on the screen, or on the **Meta Ray-Ban Display glasses** ([TORApp](TORApp/))
- Per-trial logs (raw.csv) and takeover metrics (TOT, MAlat/MAlon, SDLP, ...)

## Folder layout

This repository holds only our own files inside the CARLA 0.9.16 folder. The CARLA release itself (CarlaUE4, PythonAPI/carla, ...) is not included.

| Path | Contents |
|------|------|
| [PythonAPI/examples/takeover_experiment.py](PythonAPI/examples/takeover_experiment.py) | Experiment program (scenarios, autonomous driving, TOR, logging) |
| [PythonAPI/examples/analyze_takeover.py](PythonAPI/examples/analyze_takeover.py) | Recompute metrics and figures from the logs |
| [CarlaUE4_nosound.bat](CarlaUE4_nosound.bat) | Starts the CARLA server (no sound, no window; shows in the taskbar while running) |
| [carla-audio-engine/](carla-audio-engine/) | Vehicle sounds (FMOD). The experiment starts it automatically |
| [TORApp/](TORApp/) | Shows alerts on the Meta Ray-Ban Display glasses (Android app + PC sender) |
| [requirements.txt](requirements.txt) | Python packages |
| `Data/` | Experiment logs (generated when you run, not in git) |

## Setup (new PC)

1. Download **CARLA 0.9.16** for Windows from [CARLA releases](https://github.com/carla-simulator/carla/releases) and extract it (e.g. `C:\_byungju\drivingsim\CARLA_0.9.16`)
2. In that folder, pull in this repository:
   ```powershell
   cd C:\_byungju\drivingsim\CARLA_0.9.16
   git init
   git remote add origin https://github.com/cocoju1704/DrivingSim.git
   git fetch origin
   git checkout -f -t origin/main
   ```
3. Create the Python 3.12 virtual environment `venv_carla`:
   ```powershell
   py -3.12 -m venv venv_carla
   .\venv_carla\Scripts\python.exe -m pip install -r requirements.txt
   ```
   You can also install carla from the bundled wheel: `PythonAPI\carla\dist\carla-0.9.16-cp312-cp312-win_amd64.whl`.
   The audio engine runs with this venv's python (it needs pyfmodex).

## Running

**1. CARLA server**
```powershell
.\CarlaUE4_nosound.bat
```
The server has no window, but a minimized **"CARLA server - running"** console stays in the taskbar while it runs.

**2. Experiment**
```powershell
# 3 monitors (2560x1440 x 3, default)
.\venv_carla\Scripts\python.exe PythonAPI\examples\takeover_experiment.py

# 1 monitor (side mirrors are drawn as insets at the lower left and right of the screen)
.\venv_carla\Scripts\python.exe PythonAPI\examples\takeover_experiment.py --screens 1 --res 1920x1080 --window-pos 0,0

# Scenario / traffic / input device
.\venv_carla\Scripts\python.exe PythonAPI\examples\takeover_experiment.py --scenario 2 --vehicles 15 --input wheel

# Alerts on the Meta Ray-Ban Display glasses (phone IP: shown in TORApp)
.\venv_carla\Scripts\python.exe PythonAPI\examples\takeover_experiment.py --glasses 10.139.72.126
```
For all options: `--help`. For wheel buttons: `--wheel-setup` (once). For axis numbers: `--wheel-test`.

| Key | Action |
|----|------|
| P | Start the takeover sequence (pre-alert → 5 s later TOR → 5 s later forced manual driving) |
| E | Re-engage autonomous driving (in manual driving) |
| W/A/S/D, arrows | Driving (keyboard) |
| Z / X, L, H | Turn signals, lights, horn |
| TAB | Change camera position |
| ESC | Quit (summary.csv and figure.png are written) |

**Scenarios** (`--scenario N`). The pre-alert starts automatically as the car approaches the event point:

| N | Scenario | Pre-alert |
|---|---------|-----------|
| 0 | Practice (manual driving only, no logging) | none |
| 1 | Highway exit | 10 s before the exit point |
| 2 | Work zone (lanes 3 and 4 closed after the first lap) | 20 s before the work zone |
| 3 | Sudden fog | when the fog density reaches the threshold |

## Results

Each run creates `Data\YYMMDD_HHMMSS\`:
- `raw.csv`: one row per frame from the pre-alert on, plus a TRIAL_END row per trial
- `summary.csv`: per-trial metrics (TOT, TOR→takeover, MAlat/MAlon, SDLP, lane changes, minTTC, collisions)
- `figure.png`: speed, acceleration, lane offset, and driver input per trial

To recompute:
```powershell
.\venv_carla\Scripts\python.exe PythonAPI\examples\analyze_takeover.py              # newest run
.\venv_carla\Scripts\python.exe PythonAPI\examples\analyze_takeover.py --all        # every run
```
The metrics follow Bai et al. (2024), *Human Factors* 66(12).

## Meta Ray-Ban Display glasses

The PC sends the takeover state over UDP to the TORApp app on the phone (Wi-Fi or USB tethering), and the phone puts it on the glasses over Bluetooth. With `--glasses`, the PRE-ALERT/TOR banners are not drawn on the screen and appear only on the glasses. For app installation, glasses setup, and testing, see [TORApp/README.md](TORApp/README.md).
