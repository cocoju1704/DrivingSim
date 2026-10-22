# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from pyfmodex.studio.enums import PLAYBACK_STATE

from ..Sounds.EVSoundEngine import *
from ..utils.EventBus import *
from ..Banks import TriggerBank
from ..utils import DataKey
from ..utils.DataKey import DataKey
from ..utils.EventBus import EventBus
from ..Banks import ExampleBank
import keyboard


class EngineAdapter:
    """
    Adapter responsible for synchronizing vehicle dynamics with the EV sound engine.

    This class subscribes to simulation data from the EventBus (speed and throttle) 
    and translates these values into auditory parameters for the EVSoundEngine. 
    It ensures that engine sounds react dynamically to the driver's input and 
    vehicle state.

    Attributes:
        ev (EVSoundEngine): The engine responsible for generating electric 
            vehicle sounds.
        speed (float): The current velocity of the vehicle in km/h.
        throttle (float): The current throttle input, ranging from 0.0 to 1.0.
    """
    # The motor is heard only when the car really speeds up. Holding a speed takes a third to half
    # throttle with small corrections, but almost no acceleration (|a| < 0.5 m/s^2): silent.
    QUIET_ACCEL = 0.6   # m/s^2 forward acceleration below which the motor is silent
    FULL_ACCEL = 2.5    # m/s^2 at which it is as loud as full throttle
    ACCEL_FILTER = 0.3  # share of the way to a new acceleration per packet (get_acceleration is noisy)

    def __init__(self, bus: EventBus, ev: EVSoundEngine):
        """
        Initializes the EngineAdapter and subscribes to relevant data keys.

        Args:
            bus (EventBus): The system bus used for data subscription.
            ev (EVSoundEngine): The sound engine instance to be controlled.
        """
        self.ev = ev
        self.speed = 0
        self.throttle = 0
        self.accel = 0.0
        bus.subscribe(DataKey.SPEED, self.on_speed)
        bus.subscribe(DataKey.THROTTLE, self.on_throttle)
        bus.subscribe(DataKey.ACCEL_FORWARD, self.on_accel)
        bus.subscribe(DataKey.ACTIVE, self.on_active)
        bus.subscribe(DataKey.BLINKER, self.on_blinker)
        bus.subscribe(DataKey.REVERSE, self.on_reverse)

    def on_blinker(self, on):
        """Turn signal ticking while a turn signal is on (sample engine only)."""
        if hasattr(self.ev, 'set_blinker'):
            if self.ev.is_running is False:
                self.ev.start()
            self.ev.set_blinker(bool(on))

    def on_reverse(self, on):
        """Reverse warning sound while in reverse (sample engine only)."""
        if hasattr(self.ev, 'set_reverse'):
            if self.ev.is_running is False:
                self.ev.start()
            self.ev.set_reverse(bool(on))

    def on_active(self, active):
        """
        Pauses the engine sound while there is no vehicle and resumes it when one is back.

        Args:
            active (bool): False while there is no vehicle or no data from the CARLA side.
        """
        self.ev.set_paused(not active)

    def on_speed(self, speed):
        """
        Callback triggered when a new speed value is published to the EventBus.

        Args:
            speed (float): The updated speed value from the simulation.
        """
        self.speed = speed
        self.update()

    def on_throttle(self, throttle):
        """
        Callback triggered when a new throttle value is published to the EventBus.

        Args:
            throttle (float): The updated throttle input from the simulation.
        """
        self.throttle = throttle
        self.update()

    def on_accel(self, accel):
        """Forward acceleration (m/s^2), smoothed."""
        self.accel += self.ACCEL_FILTER * (accel - self.accel)
        self.update()

    def calculate_torque(self, throttle):
        """
        Calculates a simplified torque value used for sound modulation.

        Args:
            throttle (float): Current throttle position.

        Returns:
            float: 0..1, 0 unless the throttle is pressed and the car speeds up by more than
            QUIET_ACCEL, 1 from FULL_ACCEL on: the motor gets louder the harder it accelerates.
        """
        if throttle <= 0.0:
            return 0.0
        return min(max((self.accel - self.QUIET_ACCEL) / (self.FULL_ACCEL - self.QUIET_ACCEL), 0.0), 1.0)

    def update(self):
        """
        Updates the engine and sound states for the current frame.

        Ensures the sound engine is running and pushes the latest speed 
        and torque parameters to the FMOD system.
        """
        if self.ev.is_running is False:
            self.ev.start()
        self.ev.update_params(self.speed, self.calculate_torque(self.throttle))
        self.ev.system.update()