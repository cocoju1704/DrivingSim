# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

import os
from ..Banks.config import FMOD_CORE_DLL, FMOD_STUDIO_DLL
os.environ["PYFMODEX_DLL_PATH"] = FMOD_CORE_DLL
os.environ["PYFMODEX_STUDIO_DLL_PATH"] = FMOD_STUDIO_DLL
import pyfmodex
import time
from pyfmodex.enums import DSP_TYPE

class ReverseBeep:
    """
    Procedural audio generator for vehicle reverse warning signals.

    This class synthesizes a rhythmic "beep" sound using a DSP signal chain 
    instead of audio files. It uses a high-frequency sine oscillator processed 
    through a distortion unit to create the characteristic industrial warning 
    tone. The timing logic (on/off cycles) is managed via the internal state.

    Attributes:
        system (pyfmodex.System): The dedicated FMOD Core system for reverse sounds.
        is_playing (bool): Tracks whether a beep pulse is currently active.
        start_time (float): Timestamp of when the current beep pulse started.
        grundton (DSP): Sine wave oscillator (1500Hz).
        verzerrung (DSP): Distortion unit for harmonic grit.
        fader (DSP): Final gain stage for the signal chain.
    """
    def __init__(self):
        """
        Initializes the audio system and constructs the DSP signal chain.
        """
        self.system = pyfmodex.System()
        self.system.init()
        self.lautstaerke_regler = self.system.master_channel_group
        self.lautstaerke_regler.volume = 0.05
        self.grundton = None
        self.verzerrung = None
        self.channel = None
        self.start_time = 0
        self.is_playing = False
        self.fader = None

        self.dynamisch_Beep_erstellen()
    
    def dynamisch_Beep_erstellen(self):
        """
        Constructs the DSP signal chain: Oscillator -> Distortion -> Fader.
        
        Configures a Sine wave at 1500.0Hz and applies full distortion (level 1.0) 
        to create the sharp, piercing warning tone.
        """
        if self.grundton is None:
            # 1. Oszillator erstellen
            self.grundton = self.system.create_dsp_by_type(DSP_TYPE.OSCILLATOR)
            self.grundton.set_parameter_int(0, 0)#Wellenform Sinus (0 bis 3 möglich)
            self.grundton.set_parameter_float(1, 1500.0)#Frequenz

            # 2. Verzerrung erstellen
            self.verzerrung = self.system.create_dsp_by_type(DSP_TYPE.DISTORTION)
            self.verzerrung.set_parameter_float(0, 1)#Verzerrungsfaktor

            # 3. Fader erstellen
            self.fader = self.system.create_dsp_by_type(DSP_TYPE.FADER)
            self.fader.set_parameter_float(0, 1)

            # 4. Kette erstellen
            self.verzerrung.add_input(self.grundton)
            # Verzerrung -> Fader
            self.fader.add_input(self.verzerrung)

            # Alle aktivieren
            self.grundton.active = True
            self.verzerrung.active = True
            self.fader.active = True

    def play(self):
        """
        Initiates a single beep pulse.

        Starts the DSP chain on a new channel and records the start time 
        to facilitate the 400ms duration limit.
        """   
        if not self.is_playing:
            # Wir starten jetzt ganz normal
            self.channel = self.system.play_dsp(self.grundton)
            self.channel.add_dsp(0, self.verzerrung)
            self.channel.add_dsp(0, self.fader)
            
            self.start_time = time.time()
            self.is_playing = True

    def update(self):
        """
        Handles the lifecycle and timing of the beep pulse.

        If a beep has been active for more than 0.4 seconds (400ms), 
        the channel is stopped. Also advances the FMOD system clock.
        """
        if self.is_playing and self.channel:
            if time.time() - self.start_time >= 0.4:
                self.channel.stop()
                self.is_playing = False
        if self.system:
            self.system.update()

    def shutdown(self):
        """
        Releases FMOD resources and shuts down the reverse beep audio system.
        """
        if self.system:
            print(f'Räume den Reverse Beep auf')
            self.system.release()
            self.system = None            