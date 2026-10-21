# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

import carla
import time
import math
import keyboard

from Classes.CollisionSensor import *

class CarlaClient:
    """Communication interface for the CARLA simulator.

    This class handles the connection to the CARLA server, identifies the 
    player vehicle (tagged as 'hero'), and extracts real-time simulation 
    data required for the sound engine and logic processing.

    Attributes:
        client (carla.Client): The official CARLA client instance. :carla_docs:`carla.Client <python_api/#carlaclient>`
        world (carla.World): The current simulation world instance. :carla_docs:`carla.World <core_world/#the-world>`
        vehicle (carla.Vehicle): The identified player vehicle. :carla_docs:`carla.Vehicle <python_api/#carla.Vehicle>`
        collision_sensor (CollisionSensor): Sensor for detecting impact events. :carla_docs:`Collision detector <ref_sensors/#collision-detector>`
        crash_counter (int): Counter to track the number of collisions.
        honk_trigger (bool): State tracker for the horn input logic.
    """
    _MIN_COLLISION_INTENSITY = 100
    _MS_IN_KMH = 3.6

    def __init__(self, ip,port,timeout):
        try:
            self.client = carla.Client(ip, port)
            self.client.set_timeout(timeout)
        except Exception as e:
            print(f"Carla_client.py konnte sich nicht mit Carla Server verbinden.\nSicherstellen, dass Carla Simulator läuft.")
        self.world = None
        self.vehicle_found = False
        self.vehicle = None
        self.collision_sensor = None
        self.crash_counter = 0
        self.crash_impulse = False
        self.honk_trigger = False
        self.old_handbrake_state = False
        self.handbrake_trigger = False

        self.__connect()
        

    def __connect(self):
        """Connects to the CARLA server and retrieves the simulation world.

            Sets the `self.world` attribute by fetching the current world instance 
            from the CARLA client. This is a prerequisite for manipulating 
            environment actors or weather settings.

            Returns:
                None
        """
        # Wait for the server instead of crashing when it is not ready yet
        while True:
            try:
                self.world = self.client.get_world()
                return
            except RuntimeError:
                print("Waiting for the CARLA server ...")
                time.sleep(2.0)

    def reconnect(self):
        """Fetches the world again (after a map change or server restart) and searches the vehicle anew."""
        self.vehicle_found = False
        self.vehicle = None
        self.__connect()

    def __get_vehicle(self):
        """Finds and returns the primary ego-vehicle from the simulation.

        Iterates through all active vehicle actors in the current world and 
        identifies the one assigned the 'hero' role. This is typically used 
        to bind the simulation sensors to the user-controlled vehicle.

        Returns:
            carla.Vehicle: The vehicle actor with role_name 'hero', 
                           or None if no such vehicle is found.

        Note:
            This method expects the vehicle to have been spawned with 
            the attribute 'role_name' set to 'hero' in CARLA.
        """
        vehicles = self.world.get_actors().filter('vehicle.*')

        for vehicle in vehicles:
            if vehicle.attributes.get('role_name') == "hero":
                print(f"Verbunden mit vorhandenem Fahrzeug: {vehicle.type_id}", flush=True)
                self._waiting_reported = False
                return vehicle
        # Called 20 times a second while waiting: report it only once
        if not getattr(self, "_waiting_reported", False):
            print("Waiting for a vehicle with role_name 'hero' ...", flush=True)
            self._waiting_reported = True
        return None

    def retrieve_data(self):
        """Extracts and aggregates simulation state data into a telemetry packet.

        This method polls the CARLA world for environmental conditions (weather), 
        monitors hardware/keyboard inputs (honk), and fetches real-time vehicle 
        physics. It also manages the lifecycle of the collision sensor and 
        processes collision impulses based on defined intensity thresholds.

        The resulting data packet is formatted for downstream consumption, 
        typically for synchronization with the FMOD audio engine.

        Returns:
            dict or None: A dictionary containing telemetry data, or None if no 
            vehicle is found or initialized.
            
            Telemetry dictionary keys:
                - speed (float): Vehicle speed in km/h.
                - throttle (float): Throttle position [0.0, 1.0].
                - brake (float): Brake position [0.0, 1.0].
                - speed_limit (float): Current road speed limit.
                - gear (int): Current active gear.
                - collision_event (bool): True if a collision above intensity 100 is detected.
                - rain_intensity (float): Precipitation amount [0, 100].
                - wind_intensity (float): Wind strength [0, 100].
                - acceleration (float): Lateral acceleration (Y-axis).
                - honk (bool): Single-trigger state of the horn.
                - handbrake (bool): State of the handbrake.

        Raises:
            AttributeError: Handled internally if vehicle reference is lost during 
                actor switching or rapid simulation resets.
        """
        #Wetterdaten
        weather = self.world.get_weather()
        rain_intensity = weather.precipitation
        wind_intensity = weather.wind_intensity
        #Hupen
        honk = False
        if keyboard.is_pressed('h') and self.honk_trigger:
            honk = False
        elif keyboard.is_pressed('h') and not self.honk_trigger:
            honk = True
            self.honk_trigger = True
        elif not keyboard.is_pressed('h'):
            self.honk_trigger = False
            
        #Fahrzeugdaten
        if self.vehicle_found == False:
            #1. Fahrzeug finden:
            self.vehicle = self.__get_vehicle()
            #2. Variable setzen:
            if self.vehicle is not None:
                self.vehicle_found = True
                #Attach Collision Sensor to vehicle
                self.collision_sensor = CollisionSensor(self.vehicle)
        #3. Daten auslesen:
        if self.vehicle is not None:
            if not self.vehicle.is_alive:
                self.vehicle = self.__get_vehicle()
                self.collision_sensor = CollisionSensor(self.vehicle)
            try:
                acceleration = self.vehicle.get_acceleration()
                speed_limit = self.vehicle.get_speed_limit()
                v = self.vehicle.get_velocity()
                kmh = self._MS_IN_KMH * math.sqrt(v.x**2 + v.y**2 + v.z**2)
                control = self.vehicle.get_control()
                lights = self.vehicle.get_light_state()
                blinker = bool(lights & (carla.VehicleLightState.LeftBlinker | carla.VehicleLightState.RightBlinker))
                gear = control.gear
                handbrake = control.hand_brake
                steer = control.steer

                if self.old_handbrake_state is False and handbrake is True:
                    self.handbrake_trigger = True
                self.old_handbrake_state = self.handbrake_trigger

                if self.collision_sensor.collision_counter > self.crash_counter and self.collision_sensor.intensity > self._MIN_COLLISION_INTENSITY:
                    self.crash_impulse = True
                    self.crash_counter = self.collision_sensor.collision_counter

                #4. Daten in JSON Packet umwandeln:
                data_packet = {
                        "speed": round(kmh, 2),
                        "throttle": round(control.throttle, 2),
                        "brake": round(control.brake, 2),
                        "speed_limit": speed_limit,
                        "message": "GREEN",
                        "gear" : gear,
                        "collision_event" : self.crash_impulse,
                        "rain_intensity" : rain_intensity,
                        "wind_intensity" : wind_intensity,
                        "acceleration" : acceleration.y,
                        "honk" : honk,
                        "handbrake" : self.handbrake_trigger,
                        "blinker" : blinker,
                        "reverse" : bool(control.reverse)
                    }
                self.crash_impulse = False
                self.handbrake_trigger = False
                return data_packet
            except (AttributeError, RuntimeError) as e:
                        # Catching RuntimeError as well, as CARLA often throws this if the actor is destroyed
                        print(f"Vehicle reference lost or switching: {e}")
                        self.vehicle_found = False
                        self.vehicle = None
                        return None # Return None so the caller knows data is currently unavailable


    
    def set_rain(self, in_rain_intensity):
        """Adjusts the precipitation and road wetness levels in the simulation.

        This method updates the CARLA weather parameters simultaneously to ensure 
        visual rain matches the physical road conditions (puddles/friction).

        Args:
            in_rain_intensity (float/int): The intensity of the rain. 
                Typically a value between 0 (none) and 100 (heavy).
        
        Returns:
            None
        """
        weather = self.world.get_weather()
        weather.precipitation = float(in_rain_intensity)
        weather.wetness = float(in_rain_intensity)
        self.world.set_weather(weather)
    
    def set_wind(self, in_wind_intensity=0):
        """Sets the wind intensity for the simulation environment.

        Updates the physical wind force acting on actors and environmental 
        elements like trees or rain particles.

        Args:
            in_wind_intensity (float/int, optional): The wind strength. 
                Ranges from 0 to 100. Defaults to 0.

        Returns:
            None
        """
        weather = self.world.get_weather()
        weather.wind_intensity = float(in_wind_intensity)
        self.world.set_weather(weather)
