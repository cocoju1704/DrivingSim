# TORApp

Shows the takeover experiment's pre-alert and TOR on the **Meta Ray-Ban Display** glasses instead of the PC screen.

```
_Experiment/takeover_experiment.py ──UDP (Wi-Fi)──▶ TORApp (Galaxy S22) ──Bluetooth (Meta DAT SDK)──▶ Ray-Ban Display
       (PC)            ◀── answer/latency ──
```

| Folder | Contents |
|------|------|
| `android/` | Android app (Kotlin, Compose, Meta Wearables Device Access Toolkit 1.0.1 `mwdat-display`) |
| `pc/tor_glasses.py` | Sender on the PC. `takeover_experiment.py --glasses` uses it; you can also run it alone to test |

## What shows on the glasses

| Mode | Glasses display |
|------|------------|
| `AUTO` | Same as the screen's mode box: **green** "AUTONOMOUS - LOCKED" |
| `PRE_ALERT` | **Green** "AUTONOMOUS" + **orange** banner: **PRE-ALERT** / "<message> - takeover request in N s" / countdown bar |
| `TOR` | **Full screen in pure red (255,0,0)**: big white **TAKE / OVER**, countdown digits, countdown bar |
| `MANUAL` | **Blue** "MANUAL" (practice drive: "PRACTICE - MANUAL") |
| `OFF` | "Waiting for the simulator" (before the experiment starts or after it ends) |

The display is 600×600, right lens only, and additive (black is see-through). The SDK has no text or background colors (only PRIMARY/SECONDARY), so the phone draws the colored banners as bitmaps and sends them as images ([TorContent.kt](android/app/src/main/java/com/drivingsim/torapp/TorContent.kt)). Every view change is a full Bluetooth resend, so the countdown updates once per second.

## Alert sounds (glasses speakers)

The app plays the simulator's alert sounds ([AlertSounds.kt](android/app/src/main/java/com/drivingsim/torapp/AlertSounds.kt)): PRE-ALERT chime, TOR repeating beeps, takeover click. The glasses are the phone's Bluetooth audio device, so the sounds come from the glasses speakers.

- With `--glasses`, the PC's alert sounds turn off (`--pc-sound` plays them on both). The vehicle sounds (audio engine) stay on the PC.
- The app's **Alert sounds → Output** line shows where the sounds play. If it reads `phone speaker`, the glasses are not connected as a Bluetooth audio device.
- Volume is the phone's **media volume**.
- The app keeps playing silence so the Bluetooth audio link stays open (otherwise the start of a sound gets cut off). Bluetooth audio itself adds about 0.1–0.3 s of delay.

## 1. One-time setup

### Glasses / Meta AI app
1. Meta AI app **v272 or later**, glasses firmware **v125 or later**
2. Put the glasses on (required for the following steps)
3. Meta AI app → **Settings → App Info → tap App version 5 times** → turn **Developer Mode** on
4. Press the install button that appears there to install the Device Access Toolkit on the glasses (takes 5–10 s, keep the app open)

With Developer Mode on, you don't need to register the app in the Wearables Developer Center (`mwdat_application_id` / `mwdat_client_token` are `0`).

### Build the app (on any PC)
Android Studio is installed on the simulator PC. Rebuild and reinstall after any change in `TORApp/android` (also when the PC sends something new, such as the intervention `text`).

1. Install Android Studio (Narwhal 2025.1.1 or later, JDK 17, Android SDK 36)
2. **File → Open** → open the `TORApp/android` folder (Gradle sync downloads the SDK from Maven Central, no token needed)
3. Turn on USB debugging on the S22 → connect it → **Run ▶**

From the command line (phone connected with USB debugging on). Gradle needs JDK 17–21: Android Studio's own JDK is 25, which this Gradle version cannot run on, so use JetBrains Runtime 21:
```powershell
$env:JAVA_HOME = "$env:USERPROFILE\.jdks\jbr-21.0.11"
cd TORApp\android
.\gradlew.bat installDebug
```

## 2. Every experiment

1. Connect the **PC and the S22 to the same Wi-Fi** (school Wi-Fi often blocks device-to-device traffic, so a lab router or phone hotspot is recommended)
2. Open TORApp → allow the Bluetooth permission
3. **1. Connect to Meta AI** → approve in the Meta AI app (first time only)
4. **2. Start display** → wait for Display to read `STARTED` (the glasses show "Waiting for the simulator")
5. Write down the IP shown under **3. Simulator PC** (e.g. `192.168.0.23 : 5007`)
6. On the PC:
   ```
   python _Experiment\takeover_experiment.py --glasses 192.168.0.23
   ```
   With `--glasses`, the PRE-ALERT/TOR banners are not drawn on the screen (the AUTONOMOUS/MANUAL status box and the sounds stay).

Keep the app in the foreground during the experiment. The app keeps the screen on and holds a low-latency Wi-Fi lock.

### Connection test without the simulator
```
python TORApp\pc\tor_glasses.py 192.168.0.23 --demo        # AUTO→PRE_ALERT→TOR→MANUAL repeated
python TORApp\pc\tor_glasses.py 192.168.0.23 --mode TOR    # hold one mode
```
You can also check the glasses without the PC using the **Test** buttons at the bottom of the app.

The PC log shows how long each state change took to reach the glasses:
```
INFO: Glasses: TOR shown 180 ms after it was sent
```
This is the time from the PC sending until the app reports it sent to the glasses (PC→phone→glasses send done→PC). It does not include the time the glasses take to actually light the screen. When the program exits, the median and maximum are printed too.

## Protocol (UDP 5007)

PC → phone (resent every 0.2 s, and right away on a change):
```json
{"v": 1, "seq": 12, "mode": "TOR", "message": "Highway exit ahead", "remaining": 3.4, "total": 5.0}
```
phone → PC (an answer to every packet, plus one right after a new state is on the glasses):
```json
{"seq": 12, "shown": 12, "display": "STARTED"}
```

## Things to check first on the hardware

- **Display sleep**: the glasses display dims after 20 s without input and sleeps at 25 s. The app's **Keep display awake** option resends the current view every 15 s. It is not yet confirmed that this actually prevents sleep, or that a new view wakes a sleeping display. Leave it in AUTO for more than 30 s and then run `--mode TOR` to check.
- **Two-finger tap on the temple (Back)** ends the display session. If participants touch the glasses during the experiment, press **Start display** again.
- When a phone call or notification arrives, the system can take over the display.

## References
- [Display access overview](https://wearables.developer.meta.com/docs/develop/dat/display-overview)
- [Android Display integration](https://wearables.developer.meta.com/docs/develop/dat/display-android)
- [meta-wearables-dat-android (DisplayAccess sample)](https://github.com/facebook/meta-wearables-dat-android/tree/main/samples/DisplayAccess)
