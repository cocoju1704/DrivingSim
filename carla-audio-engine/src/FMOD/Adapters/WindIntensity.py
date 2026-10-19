# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from ..utils import RangeLevel

class WindIntensity(RangeLevel):
    """
    Enum-style class defining wind intensity ranges for FMOD parameter mapping.

    This class categorizes raw wind intensity percentages (0-100) into 
    three discrete levels. Each level is defined by a tuple containing 
    the inclusive lower bound, the exclusive upper bound, and the 
    corresponding FMOD parameter value used by the :class:`EnvironmentAdapter` 
    to control 'Windstaerke'.
    """
    NONE = (0, 10, 0)
    """NONE (tuple): Range (0, 10) mapped to FMOD value 0."""
    LOW = (10, 55, 1)
    """LOW (tuple): Range (10, 55) mapped to FMOD value 1."""
    HIGH = (55, 100, 2)
    """HIGH (tuple): Range (55, 100) mapped to FMOD value 2."""