# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from ..FMOD.Sounds import ReverseBeep

if __name__ == '__main__':
    reverse_beep = ReverseBeep()
    while True:
        reverse_beep.play()