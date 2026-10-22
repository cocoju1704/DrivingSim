import os

from ..Banks.config import FMOD_CORE_DLL, FMOD_STUDIO_DLL, SOUNDS_DIR
os.environ["PYFMODEX_DLL_PATH"] = FMOD_CORE_DLL
os.environ["PYFMODEX_STUDIO_DLL_PATH"] = FMOD_STUDIO_DLL

import pyfmodex
from pyfmodex.enums import TIMEUNIT
from pyfmodex.flags import MODE

#: Motor/drive loop. Its pitch and volume follow the throttle (and a little the speed). Made
#: from ev_drive.mp3: its steady stretch, crossfaded into a loop.
MOTOR_FILE = SOUNDS_DIR / "ev_motor.wav"
#: Tire/road noise loop. Its volume follows the speed.
ROAD_FILE = SOUNDS_DIR / "ev_road.wav"
#: Interior cabin noise loop (HVAC hum, muffled wind/road). Louder with speed up to CABIN_FULL_SPEED.
CABIN_FILE = SOUNDS_DIR / "ev_cabin.wav"
#: Turn signal ticking, 10 tick-tock periods with the first tick at the start; plays while a turn
#: signal is on. Made from the recording ev_blinker.wav (louder, the hiss between ticks gated).
BLINKER_FILE = SOUNDS_DIR / "ev_blinker_loop.wav"
#: Reverse warning sound; plays while in reverse. Made from ev_reverse.mp3: cut where the sound
#: repeats its start, so it loops seamlessly.
REVERSE_FILE = SOUNDS_DIR / "ev_reverse_loop.wav"


