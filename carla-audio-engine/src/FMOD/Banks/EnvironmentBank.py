# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

import os
import time
import logging
from .config import *

os.environ["PYFMODEX_DLL_PATH"] = FMOD_CORE_DLL
os.environ["PYFMODEX_STUDIO_DLL_PATH"] = FMOD_STUDIO_DLL

import pyfmodex
from pyfmodex.studio import StudioSystem 
from pyfmodex.studio.enums import PLAYBACK_STATE
from pyfmodex.exceptions import FmodError

class EnvironmentBank:
    """
    Interface for environmental audio assets and FMOD Studio banks.

    This class manages the lifecycle of environmental sound banks, including 
    loading the 'Master' and 'Environment' banks. It instantiates and maintains 
    persistent event instances for ambient sounds like rain and wind, allowing 
    them to be modulated in real-time by the :class:`EnvironmentAdapter`.

    Attributes:
        studio_system (StudioSystem): The active FMOD Studio playback engine.
        rain_inst (EventInstance): Persistent instance for the rain audio loop.
        wind_inst (EventInstance): Persistent instance for the wind audio loop.
    """
    DEFAULT_BANK_PATH = ENVIRONMENT_BANK_PATH
    """DEFAULT_BANK_PATH (str): The default filesystem directory containing the .bank files, sourced from the global configuration."""
    def __init__(self):
        """
        Initializes the FMOD system, loads the environment banks, and 
        immediately starts the ambient sound instances.
        """
        self.studio_system = None
        self.rain_inst = None
        self.wind_inst = None
        self.__init_studio_system()
        self.__init_events()
        self.__start_events()

    def __init_studio_system(self):
        """
        Initializes the FMOD Studio API and ensures core system drivers 
        are properly bootstrapped.
        """
        core_system = pyfmodex.System()
        core_system.init()
        core_system.release()
        self.studio_system = StudioSystem()
        self.studio_system.initialize(max_channels=512)

    def __init_events(self, bank_path=DEFAULT_BANK_PATH):
        """
        Higher-level sequence to load bank files and prepare event instances.

        Args:
            bank_path (str, optional): The directory containing bank files. 
                Defaults to ENVIRONMENT_BANK_PATH.
        """
        self._load(bank_path)
        self._prepare_events()

    def _load(self, bank_path=DEFAULT_BANK_PATH):
        """
        Loads the Master, Master.strings, and Environment banks into memory.

        Args:
            bank_path (str): The normalized path to the bank directory.

        Raises:
            FileNotFoundError: If the directory or any of the required 
                bank files are missing.
        """
        if bank_path is None:
            bank_path = self.DEFAULT_BANK_PATH
        bank_path = os.path.normpath(bank_path)
        print(f"[{self.__class__.__name__}] Resolved bank path: {bank_path}")

        if not os.path.isdir(bank_path):
            logging.error(f"Bank directory not found: {bank_path}")
            raise FileNotFoundError(f"Bank directory not found: {bank_path}")
        
        expected_files = [
            "Master.bank",
            "Master.strings.bank",
            "Environment.bank"
        ]

        for f in expected_files:
            full_path = os.path.join(bank_path, f)
            if not os.path.exists(full_path):
                print(f"[{self.__class__.__name__}] Expected bank file missing: {full_path}")
                raise FileNotFoundError(f"Bank directory not found: {bank_path}")
            else:
                self.studio_system.load_bank_file(full_path)

    def _prepare_events(self):
        """
        Retrieves event descriptions and creates instances for rain and wind.
        """
        rain_event_desc = self.studio_system.get_event(RAIN_EVENT_PATH)
        self.rain_inst = rain_event_desc.create_instance()

        wind_event_desc = self.studio_system.get_event(WIND_EVENT_PATH)
        self.wind_inst = wind_event_desc.create_instance()
    
    def __start_events(self):
        """
        Begins playback of ambient loops.
        """
        self.rain_inst.start()
        self.wind_inst.start()

    def update_studio_system(self):
        """
        Synchronizes the FMOD Studio system. Must be called in main loop to 
        apply parameter changes (intensity) to the running instances.
        """
        self.studio_system.update()

    def get_events(self):
        """
        Provides access to the active event instances for external adapters.

        Returns:
            dict: A dictionary mapping "rain" and "wind" to their 
                respective FMOD EventInstances.
        """
        events = {
            "rain": self.rain_inst,
            "wind": self.wind_inst
        }
        return events
    
    def shutdown(self):
        """
        Releases the FMOD Studio System and stops all environmental audio.
        """
        try:
            print(f'Releasing Studio System')
            self.studio_system.release()
        except AttributeError as e:
            e.add_note(f"Fehlerquelle: Die Instanz existiert nicht mehr")
            print(f"Fehler abgefangen {e}")
        else: 
            print(f"Fahre herunter")