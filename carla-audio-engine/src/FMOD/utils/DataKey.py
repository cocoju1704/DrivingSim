# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from enum import Enum

class DataKey(str, Enum):
    """
    Enumeration of simulation data keys used for system-wide communication.

    This class defines the standardized keys used by the :class:`SoundModel` 
    to identify simulation variables received from the CARLA client. By 
    inheriting from ``str``, these members act as validated constants that 
    ensure consistency between the network layer, the EventBus, and the 
    various sound adapters.
    """

    ACCELERATION = "acceleration"
    """str: Key for vehicle acceleration."""

    BRAKE = "brake"
    """str: Key for brake pedal input state."""

    COLLISION_EVENT = "collision_event"
    """str: Trigger key for vehicle impact detections."""

    GEAR = "gear"
    """str: Key for transmission gear index."""

    MESSAGE = "message"
    """str: Key for general purpose system or debug messages."""

    RAIN_INTENSITY = "rain_intensity"
    """str: Key for precipitation"""

    SPEED = "speed"
    """str: Key for vehicle velocity."""

    SPEED_LIMIT = "speed_limit"
    """str: Key for local speed limit of the current road segment."""

    THROTTLE = "throttle"
    """str: Key for throttle pedal input state."""

    WIND_INTENSITY = "wind_intensity"
    """str: Key for wind speed percentage."""

    HONK = "honk"
    """str: Key for state of the vehicle's horn trigger."""

    HANDBRAKE = "handbrake"
    """str: Key for state of the manual parking brake engagement."""

    ACTIVE = "active"
    """str: Key set by the :class:`SoundModel`: False while there is no vehicle or no data from the CARLA side."""