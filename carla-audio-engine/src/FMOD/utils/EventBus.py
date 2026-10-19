# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from collections import defaultdict
from typing import Callable, Any
from src.FMOD.utils.DataKey import DataKey

class EventBus:
    """
    Centralized Publish-Subscribe (Pub/Sub) system for decoupled communication.

    The EventBus facilitates the flow of simulation data from the SoundModel 
    to various audio adapters. By using this pattern, the data source remains 
    agnostic of the specific sound logic, allowing for a highly modular 
    and extensible architecture.
    """

    def __init__(self):
        """
        Initializes the EventBus with a default dictionary of subscribers.
        """
        self._subscribers: dict[DataKey, list[Callable[[Any], None]]] = defaultdict(list)
        """dict[DataKey, list]: Internal registry mapping DataKeys to their callback functions."""

    def subscribe(self, key: DataKey, callback: Callable[[Any], None]) -> None:
        """
        Registers a listener for a specific simulation data key.

        Args:
            key (DataKey): The specific data channel to subscribe to.
            callback (Callable): The function to be executed when data is published.
        """
        self._subscribers[key].append(callback)

    def unsubscribe(self, key: DataKey, callback: Callable[[Any], None]) -> None:
        """
        Removes a previously registered listener from a data key.

        Args:
            key (DataKey): The data channel to detach from.
            callback (Callable): The specific function to remove from the registry.
        """
        self._subscribers[key].remove(callback)

    def publish(self, key: DataKey, data: Any) -> None:
        """
        Broadcasts simulation data to all listeners of a specific key.

        This method iterates through the subscriber list for the provided key 
        and executes each callback, passing the new simulation data as an argument.

        Args:
            key (DataKey): The data channel to broadcast on.
            data (Any): The simulation value (speed, torque, etc.) to distribute.
        """
        for callback in self._subscribers[key]:
            callback(data)