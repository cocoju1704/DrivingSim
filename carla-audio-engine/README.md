# Sound Implementation for CARLA

This repository contains the implementation of basic sound functionaliy 
for the CARLA simulator. The project was developed as part of an academic assignment, at the University of Technology Nuremberg - Georg Simon Ohm, and aims 
to enhance the realism of the simulation environment.

CARLA, widely used in research for autonomous driving and user experience (UX) 
design in automotive contexts, lacks built-in support for sound. Our contribution 
introduces a simple sound system for CARLA, intended to serve as a foundation for 
others who wish to implement basic sound effects. While not designed for full-fledged 
game audio, this code can be used as:

- A reference template to enable basic sounds for more immersive simulations.
- A starting point for understanding how sound integration in CARLA can be realized.

We hope this implementation will be helpful for researchers, students, and developers exploring the
integration of audio in the CARLA simulator.


## Implemented Sounds
This implementation introduces several basic sounds to enhance
the realism of CARLA´s simulation environment.
The following sounds are implemented:

- __Ambient Sounds__: Simulates environmental sounds such as wind and rain.
- __Crash Sounds__: Plays a sound to simulate collisions between vehicles and objects.
- __Speed Limit Alert__: Triggers a sound when exceeding 100 km/h.
- __Reverse Gear Alert__: Plays a sound upon switching to reverse gears.
- __Handbrake Sound__: Features the tire squealing when the handbreak is applied.
- __EV Sound__: Simulates the characteristic audio of an Electrical-Car for operations.

>[!NOTE]
>All sounds included in this repository are improvised and gathered from online sources.
They were not professionally designed and may vary in quality. This implementation is primarily intended 
as a proof of concept or starting point for further development.

>[!CAUTION]
>The sounds are created or edited with FMOD Studio 2.02 and Engine 2.02.
>To use FMOD commercially, please contact the FMOD Licensing department.

## How to run
```mermaid
flowchart TD
  A[Download all dependencies] --> B[Checkout Code into IDE]
  B --> C[Create CARLA Client Venv]
  C --> D[Create CARLA Code Venv]
  D --> E[Create FMOD Code Venv]
  E --> F[Run RunOhmUXSim.py]
  F --> G[Select Files]
  G --> H[Start]
```

## Installation and Setup

>[!TIP]
>Everything you need to know about what has to be installed and
> how to set up the project that every thing runs right is explained in
> this video: https://www.youtube.com/watch?v=hypM038aNzE  

>[!NOTE]  
> Video is in German so you might have to use subtitles.

First, you need to install FMOD Studio 2.02 and Engine 2.02, CARLA version 0.9.15, and Python 3.8 and 3.12.
Use the following links to download the necessary files:

