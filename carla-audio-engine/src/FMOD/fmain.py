# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

"""
FMOD Integration Main Entry Point

This module orchestrates the FMOD audio system by initializing the global 
EventBus, loading sound banks, and connecting simulation adapters to their 
respective sound engines. It manages the high-level execution loop for 
audio parameter updates.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from src.FMOD.utils import *
from src.FMOD.Adapters import *
from src.FMOD.Banks import *
from src.FMOD.Model.SoundModel import *
from src.FMOD.Sounds.EVSoundEngine import *
from src.FMOD.Sounds.EVSampleEngine import EVSampleEngine
from src.FMOD.Sounds.ReverseBeep import *

import sys

#: Rain/wind ambience loops. Off: Town04's default wind (30) kept a whooshing wind loop playing all the time.
ENVIRONMENT_SOUNDS = False

def main():
    """
    Bootstraps the audio engine components and enters the main update loop.
    
    The initialization sequence follows these steps:

        1. Initialize the global :class:`EventBus` for inter-module communication.
        2. Load environmental and trigger-based :class:`Banks`.
        3. Instantiate sound engines (EV and Reverse Beep).
        4. Bind :class:`Adapters` to bridge the EventBus and Sound Engines.
        5. Execute a continuous tick loop at approximately 20Hz (0.05s interval).
    """
    bus = EventBus()

    if ENVIRONMENT_SOUNDS:
        env_bank = EnvironmentBank()
        env_adapter = EnvironmentAdapter(bus, env_bank)
    trigger_bank = TriggerBank()
    # example_bank = ExampleBank()

    # Recorded loops from the Sounds folder (plus the synthesized motor if EVSampleEngine.SYNTH_MOTOR)
    ev = EVSampleEngine()
    layers = {"motor": ev.motor_sound, "road": ev.road_sound, "cabin": ev.cabin_sound, "synth motor": ev.synth}
    print("EV sound layers: " + (", ".join(name for name, layer in layers.items() if layer is not None) or "none"))
    rev_beep = ReverseBeep()

    engine_adapter = EngineAdapter(bus, ev)
    trigger_adapter = TriggerAdapter(bus, rev_beep, trigger_bank)

    model = SoundModel(bus)

    while True:
        model.on_tick()
        trigger_adapter.on_tick()

        time.sleep(0.05)


if __name__ == '__main__':
    main()
    
