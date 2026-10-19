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
from pathlib import Path
from .config import *
os.environ["PYFMODEX_DLL_PATH"] = FMOD_CORE_DLL
os.environ["PYFMODEX_STUDIO_DLL_PATH"] = FMOD_STUDIO_DLL

import pyfmodex
from pyfmodex.studio import StudioSystem
from pyfmodex.studio.enums import PLAYBACK_STATE
from pyfmodex.exceptions import FmodError

class ExampleBank:
    """
    This class handles the low-level initialization of the FMOD Studio System, 
    manages the loading of .bank files, and provides an interface for retrieving 
    event instances. It serves as a blueprint for specialized banks like 
    :class:`EnvironmentBank` and :class:`TriggerBank`.

    Note:
        The class explicitly configures 'PYFMODEX_DLL_PATH' and 
        'PYFMODEX_STUDIO_DLL_PATH' to locate the FMOD Engine binaries on Windows.

    Attributes:
        studio_system (StudioSystem): The core FMOD Studio System instance 
            managing audio execution.
    """
    EXAMPLE_EVENT_PATH = "event:/Example"
    """EXAMPLE_EVENT_PATH (str): The FMOD project path for the example event."""
    
    def __init__(self):
        """
        Initializes the FMOD Studio System and prepares bank-specific events.
        """
        self.__init_studio_system()
        self.__init_events()

    def __init_studio_system(self):
        """
        Bootstraps the FMOD Studio API.
        
        This private method initializes a temporary core system to ensure 
        drivers are ready, then instantiates and initializes the StudioSystem 
        with 512 virtual channels.
        """
        core_system = pyfmodex.System()
        core_system.init()
        core_system.release()
        self.studio_system = StudioSystem()
        self.studio_system.initialize(max_channels=512)

    def __init_events(self, bank_path=EXAMPLE_EVENT_PATH):
        """
        Orchestrates the loading of banks and preparation of sound events.

        Args:
            bank_path (str): The path to the specific FMOD bank or event.
        """
        self._load(bank_path)
        self._prepare_events()

    def _load(self, bank_path=EXAMPLE_EVENT_PATH):
        """
        Loads FMOD .bank files from the local filesystem into memory.

        Args:
            bank_path (str): The filesystem path or event identifier.
        """
        # if bank_path is None:
        #     bank_path = DEFAULT_BANK_PATH
        # bank_path = os.path.normpath(bank_path)
        # print(f"[{self.__class__.__name__}] Resolved bank path: {bank_path}")

        # if not os.path.isdir(bank_path):
        #     raise FileNotFoundError(f"Bank directory not found: {bank_path}")

        # expected_files = [
        #     "Master.bank",
        #     "Master.strings.bank",
        #     "Example.bank"
        # ]

        # for f in expected_files:
        #     full_path = os.path.join(bank_path, f)
        #     if not os.path.exists(full_path):
        #         print(f"[{self.__class__.__name__}] Expected bank file missing: {full_path}")
        #     else:
        #         self.studio_system.load_bank_file(full_path)
        pass

    def _prepare_events(self):
        """
        Creates instances of FMOD events from the loaded banks.
        
        This method should be overridden in subclasses to assign specific 
        event instances to class attributes.
        """
        # example_event = self.studio_system.get_event(EXAMPLE_EVENT_PATH)
        # self.example_sound = example_event.create_instance()
        pass

    def update_studio_system(self):
        """
        Advances the FMOD Studio playback engine.
        
        This must be called in the main loop to 
        process playback states, parameter changes, and 3D positioning.
        """
        self.studio_system.update()

    def get_events():
        """
        Returns a dictionary of available event instances.

        Returns:
            dict: A mapping of event names to FMOD EventInstance objects.
        """
        events = {
            # See EnvironmentBank for example
        }
        return events

    def shutdown(self):
        """
        Gracefully releases the FMOD Studio System and frees native memory.
        
        Ensures that all audio handles are invalidated to prevent memory leaks 
        during simulation shutdown.
        """
        try:
            print(f'Releasing Studio System')
            self.studio_system.release()
        except AttributeError as e:
            e.add_note(f"Source of error: Instance does not exist anymore")
            print(f"Error: {e}")
        else:
            print(f"Shutdown")