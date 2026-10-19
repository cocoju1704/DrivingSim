# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from ..utils import *
from ..Banks import *
from ..Sounds import *
import keyboard
import time

import pyfmodex
from pyfmodex.studio import StudioSystem 
from pyfmodex.studio.enums import PLAYBACK_STATE
from pyfmodex.exceptions import FmodError

'''
Erklärung für self.honk_counter:
In SoundModel.py wird bei jeder Änderung des Wertes von Honk der Wert veröffentlicht.
Bei einem Tastendruckt wurde also honk immer doppelt getriggert.
durch die Einführung des Zählers und der Abfrage ob der Zähler gerade ist, wird 
das Event nur noch korrekt ein einziges Mal abgespielt
'''

class TriggerAdapter:
    """
    Adapter for managing discrete sound triggers based on simulation events.

    This class handles one-shot audio events such as gear shifts, crashes, 
    speed warnings, and the vehicle horn. It implements internal debouncing 
    logic and state tracking (e.g., counters and flags) to ensure sounds are 
    triggered correctly and only once per event, preventing double-triggering 
    from the EventBus.

    Attributes:
        reverse_beep (ReverseBeep): Engine for the rhythmic reverse warning sound.
        bank (TriggerBank): FMOD bank containing one-shot sound events.
        honk_counter (int): Counter used to debounce horn events, ensuring the 
            sound only plays once per key press.
    """
    GEAR_REVERSE = -1
    """GEAR_REVERSE (int) = -1 : Value CARLA Simulator returnes when reverse gear is selected"""
    SPEED_LIMIT = 100
    """SPEED_LIMIT (int) = 100 : Sets Value for speed warning if vehicle exceeds this limit"""
    HANDBRAKE_SPEED = 40
    """HANDBRAKE_SPEED (int) = 40 : Minimum speed for the handbrake sound to play"""
    def __init__(self, event_bus: EventBus, rev_beep: ReverseBeep, bank: TriggerBank):
        """
        Initializes the TriggerAdapter and subscribes to relevant data keys.

        Args:
            event_bus (EventBus): The system bus used for data subscription.
            rev_beep (ReverseBeep): The sound engine instance for reverse beeps.
            bank (TriggerBank): The bank containing one-shot audio instances.
        """
        self.past_gear = None
        self.speed_trigger = False
        self.crash_trigger = False
        self.honk_trigger = False
        self.handBrake_trigger = False
        self.reverse_beep = rev_beep
        self.bank = bank
        self.crash_counter = 0
        self.honk_counter = 1
        self.handBrake_flag = False
        self.speed = 0
        event_bus.subscribe(DataKey.GEAR, self.on_reverse)
        event_bus.subscribe(DataKey.COLLISION_EVENT, self.on_crash)
        event_bus.subscribe(DataKey.SPEED, self.on_speed)
        event_bus.subscribe(DataKey.HONK, self.on_honk)
        event_bus.subscribe(DataKey.HANDBRAKE, self.on_handBrake)

    def on_reverse(self, current_gear):
        """
        Evaluates gear changes to trigger the reverse beep engine.

        Args:
            current_gear (int): The current gear value from the simulation.
        """
        val = None
        if current_gear == self.GEAR_REVERSE and self.past_gear == None:
            val = True
        elif current_gear == self.GEAR_REVERSE and self.past_gear != self.GEAR_REVERSE:
            val = True
        elif current_gear == self.GEAR_REVERSE and self.past_gear == self.GEAR_REVERSE:
            val = False
        self.past_gear = current_gear
        if val == True:
            self.reverse_beep.play()

    def on_tick(self):
        """
        Updates the internal sound engine and FMOD system.
        """
        self.reverse_beep.update()
        self.bank.update_studio_system()

    def on_speed(self, speed=0):
        """
        Triggers an overspeed warning sound if the speed limit is exceeded.

        The trigger is reset only once the warning sound has finished playing.

        Args:
            speed (float): Current vehicle speed.
        """
        self.speed = speed
        self.reverse_beep.update()
        if speed > self.SPEED_LIMIT and self.speed_trigger is False:
            self.bank.play_warning()
            self.speed_trigger = True
        if self.bank.warning_sound.playback_state == PLAYBACK_STATE.STOPPED:
            self.speed_trigger = False

    def on_crash(self, crash):
        """
        Triggers the crash sound effect upon impact.

        Args:
            crash: unused. Necesarry due to the event bus design
        """
        if self.crash_trigger is False and self.crash_counter >= 1:
            self.bank.play_crash()
            self.crash_trigger = True
        if self.bank.crash_sound.playback_state == PLAYBACK_STATE.STOPPED:
            self.crash_trigger = False
        if self.crash_counter == 0:
            self.crash_counter = self.crash_counter + 1
    
    def on_honk(self, honk):
        """
        Triggers the vehicle horn with debouncing logic.

        Uses an internal counter to filter out redundant triggers from 
        continuous key-press updates.

        Args:
            honk: unused. Necesarry due to the event bus design
        """
        if self.honk_trigger is False and self.honk_counter % 2 == 0:
            self.bank.play_honk()
            self.crash_trigger = True
        if self.bank.honk_sound.playback_state == PLAYBACK_STATE.STOPPED:
            self.honk_trigger = False
        self.honk_counter = self.honk_counter + 1

    def on_handBrake(self, handBrake):
        """
        Triggers the handbrake sound effect if the vehicle is moving.

        Args:
            handBrake: unused. Necesarry due to the event bus design
        """
        if self.speed > self.HANDBRAKE_SPEED:
            if self.handBrake_trigger is False and self.handBrake_flag:
                self.bank.play_handBrake()
                self.handBrake_trigger = True
            if self.bank.handBrake_sound.playback_state == PLAYBACK_STATE.STOPPED:
                self.handBrake_trigger = False
            if not self.handBrake_flag:
                self.handBrake_flag = True
