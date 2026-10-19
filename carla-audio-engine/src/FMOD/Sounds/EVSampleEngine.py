import os

from ..Banks.config import FMOD_CORE_DLL, FMOD_STUDIO_DLL, SOUNDS_DIR
os.environ["PYFMODEX_DLL_PATH"] = FMOD_CORE_DLL
os.environ["PYFMODEX_STUDIO_DLL_PATH"] = FMOD_STUDIO_DLL

import pyfmodex
from pyfmodex.flags import MODE

#: Motor/inverter loop. Its pitch follows the speed, its volume the speed and throttle.
MOTOR_FILE = SOUNDS_DIR / "ev_motor.wav"
#: Tire/road noise loop. Its volume follows the speed.
ROAD_FILE = SOUNDS_DIR / "ev_road.wav"
#: Interior cabin noise loop (HVAC hum, muffled wind/road). Volume proportional to the speed, slightly higher with speed.
CABIN_FILE = SOUNDS_DIR / "ev_cabin.wav"


class EVSampleEngine:
    """
    Sample-based Electric Vehicle (EV) sound: recorded loops instead of oscillators.

    Drop-in replacement for :class:`EVSoundEngine` (same start / update_params / stop
    interface). Put seamless loops in the top-level ``Sounds`` folder; each one is optional:

    - ``ev_motor.wav``: motor whine, played back faster (higher) with speed.
      Without it, the synthesized motor of :class:`EVSoundEngine` is used if SYNTH_MOTOR is True.
    - ``ev_road.wav``: tire/road rumble, louder with speed.
    - ``ev_cabin.wav``: interior cabin noise, silent up to CABIN_START_SPEED, then proportional to the speed.

    Tune the class constants below to change how the sound reacts.
    """
    TOP_SPEED = 120.0           # km/h at which pitch and volume reach their maximum
    MOTOR_PITCH_MIN = 0.7       # playback speed at standstill (1.0 = as recorded)
    MOTOR_PITCH_MAX = 1.8       # playback speed at TOP_SPEED
    MOTOR_VOLUME_IDLE = 0.05    # standstill, no throttle
    MOTOR_VOLUME_SPEED = 0.35   # added at TOP_SPEED
    MOTOR_VOLUME_THROTTLE = 0.3 # added while the throttle is pressed
    ROAD_VOLUME_MAX = 0.6       # road noise at TOP_SPEED
    CABIN_START_SPEED = 20.0    # km/h; at or below this the cabin noise is silent
    CABIN_VOLUME_IDLE = 0.0     # cabin noise at CABIN_START_SPEED
    CABIN_VOLUME_SPEED = 0.6    # added at TOP_SPEED, proportional to the speed above CABIN_START_SPEED
    CABIN_PITCH_MIN = 0.95      # cabin noise playback speed at standstill
    CABIN_PITCH_MAX = 1.1       # cabin noise playback speed at TOP_SPEED
    MASTER_VOLUME = 1.0
    SYNTH_MOTOR = False         # True: synthesized motor (EVSoundEngine) when there is no ev_motor.wav

    def __init__(self):
        self.system = pyfmodex.System()
        self.system.init(maxchannels=32)
        self.motor_sound = self._load(MOTOR_FILE)
        self.road_sound = self._load(ROAD_FILE)
        self.cabin_sound = self._load(CABIN_FILE)
        # No motor loop: optionally fall back to the synthesized motor
        self.synth = None
        if self.motor_sound is None and self.SYNTH_MOTOR:
            from .EVSoundEngine import EVSoundEngine
            self.synth = EVSoundEngine()
        self.motor_ch = None
        self.road_ch = None
        self.cabin_ch = None
        self.is_running = False

    def _load(self, path):
        if not path.exists():
            return None
        return self.system.create_sound(str(path), mode=MODE.LOOP_NORMAL | MODE.CREATESAMPLE)

    @staticmethod
    def available():
        """True when at least one of the loop files exists."""
        return MOTOR_FILE.exists() or ROAD_FILE.exists() or CABIN_FILE.exists()

    def _play(self, sound):
        if sound is None:
            return None
        channel = self.system.play_sound(sound, paused=True)
        channel.volume = 0.0
        channel.paused = False
        return channel

    def start(self):
        self.motor_ch = self._play(self.motor_sound)
        self.road_ch = self._play(self.road_sound)
        self.cabin_ch = self._play(self.cabin_sound)
        if self.synth is not None:
            self.synth.start()
        self.is_running = True

    def update_params(self, speed_kmh, torque, road_roughness=0.01):
        """
        Args:
            speed_kmh (float): Current vehicle speed.
            torque (float): 1 while the throttle is pressed, 0 otherwise.
            road_roughness (float, optional): Passed on to the synthesized motor if it is used.
        """
        if not self.is_running:
            return
        ratio = min(max(speed_kmh, 0.0) / self.TOP_SPEED, 1.0)

        if self.motor_ch is not None:
            self.motor_ch.pitch = self.MOTOR_PITCH_MIN + ratio * (self.MOTOR_PITCH_MAX - self.MOTOR_PITCH_MIN)
            motor_volume = self.MOTOR_VOLUME_IDLE + ratio * self.MOTOR_VOLUME_SPEED + abs(torque) * self.MOTOR_VOLUME_THROTTLE
            self.motor_ch.volume = motor_volume * self.MASTER_VOLUME
        if self.synth is not None:
            self.synth.update_params(speed_kmh, torque, road_roughness)
            self.synth.system.update()

        if self.road_ch is not None:
            self.road_ch.volume = ratio * self.ROAD_VOLUME_MAX * self.MASTER_VOLUME

        if self.cabin_ch is not None:
            self.cabin_ch.pitch = self.CABIN_PITCH_MIN + ratio * (self.CABIN_PITCH_MAX - self.CABIN_PITCH_MIN)
            if speed_kmh <= self.CABIN_START_SPEED:
                self.cabin_ch.volume = 0.0
            else:
                cabin_ratio = min((speed_kmh - self.CABIN_START_SPEED) / (self.TOP_SPEED - self.CABIN_START_SPEED), 1.0)
                self.cabin_ch.volume = (self.CABIN_VOLUME_IDLE + cabin_ratio * self.CABIN_VOLUME_SPEED) * self.MASTER_VOLUME

    def set_paused(self, paused):
        """Pauses or resumes every loop (used while there is no vehicle)."""
        self.system.master_channel_group.paused = paused
        self.system.update()
        if self.synth is not None:
            self.synth.system.master_channel_group.paused = paused
            self.synth.system.update()

    def stop(self):
        if self.synth is not None:
            self.synth.stop()
        if self.system:
            self.system.release()
