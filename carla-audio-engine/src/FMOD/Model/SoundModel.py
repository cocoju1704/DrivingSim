# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

import socket
from ..utils import DataKey
from ..utils import EventBus
import json

UDP_IP = "127.0.0.1"
UDP_PORT = 5005

class SoundModel:
    """
    Network listener and data dispatcher for the audio engine.

    This class operates as the primary data gateway. It listens for incoming 
    UDP packets containing simulation state data (in JSON format), decodes them, 
    and identifies changes between consecutive data frames. Significant changes 
    are then published to the :class:`EventBus` to notify registered adapters.

    Attributes:
        bus (EventBus): The central communication hub for publishing simulation updates.
        sock (socket.socket): The UDP socket used for receiving simulation data.
        client_data (dict): A local cache of the most recent data frame received 
            from the simulation client.
    """
    def __init__(self, event_bus: EventBus):
        """
        Initializes the network socket and binds it to the local UDP endpoint.

        Args:
            event_bus (EventBus): The bus instance where simulation data 
                will be dispatched.
        """
        self.bus = event_bus
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((UDP_IP, UDP_PORT))
        self.sock.settimeout(1.0)  # no packet for 1 s: the CARLA side is gone

        self.client_data: dict[str, object] = {}

    def _decode(self) -> dict[str, object]:
        """
        Receives and deserializes the incoming UDP data packet.

        Returns:
            dict[str, object]: A dictionary representation of the received JSON data.
        """
        try:
            data, _ = self.sock.recvfrom(2048)
        except (socket.timeout, ConnectionResetError):
            return None
        # JSON-String to dictionary
        return json.loads(data.decode())
    
    def _calculate_diff(self, new_values: dict[str, object], old_values: dict[str, object]) -> dict[DataKey, object]:
        """
        Compares the new data frame with the previous state to detect changes.

        This method performs a delta-check to ensure that only modified values 
        are published. It also converts string keys from the JSON packet into 
        formal :class:`DataKey` enum members.

        Args:
            new_values (dict): The data frame just received.
            old_values (dict): The data frame from the previous tick.

        Returns:
            dict[DataKey, object]: A dictionary of modified keys and their new values.
        """
        diff: dict[DataKey, object] = {}
        for key_str, value in new_values.items():
            if old_values.get(key_str) != value:
                try:
                    key_enum = DataKey(key_str)  # String -> Enum
                    diff[key_enum] = value
                except ValueError:
                    print(f"Unknown key received: {key_str}")
        return diff

    def on_tick(self) -> None:
        """
        Main execution loop for the network listener.

        Captures a new data frame, identifies changed attributes, and 
        publishes the differences to the EventBus. This should be called 
        frequently (typically within the main program loop) to ensure 
        audio-simulation synchronicity.
        """    
        old_data = self.client_data.copy()
        new_data = self._decode()
        # No vehicle (null packet) or no packet at all: only ACTIVE changes, so the adapters
        # silence the looping sounds. The next real packet differs in every key and restores them.
        if new_data is None:
            self.client_data = {DataKey.ACTIVE.value: False}
        else:
            self.client_data = new_data.copy()
            self.client_data[DataKey.ACTIVE.value] = True

        diff = self._calculate_diff(self.client_data, old_data)

        for key, value in diff.items():
            self.bus.publish(key, value)

