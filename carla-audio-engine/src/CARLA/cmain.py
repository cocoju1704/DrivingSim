# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

"""
CARLA Operations Handler
========================
This module manages core CARLA operations, including client initialization, 
simulation data retrieval, and dynamic weather configuration.
"""

import time
from threading import Thread
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from src.CARLA.Classes import *

#: True: open the rain/wind slider window. False: set the fixed values below once and ask nothing.
SHOW_WEATHER_WINDOW = False
RAIN_INTENSITY = 0
WIND_INTENSITY = 10

def carla_data_loop(client, sock):
    """
    Executes a continuous data retrieval loop.

    Fetches the latest simulation state from the CARLA server and 
    broadcasts it via the specified UDP socket.

    Args:
        client (CarlaClient): Active instance of the CARLA client.
        sock (Socket): UDP socket instance used for publishing simulation packets.
    """
    while True:
        try:
            data_packet = client.retrieve_data()
        except RuntimeError as e:  # map changed or server restarted: the old world is gone
            print(f"Lost the CARLA world ({e}), reconnecting")
            client.reconnect()
            continue
        sock.publish_data(data_packet)
        time.sleep(0.05)

def main():
    """
    Main entry point for CARLA operations.

    Initializes the client and weather modules, then spawns a background 
    thread to handle the continuous data retrieval loop.
    """
    client = CarlaClient('localhost', 2000, 20.0)
    sock = Socket()
    if not SHOW_WEATHER_WINDOW:
        client.set_rain(RAIN_INTENSITY)
        client.set_wind(WIND_INTENSITY)
        print(f"Weather set: rain {RAIN_INTENSITY}, wind {WIND_INTENSITY}", flush=True)
        carla_data_loop(client, sock)
        return
    weather = Weather(client)
    carla_thread = Thread(target=carla_data_loop, args=(client, sock), daemon=True)
    carla_thread.start()
    weather.run()

if __name__ == '__main__':
    main()