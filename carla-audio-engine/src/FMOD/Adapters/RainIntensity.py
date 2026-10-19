# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from ..utils import RangeLevel

class RainIntensity(RangeLevel):
    """
    Enum-style class defining rain intensity ranges for FMOD parameter mapping.

    This class categorizes raw rain intensity percentages (0-100) into 
    four discrete levels. Each level is defined by a tuple representing 
    the inclusive lower bound, the exclusive upper bound, and the 
    corresponding FMOD parameter value used by the :class:`EnvironmentAdapter`.
    """
    NONE = (0, 10, 0)
    """NONE (tuple): Range (0, 10) mapped to FMOD value 0."""
    LOW = (10, 44, 1)
    """LOW (tuple): Range (10, 44) mapped to FMOD value 1."""
    MEDIUM = (44, 77, 2)
    """MEDIUM (tuple): Range (44, 77) mapped to FMOD value 2."""
    HIGH = (77, 100, 3)
    """HIGH (tuple): Range (77, 100) mapped to FMOD value 3."""