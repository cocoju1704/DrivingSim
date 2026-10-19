# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from enum import Enum

class RangeLevel(Enum):
    """
    Generic base class for level definitions with range bounds and output mapping.

    This utility allows for the categorization of continuous numeric simulation 
    data into discrete states. It is primarily used to map percentages (like 
    rain or wind intensity) into specific integer values required by FMOD 
    Studio parameters.
    """
    def __init__(self, lower, upper, mapped_value):
        """
        Initializes a range level with specific boundaries.

        Args:
            lower (float): The bottom threshold of this level.
            upper (float): The top threshold of this level.
            mapped_value (int): The discrete value to be sent to FMOD.
        """
        self.lower = lower
        """float: The lower boundary of the range."""
        
        self.upper = upper
        """float: The upper boundary of the range."""
        
        self.mapped_value = mapped_value
        """int: The integer value used for FMOD parameter modulation."""

    def contains(self, value):
        """
        Checks whether the given value falls within this level's range.

        The logic implements a specific boundary rule: the lower bound is 
        inclusive only if it is 0.0, otherwise it is treated as exclusive 
        to prevent overlap between adjacent levels.

        Args:
            value (float): The numeric value to test against the range.

        Returns:
            bool: True if the value is within the bounds, False otherwise.
        """
        return self.lower < value <= self.upper if self.lower != 0 else self.lower <= value <= self.upper

    @classmethod
    def from_value(cls, value):
        """
        Factory method to find the matching level for a given numeric input.

        Iterates through all members of the Enum and returns the level where 
        :meth:`contains` evaluates to True.

        Args:
            value (float): The simulation value to be categorized.

        Returns:
            RangeLevel: The matching Enum member, or None if no match is found.
        """
        for level in cls:
            if level.contains(value):
                return level
        return None