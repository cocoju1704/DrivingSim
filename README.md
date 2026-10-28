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
| [_Experiment/NDRT_scripts/](_Experiment/NDRT_scripts/) | Intervention texts, `scenario<N>_<driving\|NDRT>_<summary\|question>.txt` (3 × 2 × 2 = 12), plus `scenario<N>-b_...` where variant b needs its own text |
| [_Experiment/analyze_takeover.py](_Experiment/analyze_takeover.py) | Recompute metrics and figures from the logs |
| [carla-audio-engine/](carla-audio-engine/) | Vehicle sounds (FMOD). The experiment starts it automatically |
| [TORApp/](TORApp/) | Shows alerts on the Meta Ray-Ban Display glasses (Android app + PC sender) |
| [requirements.txt](requirements.txt) | Python packages |
| `_Experiment/Data/` | Experiment data, one folder per run (in git, without the glasses videos) |

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
.\venv_carla\Scripts\python.exe _Experiment\takeover_experiment.py --scenario 2-b --vehicles 15 --input wheel

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

**Scenarios** (`--scenario N-V`: number and variant, e.g. `2-b`; a number alone is variant a). The car drives autonomously in lane 3 (2-b and 3-b: lane 2; `--lane`, 1 = next to the median). The pre-alert starts automatically as the car approaches the event point, 60 s (`--pre-alert`) before the TOR, and the TOR comes 5 s (`--tor-lead`) before the event point:

| N-V | Scenario | Event point |
|---|---------|-----------|
| 0 | Practice: starts in the town, the driver finds the way to the highway by hand (navigation map at the top right), one lap by hand, then autonomous driving; P gives a takeover to practise. No logging | none |
| 1-a | Highway exit (exit lane: lane 4; signs EXIT 1 km, 500 m, at the exit) | The exit point (end of the overpass, `--exit-at`). Pre-alert 65 s before, ~1.4 km at 80 km/h. The exit point is 874 m from the start, closer than that, so the first pre-alert comes on the second lap |
| 1-b | Highway exit on the opposite carriageway: the loop driven the other way round from the same start, leaving at that side's exit ramp (still on the car's right: Town04 has no exits next to the median) | The exit ramp 908 m from the start (`REVERSE_EXIT_AT`); first pre-alert on the second lap, as in 1-a |
| 2-a | Work zone (after the first lap, lanes 3 and 4 close: the car's own lane; one ROAD WORK sign 200 m before, an arrow board where the lanes start to close) | Where the cones reach lane 3 (`--workzone-at`) |
| 2-b | Work zone mirrored: lanes 1 and 2 close, the car drives in lane 2, the arrow board points right | Where the cones reach lane 2 |
| 3-a | Accident (crashed cars, police car, ambulance, cones close lanes 3 and 4 on the second pass; one caution sign 200 m before, an arrow board) | Where the cones reach lane 3 (`--accident-at`) |
| 3-b | Accident mirrored: lanes 1 and 2 close, the car drives in lane 2 | Where the cones reach lane 2 |

Scenarios 2 and 3: after the takeover a car drives in lane 1 level with the car, and past the closure a broken-down van (hazard lights, warning triangle) stands in lane 2 (250 m past the work zone, 350 m past the accident): with lane 1 taken, the driver has to move over to lane 3. Variant b mirrored: the car in lane 4, the van in lane 3, the driver moves over to lane 2. The signs stay on the right shoulder in both. Autonomous driving comes back by itself 10 s after the takeover (scenarios 2 and 3: 10 s after passing the van; `--no-reengage`: off). The NDRT chat (`kakao_sets/scenario<N>.json`) is the same for both variants.

The fog scenario of earlier versions (then scenario 3; the accident was 4) is in [_Experiment/legacy/fog_scenario/](_Experiment/legacy/fog_scenario/).

The signs ([_Experiment/road_signs.py](_Experiment/road_signs.py)) are drawn with CARLA debug lines (CARLA has no sign props with text): they glow a little and disappear a few seconds after the program stops.

After the pre-alert the traffic leaves: cars ahead speed up to 60 km/h above the car's speed, cars behind slow down as much (over 10 s), and each is removed 250 m away; the rest are removed 10 s before the TOR, so the takeover happens on an empty road. The traffic stays gone for the rest of the run.

**Intervention** during the pre-alert (glasses only, `--glasses`). Set in [_Experiment/intervention_config.json](_Experiment/intervention_config.json):

```json
{
    "intervention": "driving",
    "format": "summary",
    "delay_seconds": 5.0,
    "question_seconds": 10.0
}
```

| Key | Values |
|-----|--------|
| `intervention` | `none` (control: pre-alert only), `driving` (driving situation, Endsley SA levels 1-3), `NDRT` (ready-to-resume) |
| `format` | `summary` (statements, read only), `question` (questions); both show one line at a time, each for `question_seconds` |
| `delay_seconds` | from the pre-alert to the text |
| `intro_seconds` | NDRT only: a first line on what the participant was doing ("김민수님께서 마케팅팀 톡방에 공지를 작성 중이셨습니다."), this long (default 5) |

Timeline with the defaults (glasses and screen alike): 0–5 s pre-alert banner "곧 자율주행 구간이 끝납니다" → 5–15 s SA level 1 → 15–25 s level 2 → 25–35 s level 3 → pre-alert banner again → 60 s TOR, "지금 직접 운전하세요" blinking (no countdown). NDRT: 5–10 s the intro line, then the three ready-to-resume lines 10–40 s. The pre-alert banner shows whenever no text does (auditory modality: all along); no time left is ever shown. From the TOR on, the NDRT chat page shows the RtR summary folded above the notice editor.

The text is `_Experiment/NDRT_scripts/scenario<N>_<intervention>_<format>.txt` for the `--scenario` that runs (`scenario<N>-b_...` instead for variant b if there is one, e.g. 2-b's driving summary names lanes 1 and 2): one line per displayed line (`Label: sentence`, the label is drawn bold), `#` starts a comment line. With `NDRT` + `summary` the glasses show the participant's own ready-to-resume summary of their notice draft instead (ChatGPT, from kakao_ndrt.py); the file is the fallback if none has arrived. The intervention name is logged in the `intervention` column of raw.csv and summary.csv.

## Results

Each run creates `_Experiment\Data\YYMMDD_HHMMSS\`:
- `driving\raw.csv`: one row per frame from the pre-alert on, plus a TRIAL_END row per trial
- `driving\summary.csv`: per-trial metrics (TOT, TOR→takeover, MAlat/MAlon, SDLP, lane changes, minTTC, collisions)
- `driving\figure.png`: speed, acceleration, lane offset, and driver input per trial
- `ndrt\`: the NDRT chat (`ndrt.jsonl`) and the RtR summaries (`rtr.jsonl`, `rtr_experiment.jsonl`)
- `video\`: the glasses recording with `--record` (not in git: too large)

To recompute:
```powershell
.\venv_carla\Scripts\python.exe _Experiment\analyze_takeover.py                     # newest run
.\venv_carla\Scripts\python.exe _Experiment\analyze_takeover.py --all               # every run
```
The metrics follow Bai et al. (2024), *Human Factors* 66(12).

## Meta Ray-Ban Display glasses

The PC sends the takeover state over UDP to the TORApp app on the phone (Wi-Fi or USB tethering), and the phone puts it on the glasses over Bluetooth. With `--glasses`, the PRE-ALERT/TOR banners are not drawn on the screen and appear only on the glasses. For app installation, glasses setup, and testing, see [TORApp/README.md](TORApp/README.md).
