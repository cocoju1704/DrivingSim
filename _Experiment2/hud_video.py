#!/usr/bin/env python

"""
The NDRT video of the HUD condition, played by the experiment itself in the HUD area of the middle
monitor (abc_experiment.Overlay.hud_rect), with the same commands as the glasses / phone apps
(video_link.VideoLink):

    block start   play: the video (--video-file, else the one played last, else the first in
                  mrbd-video/), from --video-start, else from where it was left (hud_video.json; not
                  for a set's clip with NDRT video questions: from its start)
    SAGAT         freeze: paused, nothing on the HUD (as the glasses: their display shows nothing)
    after 3-2-1   resume: playing again if it was playing before
    TOR           alert: as freeze; alert_off: still paused (manual driving to the end)
    block end     pause

The HUD has the video's shape (16:9, abc_experiment.Overlay.HUD_ASPECT), so the video fills it
(a video of another shape: whole and centred, object-fit: contain). The sound plays on this PC (pygame.mixer, its
channel 0 reserved for it).

Decoding: ffmpeg (imageio-ffmpeg), one process for the frames (already scaled to the HUD's size,
30 fps) and one for the sound, both started again at the position after each pause.
"""

from __future__ import print_function

import json
import logging
import os
import queue
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIRS = [os.path.join(HERE, '..', 'mrbd-video', 'media'), os.path.join(HERE, '..', 'mrbd-video')]
SAVED = os.path.join(HERE, 'hud_video.json')   # {"last": name, "pos": {name: s}}
VIDEO_EXT = ('.mp4', '.m4v', '.webm', '.mov', '.mkv')
FPS = 30.0
AUDIO_CHUNK_S = 0.2
VOLUME = 1.0
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def find_video(name=None):
    """The path of the video name (a file name in mrbd-video/media or mrbd-video/, or a path); without
    a name the one played last, else the first in those folders. None if there is none."""
    if name:
        if os.path.isfile(name):
            return os.path.abspath(name)
        for folder in VIDEO_DIRS:
            path = os.path.join(folder, os.path.basename(name))
            if os.path.isfile(path):
                return os.path.abspath(path)
        return None
    last = load_saved().get('last')
    if last:
        path = find_video(last)
        if path:
            return path
    for folder in VIDEO_DIRS:
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.lower().endswith(VIDEO_EXT) and not f.startswith('.'):
                    return os.path.abspath(os.path.join(folder, f))
    return None


def load_saved():
    try:
        with open(SAVED, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def video_size(path):
    """(width, height, duration s) of the video."""
    import cv2
    capture = cv2.VideoCapture(path)
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS) or FPS
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    finally:
        capture.release()
    if width <= 0 or height <= 0:
        raise RuntimeError('cannot read %s' % path)
    return width, height, frames / fps if frames > 0 else 0.0


