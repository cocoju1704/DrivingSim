# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

import os
import time
from pathlib import Path
from .config import *


os.environ["PYFMODEX_DLL_PATH"] = FMOD_CORE_DLL
os.environ["PYFMODEX_STUDIO_DLL_PATH"] = FMOD_STUDIO_DLL

import pyfmodex
from pyfmodex.studio import StudioSystem 
from pyfmodex.studio.enums import PLAYBACK_STATE
from pyfmodex.exceptions import FmodError


class TriggerBank:
    """
    Interface for discrete, one-shot audio assets within FMOD Studio.

    This class manages the loading and playback of trigger-based sound events, 
    such as collisions, horns, and warnings. It maintains specific event 
    instances and provides public methods to initiate playback, which are 
    typically invoked by the :class:`TriggerAdapter`.

    Attributes:
        warning_sound (EventInstance): Instance for the overspeed warning audio.
        crash_sound (EventInstance): Instance for the vehicle collision audio.
        honk_sound (EventInstance): Instance for the vehicle horn audio.
        handBrake_sound (EventInstance): Instance for the handbrake engagement audio.
    """
    DEFAULT_BANK_PATH = TRIGGER_BANK_PATH
    """DEFAULT_BANK_PATH (str): Default directory for trigger .bank files, defined in the system configuration."""
    def __init__(self):
        """
        Initializes the FMOD system and prepares one-shot event instances.
        """
        self.warning_sound = None
        self.crash_sound = None
        self.honk_sound = None
        self.handBrake_sound = None
        self.__init_studio_system()
        self.__init_events()

    def __init_studio_system(self):
        """
        Initializes the FMOD Studio API and bootstraps core drivers.
        """
        core_system = pyfmodex.System()
        core_system.init()
        core_system.release()
        self.studio_system = StudioSystem()
        self.studio_system.initialize(max_channels=512)

    def __init_events(self, bank_path=DEFAULT_BANK_PATH):
        """
        Orchestrates the loading of banks and the preparation of event instances.

        Args:
            bank_path (str, optional): The path to the bank directory. 
                Defaults to TRIGGER_BANK_PATH.
        """
        self._load(bank_path)
        self._prepare_events()

    def _load(self, bank_path=DEFAULT_BANK_PATH):
        """
        Loads the Master and Trigger-specific bank files into memory.

        Args:
            bank_path (str): Normalized path to the bank directory.

        Raises:
            FileNotFoundError: If the specified directory cannot be located.
        """
        if bank_path is None:
            bank_path = self.DEFAULT_BANK_PATH
        bank_path = os.path.normpath(bank_path)
        print(f"[{self.__class__.__name__}] Resolved bank path: {bank_path}")

        if not os.path.isdir(bank_path):
            raise FileNotFoundError(f"Bank directory not found: {bank_path}")

        expected_files = [
            "Master.bank",
            "Master.strings.bank",
            "Trigger_Bank.bank",
            "Trigger_Bank.strings.bank",
        ]

        for f in expected_files:
            full_path = os.path.join(bank_path, f)
            if not os.path.exists(full_path):
                print(f"[{self.__class__.__name__}] Expected bank file missing: {full_path}")
            else:
                self.studio_system.load_bank_file(full_path)

    def _prepare_events(self):
        """
        Maps FMOD project paths to local event instances for playback control.
        """
        temp_warning_event = self.studio_system.get_event(WARNING_EVENT_PATH)
        temp_crash_event = self.studio_system.get_event(CRASH_EVENT_PATH)
        temp_honk_event = self.studio_system.get_event(HONK_EVENT_PATH)
        temp_handBranke_event = self.studio_system.get_event(HANDBRAKE_EVENT_PATH)
        self.warning_sound = temp_warning_event.create_instance()
        self.crash_sound = temp_crash_event.create_instance()
        self.honk_sound = temp_honk_event.create_instance()
        self.handBrake_sound = temp_handBranke_event.create_instance()
    
    def play_honk(self):
        self.honk_sound.start()
    
    def play_crash(self):
        self.crash_sound.start()
    
    def play_warning(self):
        self.warning_sound.start()

    def play_handBrake(self):
        self.handBrake_sound.start()

    def update_studio_system(self):
        self.studio_system.update()

    def get_events():
        """
        Returns a dictionary of event instances.
        """
        events = {

        }
        return events

    def shutdown(self):
        """
        Releases the FMOD Studio System and stops all active sounds.
        """
        try:
            print(f'Releasing Studio System')
            self.studio_system.release()
        except AttributeError as e:
            e.add_note(f"Fehlerquelle: Die Instanz existiert nicht mehr")
            print(f"Fehler abgefangen {e}")
        else: 
            print(f"Fahre herunter")