### Dependencies
|Component|Version|
|---|---|
|[FMOD-STUDIO](https://www.fmod.com/download#fmodstudio)|2.02|
|[FMOD-ENGINE](https://www.fmod.com/download#fmodengine)|2.02|
|[CARLA](https://github.com/carla-simulator/carla/releases/tag/0.9.15/)|0.9.15|
|[PYTHON](https://www.python.org/downloads/windows/)|3.8 and 3.12|

After the installations are complete you can _clone_ the repository into your own IDE. 
Now you have to creat three different venvs for the project.

### 1. CARLA Client Venv
For the CARLA Client Venv you have to go into the CARLA folder where the _Carla4UE.exe_ lies and start 
there a terminal or you directly navigate to the folder via the terminal.

After that you have to naviagte into the _PythonAPI_ and then into the _examples_ folder.
````Console
C:\Users\user\yourFolderWhereCarlaIs\WindowsNoEditor> cd PythonAPI\examples
````

Here you have to creata a venv with __Pyhton 3.8__.
````Console
C:\Users\user\yourFolderWhereCarlaIs\WindowsNoEditor\PythonAPI\examples> py -3.8 venv .venv38
````

After the venv is created you have to activate it. 
````Console
C:\Users\user\yourFolderWhereCarlaIs\WindowsNoEditor\PythonAPI\examples> .\.venv38\Scripts\activate
````

In the active venv you have to install a _requirements.txt_.
````Console
(.venv38) C:\Users\user\yourFolderWhereCarlaIs\WindowsNoEditor\PythonAPI\examples> pip install -r requirements.txt
````

This will take a while until all packages are installed. After that you have to install manualy carla in the venv.
````Console
(.venv38) C:\Users\user\yourFolderWhereCarlaIs\WindowsNoEditor\PythonAPI\examples> pip install carla
````

After that you can check with the command `pip list` if everything is installed correctly. And you can `deactivate` the venv.


>[!IMPORTANT]
> The next two venvs have to be created in the src folder. So you have to clone the project into your IDE if not already done.
### 2. CARLA Code Venv:
This venv has to be created in the _CARLA_ folder of our project. This part of the code connects with CARLA 
and sends/receives data from the simulator.  
To create this venv you have to open a terminal in your IDE and direct to the CARLA folder.
````Console
C:\Users\user\yourProjectFolder> cd src\CARLA
````

Here you must now create a venv with __Python 3.8__, as for the CARLA simulator.
````Console
C:\Users\user\yourProjectFolder\src\CARLA> py -3.8 -m venv .venv38
````

And as with the venv for the simulator we have to activate it and install the _requirements.txt_.
````Console
C:\Users\user\yourProjectFolder\src\CARLA> .\.venv38\Scripts\activate
````
````Console
(.venv38) C:\Users\user\yourProjectFolder\src\CARLA> pip install -r requirements.txt
````


After the installation is complete you can `deactivate` the venv.

### 3. FMOD Code Venv:
This venv has to be created in the _FMOD_ folder of our project. This part of the code is responisble
for playing the sounds in the right events.  
To creat it you have to follow the same steps a befor:
- direct to the right folder
````Console
C:\Users\user\yourProjectFolder> cd src\FMOD 
````
- create the venv with __Python 3.12__
````Console
C:\Users\user\yourProjectFolder\src\FMOD> py -3.12 -m venv .venv
````
- activate it
````Console
C:\Users\user\yourProjectFolder\src\FMOD> .\.venv38\Scripts\activate
````
- install the requirements.txt
````Console
(.venv38) C:\Users\user\yourProjectFolder\src\FMOD> pip install -r requirements.txt
````
- `deactivate` it

### Launcher
After all venvs are created you can launch the project by running the `RunOhmUXSim.py` file.
Starting the script opens a launcher.

![Launcher](docs/source/diagrams/View_Launcher.png)

In the launcher you have to select the files for:
1. the CARLA client.
2. the venvs: here you have to select the python.exe files.
3. and the scripts for control, traffic generation and our scripts for the CARLA and FMOD code.

>[!TIP]
>The image provides example paths that should be similar to yours.

>[!NOTE]
>The field `Use DircetX 11 (-dx11)` has to be selected if your GPU isn´t from NVIDIA or has less then 8GB VRam.


## Architecture and Structure
The system is divided into two parts—CARLA and FMOD. The CARLA part essentially handles the setup of 
and communication with the CARLA simulator. The FMOD part handles audi playback.

### 1. CARLA
The __CARLA part__ is responsible for connecting to the CARLA simulator and providing the __simulation data__ that is later used by the 
FMOD subsystem for audio playback. Technically, it consists of a lightweight client that connects to the running CARLA server,
locates/monitors the "hero" vehicle reads relevant state information, and __periodically sends it via UDP as JSON__ to a local receiver.

#### Folder Structure
- `cmain.py`  
  Entry point for the CARLA client. Starts the data loop (polling simulation values) and sends data packets at a fixed interval.
  It also launches a small weather UI to adjust weather parameters during runtime.
- `Classes/`  
  Contains the core calsses for connecting, sensing, data transport, and UI:
  - `__init__.py`
  Exposes the main classes as package imports.
  - `CarlaClient.py`
  Encapsulates the CARLA server connection, retrieves the `world`, searches for a vehicle, and continuously reads vehicle and environment data.
  It also attaches a collision sensor and produces a compact data packet (relevant for the audio logic).
  - `CollisionSensor.py`
  Implements a CARLA collision sensor that counts collisions and measures their intensity, used to trigger crash events.
  - `Socket.py`
  Minimal UDP wrapper for sending JSON data (locally to 127.0.0.1 on a fixed port)
  - `Weather.py`
  Small Tkinter GUI used to set rain and wind intensity in the running simulation.
- `generate_traffic.py`
Script to generate traffic in the simulator.
- `requirements.txt`
Python dependencies that are required for the CARLA client (will be installed into a venv).

#### Data flow
1. `cmain.py` starts the client and the sender loop.
2. `CarlaClient` connects to the simulator, finds the hero vehicle, and attaches a `CollisionSensor`.
3. At short intervals, it reads relevant states (vehicle motion, vehicle control, speed, speed limit, wheather, events like collisions/honk)
4. `Socket` serializes the values as JSON and sends them via UDP to the local receiver (FMOD subsystem).

__Goal of this module:__
Provide a robust and easily extensible interface between the CARLA simulation and the sound system, without embedding audio logic directly inside the CARLA side.

### 2. FMOD
The __FMOD part__ handles the actual __audio logic and audio playback__. It receives data packets sent by the CARLA client (UDP/JSON),
detects changes (diffing), and translates these changes into __FMOD event triggers__, __parameter updates__, or __procedurally generated sounds__. The structure is loosely
based on an __MVC-style__ split: _Model_ (data receiving/processing), _Adapters_ (logic), and _Banks/Sounds_ (audio resources and playback).

#### Folder Structure
- `fmain.py`
Entry point of the FMOD subsystem. Initializes:
  - the central `EventBus` (publisher-subscriber),
  - FMOD `Banks` (loading/initializing FMOD Studio events) and live-created sounds,
  - `Adapters` (audio logic reacting to data changes),
  - and the `SoundModel` (UDP receive & diffing).  
  Then it runs a loop that regularly processes new data and ticks trigger/one-shot logic.
- `Model/`
  - `SoundModel.py`
  __Receives__ CARLA data via UDP, __decodes__ the JSON, and computes the __difference__ to the previous state. Only changed values are
  published via the `EventBus`. This reduces unnecessary sound updates and cleanly separates data handling from audio logic.
- `utils/`
  - `EventBus.py`
  Lightweight event bus enabling loose coupling between publishers (model) and subscribers (adapters).
  - `DataKey.py`
  Central definition of all data keys (Enum). Ensures consistent keys, avoids typos, and supports easy extension.
  - `RangeLevel.py`
  Utility for mapping continuous values (e.g., intensities) to discrete levels.
- `Adapters/` (controller/adaper layer)
Components that __subscribe__ to specific `DataKeys` and translate changes into audio actions.
  - `EnvironmentAdapter.py`
  Updates environment parameters (e.g., rain/wind) as FMOD parameters on continuously running events. Includes mapping from continuous intensities to levels (`RainIntensity`/`WindIntensity`).
  - `EngineAdapter.py`
  Handles engine/vehicle sounds. Instead of relying only on FMOD Studio events, it controls a procedural EV sound generator (parameters: speed/throttle → estimated “torque”).
  - `TriggerAdapter.py`
  Handles one-shot/trigger sounds such as crash, honk, handbrake, and reverse warning. Contains simple gating/state logic to prevent double-triggering in noisy input scenarios.
  - `RainIntensity.py`/`WindIntensity.py`
  Define intensity ranges as discrete levels (NONE/LOW/MEDIUM/HIGH) that are mapped to parameter values.
- `Banks/` (FMOD Studio interface)
Encapsulates __loading FMOD bank files__, creating event instances, and calling `studio_system.update()`:
  - `EnvironmentBank.py`
  Initializes FMOD Studio, loads the relevant bank, and provides instances for rain/wind (including parameter control).
  - `TriggerBank.py`
  Loads the trigger bank and exposes methods like `play_*()` for warning/crash/honk/handbrake.
  - `ExampleBank.py`
  Example class for Bank classes.
- `Sounds/` (procedural audio)
  - `EVSound.py`
  Generates EV/vehicle sounds procedurally using DSP oscillators, filters, and parameterized volume/frequency control based on speed and load.
  -`ReverseBeep.py`
  Procedurally generated reverse beep (short tone/pattern) as an alternative or supplement to FMOD Studio events.
- `requirements.txt`
Python dependencies that are required for the CARLA client (will be installed into a venv).

#### Data Flow
1. __`fmain.py` boots the FMOD subsystem__  
It creates the central `EventBus`, initializes the required FMOD components (`Banks` and procedural `Sounds`), instantiates the `Adapters` that subscribe to data changes, and finally starts the `SoundModel` (UDP receiver).
2. __`SoundModel` receives CARLA data via UDP__  
The model listens on a local UDP socket, decodes incoming JSON packets, and keeps the previous packet as a reference state.
3. __Diffing: only changes are published__  
For each new packet, the model computes a diff against the last state. Only changed values are published on the `EventBus`.
4. __Adapters react to published updates__
  - __Continuous values__ (e.g., speed, throttle, rain/wind intensity) are translated into parameter updates (FMOD parameters or DSP/procedural sound parameters).
  - __Trigger-like values__ (e.g., collision, honk, reverse gear, handbrake) are handled with gating/state logic to avoid duplicate triggers and then played as one-shot sounds.
5. __FMOD engine is kept alive via regular updates__  
Within the main loop in `fmain.py`, the system processes model updates (publishing changes) and ticks adapter/bank update functions so FMOD event playback and procedural audio remain responsive and in sync.


## Third-Party Licenses

Made using FMOD Studio by Firelight Technologies Pty Ltd.
Additionally this project uses [CARLA Simulator](https://github.com/carla-simulator/carla) and [PYFMODEX](https://github.com/tyrylu/pyfmodex) under the [MIT License](https://opensource.org/licenses/MIT).

Please ensure you comply with the MIT license terms when using or modifying this project.