def contain(width, height, box_w, box_h):
    """The video's size in a box_w x box_h box, whole and centred (object-fit: contain), even px."""
    scale = min(box_w / float(width), box_h / float(height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


class HudVideo(object):
    device = 'hud'

    def __init__(self, video_file=None, start_s=0.0, resume=True, sound=True):
        self.results = queue.Queue()   # (time.time(), command, delivered, state): the experiment logs them
        self.path = find_video(video_file)
        self.title = os.path.basename(self.path) if self.path else (video_file or '')
        self._start = start_s
        self._resume = resume       # start_s 0: from where it was left (False: from 0, e.g. a clip with questions)
        self._lock = threading.Lock()
        self._gen = 0               # the decoders' generation: a pause or a new size ends the old ones
        self._procs = []
        self._playing = False
        self._frozen = False
        self._was_playing = None    # at a freeze / alert
        self._pos = 0.0             # s, while paused; while playing: at _since
        self._since = 0.0           # time.monotonic() when playing started from _pos
        self._side = None           # (width, height) px: the HUD's size (Overlay)
        self._frame = None          # (gen, index, bytes) the frame to show now
        self._surface = None        # (gen, index, pygame.Surface)
        self._size = None
        self._duration = 0.0
        self._channel = None
        if self.path is None:
            logging.warning('HUD video: %s not found in %s', video_file or 'no video',
                            ' / '.join(os.path.normpath(d) for d in VIDEO_DIRS))
            return
        try:
            self._width, self._height, self._duration = video_size(self.path)
        except Exception as error:  # pylint: disable=broad-except
            logging.warning('HUD video: %s', error)
            self.path = None
            return
        if sound:
            self._audio_init()
        else:   # 2026-11-14: no earphones on this PC: the glasses play the sound (video_link glasses_sound)
            logging.info('HUD video: no sound on this PC (the glasses play it)')
        logging.info('HUD video: %s (%dx%d, %.0f s)', self.path, self._width, self._height, self._duration)

    # -- sound --------------------------------------------------------------------------------

    def _audio_init(self):
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2)
            pygame.mixer.set_reserved(1)   # channel 0: this video; the alert sounds take the others
            self._channel = pygame.mixer.Channel(0)
            self._channel.set_volume(VOLUME)
            self._rate, _, self._channels = pygame.mixer.get_init()
        except Exception as error:  # pylint: disable=broad-except
            logging.warning('HUD video: no sound (%s)', error)
            self._channel = None

    def _audio(self, gen, pos):
        import pygame
        command = [ffmpeg_exe(), '-nostdin', '-loglevel', 'error', '-ss', '%.3f' % pos, '-i', self.path,
                   '-vn', '-f', 's16le', '-acodec', 'pcm_s16le', '-ac', str(self._channels), '-ar', str(self._rate), '-']
        proc = self._spawn(command, gen)
        if proc is None:
            return
        chunk = int(self._rate * AUDIO_CHUNK_S) * 2 * self._channels
        first = True
        try:
            while gen == self._gen:
                data = proc.stdout.read(chunk)
                if not data:
                    return
                sound = pygame.mixer.Sound(buffer=data)
                if first:
                    self._channel.play(sound)
                    first = False
                    continue
                while gen == self._gen and self._channel.get_queue() is not None:
                    time.sleep(0.02)
                if gen != self._gen:
                    return
                if not self._channel.get_busy():
                    self._channel.play(sound)
                else:
                    self._channel.queue(sound)
        except Exception as error:  # pylint: disable=broad-except
            if gen == self._gen:
                logging.warning('HUD video sound: %s', error)

    # -- frames -------------------------------------------------------------------------------

    def _spawn(self, command, gen):
        with self._lock:
            if gen != self._gen:
                return None
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            self._procs.append(proc)
            return proc

    def _video(self, gen, pos, since, size):
        width, height = size
        command = [ffmpeg_exe(), '-nostdin', '-loglevel', 'error', '-ss', '%.3f' % pos, '-i', self.path, '-an',
                   '-vf', 'fps=%g,scale=%d:%d:flags=area' % (FPS, width, height),
                   '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
        proc = self._spawn(command, gen)
        if proc is None:
            return
        n = width * height * 3
        index = 0
        try:
            while gen == self._gen:
                data = proc.stdout.read(n)
                if len(data) < n:
                    if gen == self._gen:   # the end of the video
                        self._ended(gen)
                    return
                due = since + index / FPS
                late = time.monotonic() - due
                if late < -0.002:
                    time.sleep(-late)
                if late < 1.0 / FPS or index == 0:
                    self._frame = (gen, index, data)
                index += 1
        except Exception as error:  # pylint: disable=broad-except
            if gen == self._gen:
                logging.warning('HUD video frames: %s', error)

    def _ended(self, gen):
        with self._lock:
            if gen != self._gen:
                return
        self._halt()
        self._pos = 0.0
        self._save()
        self.results.put((time.time(), 'ended', 1, self._state('')))

    def _kill(self):
        """Ends the decoders (with the lock held)."""
        self._gen += 1
        for proc in self._procs:
            try:
                proc.kill()
            except OSError:
                pass
        self._procs = []
        self._frame = None
        self._surface = None
        if self._channel is not None:
            try:
                self._channel.stop()
            except Exception:  # pylint: disable=broad-except
                pass

    def _launch(self):
        """Decoders from the position (with the lock held), when playing and the HUD's size is known."""
        self._kill()
        if not self._playing or not self._side or self.path is None:
            return
        self._size = contain(self._width, self._height, *self._side)
        gen = self._gen
        since = time.monotonic()
        self._pos, self._since = self.position(), since
        threading.Thread(target=self._video, args=(gen, self._pos, since, self._size), daemon=True).start()
        if self._channel is not None:
            threading.Thread(target=self._audio, args=(gen, self._pos), daemon=True).start()

    def position(self):
        if self._playing:
            return self._pos + time.monotonic() - self._since
        return self._pos

    def sync_position(self):
        """(t, playing) for video_link's glasses sound to follow."""
        if self.path is None:
            return None
        return self.position(), self._playing and not self._frozen

    def _play(self):
        with self._lock:
            self._playing = True
            self._since = time.monotonic()
            self._launch()

    def _halt(self):
        with self._lock:
            if self._playing:
                self._pos = self.position()
                self._playing = False
            self._kill()

    def _save(self):
        if self.path is None:
            return
        saved = load_saved()
        saved['last'] = self.title
        saved.setdefault('pos', {})[self.title] = round(self._pos, 2)
        try:
            with open(SAVED, 'w', encoding='utf-8') as f:
                json.dump(saved, f, ensure_ascii=False, indent=1)
        except OSError as error:
            logging.warning('HUD video: %s not saved (%s)', SAVED, error)

    def _state(self, qid):
        return {'id': qid, 'device': 'hud', 'screen': 'player' if self.path else 'none', 'title': self.title,
                't': round(self.position(), 3) if self.path else None, 'paused': not self._playing,
                'frozen': self._frozen}

    def _report(self, action, qid=''):
        self.results.put((time.time(), action, 1 if self.path else 0, self._state(qid)))

    # -- the overlay ------------------------------------------------------------------------

    def surface(self, width, height=None):
        """The frame to show in the HUD (width x height px; height None: a square), as (pygame.Surface,
        its offset in the HUD), or None (paused at a question / the TOR, no video, not started yet)."""
        side = (width, height or width)
        if side != self._side:
            with self._lock:
                self._side = side
                if self._playing:
                    self._launch()
        if self._frozen or self.path is None:
            return None
        frame = self._frame
        if frame is None:
            return None
        gen, index, data = frame
        if self._surface is None or self._surface[:2] != (gen, index):
            import pygame
            self._surface = (gen, index, pygame.image.frombuffer(data, self._size, 'RGB'))
        w, h = self._size
        return self._surface[2], ((side[0] - w) // 2, (side[1] - h) // 2)

    # -- the experiment's commands (as VideoLink) --------------------------------------------

    def start(self):
        if self.path is None:
            self._report('play')
            return
        saved = load_saved().get('pos', {}).get(self.title, 0.0)
        self._pos = self._start if self._start > 0 or not self._resume else saved
        if self._duration and self._pos >= self._duration - 1:
            self._pos = 0.0
        self._frozen = False
        self._was_playing = None
        self._play()
        self._save()
        self._report('play')

    def _hold(self, action, qid):
        if self._was_playing is None:
            self._was_playing = self._playing
        self._frozen = True
        self._halt()
        self._save()
        self._report(action, qid)

    def pause(self, qid=''):
        self._hold('freeze', qid)

    def alert(self, eid='', text=''):
        self._hold('freeze', eid)

    def alert_off(self, eid=''):
        self._report('alert_off', eid)

    def resume(self, qid=''):
        was = self._was_playing
        self._was_playing = None
        self._frozen = False
        if self.path is not None and (was is None or was):
            self._play()
        self._report('resume', qid)

    def stop(self):
        self._was_playing = None
        self._halt()
        self._save()
        self._report('pause')

    def close(self, wait=0.0):
        self._halt()