class EVSampleEngine:
    """
    Sample-based Electric Vehicle (EV) sound: recorded loops instead of oscillators.

    Drop-in replacement for :class:`EVSoundEngine` (same start / update_params / stop
    interface). Put seamless loops in the top-level ``Sounds`` folder; each one is optional:

    - ``ev_motor.wav``: motor sound, played back faster (higher) with speed, heard only under throttle.
      Without it, the synthesized motor of :class:`EVSoundEngine` is used if SYNTH_MOTOR is True.
    - ``ev_road.wav``: tire/road rumble, louder with speed.
    - ``ev_cabin.wav``: interior cabin noise, audible from standstill, louder with speed up to CABIN_FULL_SPEED.
    - ``ev_blinker_loop.wav``: turn signal ticking (set_blinker).
    - ``ev_reverse_loop.wav``: reverse warning sound (set_reverse).

    Tune the class constants below to change how the sound reacts.
    """
    TOP_SPEED = 120.0           # km/h at which pitch and volume reach their maximum
    MOTOR_PITCH_MIN = 0.5       # playback speed released at standstill (1.0 = as recorded)
    MOTOR_PITCH_MAX = 1.8       # playback speed at full throttle and TOP_SPEED
    MOTOR_PITCH_SPEED = 0.3     # share of the pitch range that follows the speed; the rest follows the throttle
    MOTOR_PITCH_GLIDE = 0.15    # share of the way to the new throttle pitch per update: it rises, not jumps
    # The motor gets louder the more the throttle is pressed: full throttle gives MOTOR_VOLUME_LOW
    # at standstill up to MOTOR_VOLUME_HIGH at TOP_SPEED. Released, it fades down to
    # MOTOR_VOLUME_RELEASED of that, never quite silent (0: silent).
    MOTOR_VOLUME_LOW = 0.3
    MOTOR_VOLUME_HIGH = 0.65
    MOTOR_VOLUME_RELEASED = 0.15
    MOTOR_FADE = 0.3            # share of the way to the new volume per update (20 per second): no clicks
    BLINKER_VOLUME = 0.6
    REVERSE_VOLUME = 0.6
    ROAD_VOLUME_MAX = 0.6       # road noise at TOP_SPEED
    CABIN_FULL_SPEED = 50.0     # km/h at which the cabin noise reaches CABIN_VOLUME_MAX
    CABIN_VOLUME_IDLE = 0.1     # cabin noise at standstill
    CABIN_VOLUME_MAX = 0.6      # cabin noise at CABIN_FULL_SPEED and above
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
        self.blinker_sound = self._load(BLINKER_FILE)
        self.blinker_ch = None
        self.reverse_sound = self._load(REVERSE_FILE)
        self.reverse_ch = None
        self.motor_volume = 0.0
        self.motor_throttle = 0.0   # the throttle the pitch follows, glided
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
        return any(path.exists() for path in (MOTOR_FILE, ROAD_FILE, CABIN_FILE, BLINKER_FILE, REVERSE_FILE))

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
        self.blinker_ch = self._held(self.blinker_sound, self.BLINKER_VOLUME)
        self.reverse_ch = self._held(self.reverse_sound, self.REVERSE_VOLUME)
        if self.synth is not None:
            self.synth.start()
        self.is_running = True

    def _held(self, sound, volume):
        """A loop that waits, paused, until _switch starts it."""
        if sound is None:
            return None
        channel = self.system.play_sound(sound, paused=True)
        channel.volume = volume * self.MASTER_VOLUME
        return channel

    def _switch(self, channel, on):
        """Start a held loop from its beginning, or stop it."""
        if channel is None:
            return
        if on:
            channel.set_position(0, TIMEUNIT.PCM)
        channel.paused = not on
        self.system.update()

    def set_blinker(self, on):
        """Turn signal ticking on (from the first tick, like a real relay) or off."""
        self._switch(self.blinker_ch, on)

    def set_reverse(self, on):
        """Reverse warning sound on or off."""
        self._switch(self.reverse_ch, on)

    def update_params(self, speed_kmh, torque, road_roughness=0.01):
        """
        Args:
            speed_kmh (float): Current vehicle speed.
            torque (float): Throttle, 0..1.
            road_roughness (float, optional): Passed on to the synthesized motor if it is used.
        """
        if not self.is_running:
            return
        ratio = min(max(speed_kmh, 0.0) / self.TOP_SPEED, 1.0)

        if self.motor_ch is not None:
            self.motor_throttle += self.MOTOR_PITCH_GLIDE * (min(abs(torque), 1.0) - self.motor_throttle)
            rise = self.MOTOR_PITCH_SPEED * ratio + (1.0 - self.MOTOR_PITCH_SPEED) * self.motor_throttle
            self.motor_ch.pitch = self.MOTOR_PITCH_MIN + rise * (self.MOTOR_PITCH_MAX - self.MOTOR_PITCH_MIN)
            share = self.MOTOR_VOLUME_RELEASED + (1.0 - self.MOTOR_VOLUME_RELEASED) * min(abs(torque), 1.0)
            target = share * (self.MOTOR_VOLUME_LOW + ratio * (self.MOTOR_VOLUME_HIGH - self.MOTOR_VOLUME_LOW))
            self.motor_volume += self.MOTOR_FADE * (target - self.motor_volume)
            self.motor_ch.volume = self.motor_volume * self.MASTER_VOLUME
        if self.synth is not None:
            self.synth.update_params(speed_kmh, torque, road_roughness)
            self.synth.system.update()

        if self.road_ch is not None:
            self.road_ch.volume = ratio * self.ROAD_VOLUME_MAX * self.MASTER_VOLUME

        if self.cabin_ch is not None:
            self.cabin_ch.pitch = self.CABIN_PITCH_MIN + ratio * (self.CABIN_PITCH_MAX - self.CABIN_PITCH_MIN)
            cabin_ratio = min(max(speed_kmh, 0.0) / self.CABIN_FULL_SPEED, 1.0)
            cabin_volume = self.CABIN_VOLUME_IDLE + cabin_ratio * (self.CABIN_VOLUME_MAX - self.CABIN_VOLUME_IDLE)
            self.cabin_ch.volume = cabin_volume * self.MASTER_VOLUME

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
