# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

import socket as udp
import json
import time

class Socket:
    """Handles UDP networking for broadcasting simulation telemetry.

    This class initializes a local UDP socket to transmit JSON-encoded data 
    packets. It acts as the primary transmitter for sending CARLA vehicle 
    states and environmental data to external listeners, such as the FMOD 
    integration layer.

    Attributes:
        UDP_IP (str): The destination IP address (default: "127.0.0.1").
        UDP_PORT (int): The destination port number (default: 5005).
    """
    def __init__(self):
        """Initializes the UDP socket and sets network parameters."""
        self.UDP_IP = "127.0.0.1"
        self.UDP_PORT = 5005
        self.socket = udp.socket(udp.AF_INET, udp.SOCK_DGRAM)
    def publish_data(self, data_packet):
        """Serializes and sends a data packet over the UDP socket.

        Converts a dictionary-based data packet into a JSON string, 
        encodes it into bytes, and transmits it to the pre-configured 
        IP and Port.

        Args:
            data_packet (dict): The telemetry data dictionary generated 
                by the CarlaClient's retrieve_data method.

        Returns:
            None
        """
        message = json.dumps(data_packet).encode()
        self.socket.sendto(message, (self.UDP_IP, self.UDP_PORT))