# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

"""
FMOD Project Configuration

This module defines the filesystem paths and event strings required to link 
the Python engine with FMOD Studio assets. It dynamically resolves the 
project root to ensure cross-platform compatibility and defines the 
URI-style paths for specific FMOD events.
"""

import os
from pathlib import Path

# --- Path Resolution ---
FILE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FILE_DIR.parents[2]
BANKS_DIR = PROJECT_ROOT / "Banks"
SOUNDS_DIR = PROJECT_ROOT / "Sounds"

#: FMOD Engine install folder (contains "api"); override with the FMOD_API_DIR environment variable
FMOD_API_DIR = Path(os.environ.get("FMOD_API_DIR", r"C:\Program Files (x86)\FMOD SoundSystem\FMOD Studio API Windows"))

#: Absolute path to FMOD Core dll
FMOD_CORE_DLL = str(FMOD_API_DIR / "api" / "core" / "lib" / "x64" / "fmod.dll")

#: Absolute path to FMOD Studio dll
FMOD_STUDIO_DLL = str(FMOD_API_DIR / "api" / "studio" / "lib" / "x64" / "fmodstudio.dll")

#: Absolute path to the Trigger sound banks directory.
TRIGGER_BANK_PATH = str((BANKS_DIR / "Trigger_Bank").resolve())

#: Absolute path to the Environment sound banks directory.
ENVIRONMENT_BANK_PATH = str((BANKS_DIR / "Environment_Bank").resolve())

# --- Environment Bank events ---
#: FMOD Studio path for the ambient rain loop.
RAIN_EVENT_PATH = "event:/Rain"

#: FMOD Studio path for the ambient wind loop.
WIND_EVENT_PATH = "event:/Wind"

# --- Trigger Bank events ---
#: FMOD Studio path for the overspeed warning signal.
WARNING_EVENT_PATH = "event:/Warning"

#: FMOD Studio path for the vehicle collision impact.
CRASH_EVENT_PATH = "event:/Crash"

#: FMOD Studio path for the vehicle horn.
HONK_EVENT_PATH = "event:/Honk"

#: FMOD Studio path for the handbrake engagement sound.
HANDBRAKE_EVENT_PATH = "event:/HandBrake"