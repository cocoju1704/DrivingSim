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
| [_Experiment/takeover_experiment.py](_Experiment/takeover_experiment.py) | Experiment program (scenarios, autonomous driving, TOR, logging) |
| [_Experiment/CarlaUE4_nosound.bat](_Experiment/CarlaUE4_nosound.bat) | Starts the CARLA server (no sound, no window; shows in the taskbar while running) |
| [_Experiment/intervention_config.json](_Experiment/intervention_config.json) | Which intervention text the glasses show during the pre-alert |
| [_Experiment/NDRT_scripts/](_Experiment/NDRT_scripts/) | Intervention texts, `scenario<N>_<driving\|NDRT>_<summary\|question>.txt` (3 × 2 × 2 = 12) |
| [PythonAPI/examples/analyze_takeover.py](PythonAPI/examples/analyze_takeover.py) | Recompute metrics and figures from the logs |
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
.\_Experiment\CarlaUE4_nosound.bat
```
The server has no window, but a minimized **"CARLA server - running"** console stays in the taskbar while it runs.

**2. Experiment**
```powershell
# 3 monitors (2560x1440 x 3, default)
.\venv_carla\Scripts\python.exe _Experiment\takeover_experiment.py

# 1 monitor (side mirrors are drawn as insets at the lower left and right of the screen)
.\venv_carla\Scripts\python.exe _Experiment\takeover_experiment.py --screens 1 --res 1920x1080 --window-pos 0,0

# Scenario / traffic / input device
.\venv_carla\Scripts\python.exe _Experiment\takeover_experiment.py --scenario 2 --vehicles 15 --input wheel

# Alerts on the Meta Ray-Ban Display glasses (phone IP: shown in TORApp)
.\venv_carla\Scripts\python.exe _Experiment\takeover_experiment.py --glasses 10.139.72.126
```
For all options: `--help`. For wheel buttons: `--wheel-setup` (once). For axis numbers: `--wheel-test`.

| Key | Action |
|----|------|
| P | Start the takeover sequence (pre-alert → 60 s later TOR → 5 s later forced manual driving) |
| E | Re-engage autonomous driving (in manual driving) |
| W/A/S/D, arrows | Driving (keyboard) |
| Z / X, L, H | Turn signals, lights, horn |
| TAB | Change camera position |
| ESC | Quit (summary.csv and figure.png are written) |

**Scenarios** (`--scenario N`). The car drives autonomously in lane 3 (`--lane`, 1 = next to the median). The pre-alert starts automatically as the car approaches the event point, 60 s (`--pre-alert`) before the TOR:

| N | Scenario | TOR |
|---|---------|-----------|
| 0 | Practice (manual driving only, no logging) | none |
| 1 | Highway exit (exit lane: lane 4; signs EXIT 1 km, 500 m, at the exit) | 5 s before the exit point (pre-alert 65 s before, ~1.4 km at 80 km/h). The exit point is 874 m from the start, closer than that, so the first pre-alert comes on the second lap |
| 2 | Work zone (lanes 3 and 4 closed after the first lap: the car's own lane; signs ROAD WORK 1 km, 500 m, LANE 3 4 CLOSED 250 m before) | 15 s before the work zone (pre-alert 75 s before, ~1.7 km) |
| 3 | Sudden fog | 60 s after the fog density reaches the threshold (pre-alert) |

The signs ([_Experiment/road_signs.py](_Experiment/road_signs.py)) are drawn with CARLA debug lines (CARLA has no sign props with text): they glow a little and disappear a few seconds after the program stops.

After the pre-alert the traffic leaves: cars ahead speed up to 60 km/h above the car's speed, cars behind slow down as much (over 10 s), and each is removed 250 m away; the rest are removed 10 s before the TOR, so the takeover happens on an empty road. The traffic stays gone for the rest of the run.

**Intervention** during the pre-alert (glasses only, `--glasses`). Set in [_Experiment/intervention_config.json](_Experiment/intervention_config.json):

```json
{
    "intervention": "driving",
    "format": "summary",
    "delay_seconds": 5.0,
    "question_seconds": 15.0
}
```

| Key | Values |
|-----|--------|
| `intervention` | `none` (control: pre-alert only), `driving` (driving situation, Endsley SA levels 1-3), `NDRT` (ready-to-resume) |
| `format` | `summary` (all lines at once, read only), `question` (one question at a time, each `question_seconds`) |
| `delay_seconds` | from the pre-alert to the text |

Glasses timeline with the defaults: 0–5 s pre-alert only → 5–20 s SA level 1 / ready-to-resume step 1 → 20–35 s step 2 → 35–50 s step 3 → 50–60 s pre-alert only → 60 s TOR. `summary` shows all three lines for the same 5–50 s.

The text is `_Experiment/NDRT_scripts/scenario<N>_<intervention>_<format>.txt` for the `--scenario` that runs: one line per displayed line (`Label: sentence`, the label is drawn bold), `#` starts a comment line. While a text is shown, the glasses keep the countdown it had when the text appeared (55, 40, 25 s): each new view with the text takes 1–3 s to send over Bluetooth, so a per-second countdown would skip seconds and could delay the TOR. Without text (the first 5 s, the last 10 s) it counts every second. The intervention name is logged in the `intervention` column of raw.csv and summary.csv.

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
