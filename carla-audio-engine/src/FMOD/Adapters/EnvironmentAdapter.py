# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from src.FMOD.Banks import EnvironmentBank
from src.FMOD.utils import DataKey  
from src.FMOD.utils.DataKey import DataKey
from ..utils.EventBus import EventBus
from .RainIntensity import RainIntensity
from .WindIntensity import WindIntensity
from ..utils import RangeLevel

import pyfmodex
from pyfmodex.studio import StudioSystem 


class EnvironmentAdapter:
    """
    Adapter responsible for mapping environmental simulation data to FMOD sound events.

    This class monitors environmental factors like rain and wind intensity from the 
    EventBus. It translates these raw simulation values into discrete levels 
    (defined by :class:`RainIntensity` and :class:`WindIntensity`) and updates 
    the corresponding FMOD Studio parameters to modulate the ambient audio.

    Attributes:
        bank (EnvironmentBank): The sound bank containing environmental audio events.
        rain_event (EventInstance): The FMOD event instance controlling rain audio.
        wind_event (EventInstance): The FMOD event instance controlling wind audio.
    """
    def __init__(self, event_bus: EventBus, bank: EnvironmentBank):
        """
        Initializes the EnvironmentAdapter and subscribes to relevant data keys.

        Args:
            event_bus (EventBus): The system bus for subscribing to intensity data.
            bank (EnvironmentBank): The bank instance providing access to FMOD events.
        """
        self.bank = bank
        events = self.bank.get_events()
        
        self.rain_event = events["rain"]
        self.wind_event = events["wind"]

        event_bus.subscribe(DataKey.RAIN_INTENSITY, self.on_rain)
        event_bus.subscribe(DataKey.WIND_INTENSITY, self.on_wind)
        event_bus.subscribe(DataKey.ACTIVE, self.on_active)

    def on_active(self, active: bool):
        """
        Silences rain and wind while there is no vehicle. When it is back, the
        :class:`SoundModel` publishes the current intensities again.

        Args:
            active (bool): False while there is no vehicle or no data from the CARLA side.
        """
        if not active:
            self.on_rain(0)
            self.on_wind(0)

    def on_rain(self, intensity: float):
        """
        Callback triggered by rain intensity updates from the simulation.

        Maps the float intensity to a discrete FMOD parameter 'regenstaerke'.

        Args:
            intensity (float): The raw rain intensity value from the simulation.
        """
        value = 0
        rain_level = RainIntensity.from_value(intensity)
        if rain_level:
            value = rain_level.mapped_value  # 0,1,2,3
        else:
            print(self.__class__.__name__ + ":Invalid intensity value")
            return
        
        self.rain_event.set_parameter_by_name("regenstaerke", value)
        self.bank.update_studio_system() 

    def on_wind(self, intensity: float):
        """
        Callback triggered by wind intensity updates from the simulation.

        Maps the float intensity to a discrete FMOD parameter 'Windstaerke'.

        Args:
            intensity (float): The raw wind intensity value from the simulation.
        """
        value = 0
        wind_level = WindIntensity.from_value(intensity)
        if wind_level:
            value = wind_level.mapped_value  # 0,1,2
        else:
            print(self.__class__.__name__ + ":Invalid intensity value")
            return
        
        self.wind_event.set_parameter_by_name("Windstaerke", value)
        self.bank.update_studio_system()