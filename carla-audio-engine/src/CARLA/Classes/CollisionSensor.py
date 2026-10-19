# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

import weakref
import collections
import math
import carla

class CollisionSensor(object):
    """Sensor responsible for detecting and logging vehicle collisions.

    This class wraps a CARLA collision sensor, attaching it to a parent vehicle 
    to monitor physical impacts. It maintains a rolling history of collision 
    intensities and uses class-level variables to track global collision events.
    """
    collision_counter = 0
    """int: A global counter incremented on every collision event."""
    intensity = 0
    """float: The magnitude (Euclidean norm) of the last detected collision impulse."""

    def __init__(self, parent_actor):
        """Initializes the sensor and attaches it to the parent actor.

        Args:
            parent_actor (carla.Actor): The vehicle actor to which the 
                collision sensor will be attached.
        """
        self.sensor = None
        self.history = []
        if parent_actor is not None:
            self._parent = parent_actor
            self.world = self._parent.get_world()
            print(self.world)
            bp = self.world.get_blueprint_library().find('sensor.other.collision')
            self.sensor = self.world.spawn_actor(bp, carla.Transform(), attach_to=self._parent)
            # We need to pass the lambda a weak reference to self to avoid circular reference.
            weak_self = weakref.ref(self)
            self.sensor.listen(lambda event: CollisionSensor._on_collision(weak_self, event))

    def get_collision_history(self):
        """Retrieves the collision history.

        Returns:
            collections.defaultdict: A mapping of simulation frames to the 
            total collision intensity recorded during that frame.
        """
        history = collections.defaultdict(int)
        for frame, intensity in self.history:
            history[frame] += intensity
        return history

    @staticmethod
    def _on_collision(weak_self, event):
        """Callback triggered by CARLA when a collision occurs.

        Calculates the Euclidean norm of the normal impulse vector to determine 
        collision intensity and updates the rolling history buffer.

        Args:
            weak_self (weakref.ref): A weak reference to the CollisionSensor 
                instance to prevent circular memory references.
            event (carla.CollisionEvent): The event object provided by CARLA 
                containing impulse and actor data.
        """
        CollisionSensor.collision_counter = CollisionSensor.collision_counter + 1
        self = weak_self()
        if not self:
            return
        impulse = event.normal_impulse
        CollisionSensor.intensity = math.sqrt(impulse.x**2 + impulse.y**2 + impulse.z**2)
        self.history.append((event.frame, CollisionSensor.intensity))
        if len(self.history) > 4000:
            self.history.pop(0)