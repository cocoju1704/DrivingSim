# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

import time
import keyboard

from ..FMOD.Sounds import EVSoundEngine

if __name__ == '__main__':
    tesla = EVSoundEngine()
    tesla.start()
    
    speed = 0.0
    torque = 0.0
    last_time = time.time()
    
    print("Tesla Interior Sound Engine (Fixed Hierarchie)")
    print("W/S: Fahren | ESC: Beenden")

    while not keyboard.is_pressed('ESC'):
        dt = time.time() - last_time
        last_time = time.time()
        
        if keyboard.is_pressed('w'): 
            speed = min(speed + 20 * dt, 200)
            torque = 1.0
        elif keyboard.is_pressed('s'): 
            speed = max(speed - 40 * dt, 0)
            torque = -0.8 # Rekuperation
        else:
            speed = max(speed - 5 * dt, 0)
            torque *= 0.1 # Ausrollen
            
        tesla.update_params(speed, torque)
        tesla.system.update()
        
        print(f"\rSpeed: {speed:5.1f} km/h | Motor-Load: {torque:4.1f}", end="")
        time.sleep(0.01)
    
    tesla.stop()