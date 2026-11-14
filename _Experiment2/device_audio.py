#!/usr/bin/env python

"""
The sound of the NDRT video in the glasses and phone conditions, played on this PC (Windows' default
output: the participant's wireless earphones), in step with the picture on the device: the device
plays muted (video_link's play {mute}: glasses app v17, phone app v3) and reports its position t
every 2 s and after each command (/api/state); this follows those reports.

    VideoLink.start()    follow(): from the next report that shows the device playing (and muted)
    pause / alert        hold(): silent at once (the device stops too); a report made before this
                         moment does not start it again
    resume               follow() again: the sound starts when a report shows the device playing
    stop / close         stop()

Each report gives the device's position at the server's clock: t + (server_ts - received_ts) while
playing, taken at the middle of this PC's request (a kept-alive connection: the round trip is short).
The sound plays from that position + LEAD_S (the report's own trip to the server and the earphones'
Bluetooth delay both make the sound late). Then each new report is compared with where the sound is:
the largest difference of the last few reports (a report's trip only makes the device look behind),
past RESYNC_S, starts the sound again at the right place. No report for STALE_S, a paused / covered /
unmuted device (an old app, or a play without mute: the device has the sound) or another video:
silent.

Decoding: ffmpeg (imageio-ffmpeg) as hud_video.py, the sound in 0.2 s pieces on pygame.mixer's
channel 0 (reserved; the TOR sounds take the others). The HUD condition does not use this (hud_video
plays its own sound).
"""

from __future__ import print_function

import http.client
import json
import logging
import ssl
import subprocess
import threading
import time
import urllib.parse

from hud_video import AUDIO_CHUNK_S, NO_WINDOW, ffmpeg_exe, find_video

LEAD_S = 0.2        # s ahead of the device's reported position (report trip + Bluetooth, about 0.1 + 0.1-0.2)
RESYNC_S = 0.3      # s: the sound started again when it is further off the device than this
JUMP_S = 1.5        # s: one report this far off (a seek, a stall) is enough
WINDOW = 3          # reports compared (the largest difference of these, see above)
STALE_S = 6.0       # s without a new report: silent (the device reports every 2 s)
POLL_S = 0.5        # s between requests for the report
FAST_POLL_S = 0.2   # ... for FAST_S after start / resume (the sound starts soon after the picture)
FAST_S = 4.0
VOLUME = 1.0


class DeviceAudio(object):
    def __init__(self, base, device, headers, video_file=None, results=None):
        """base: the mrbd-video server (http(s)://host:port), device: whose report ('glasses' / 'phone'),
        results: VideoLink.results (a queue: what the sound did goes into the experiment's events)."""
        self.base = base
        self.device = device
        self._headers = headers
        self._file = video_file
        self._results = results
        self._lock = threading.Lock()
        self._following = False
        self._after = None          # server ms: reports received before this are not followed
        self._fast_until = 0.0
        self._offset_ms = None      # server clock - this PC's (ms), from the last request
        self._conn = None
        self._gen = 0               # the decoder's generation: a hold / a new start ends the old one
        self._proc = None
        self._playing = False       # the sound playing (or starting)
        self._pos = 0.0             # s in the video at _since (time.monotonic())
        self._since = 0.0
        self._diffs = []            # (received_ts, sound - device - LEAD_S) of the last reports
        self._last_received = None
        self._path = None
        self._title = None
        self._missing = set()
        self._alive = True
        self._channel = None
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2)
            pygame.mixer.set_reserved(1)   # channel 0: this sound; the alert sounds take the others
            self._channel = pygame.mixer.Channel(0)
            self._channel.set_volume(VOLUME)
            self._rate, _, self._channels = pygame.mixer.get_init()
        except Exception as error:  # pylint: disable=broad-except
            logging.warning('Video sound on this PC: none (%s)', error)
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def ok(self):
        return self._channel is not None

    # -- the experiment's side (VideoLink) ---------------------------------------------------

    def _server_now(self):
        return None if self._offset_ms is None else time.time() * 1000.0 + self._offset_ms

    def follow(self):
        """Start / resume: play when a report made from now on shows the device playing."""
        with self._lock:
            self._following = True
            self._after = self._server_now()
            self._fast_until = time.monotonic() + FAST_S
            self._diffs = []

    def hold(self):
        """A question / the TOR: silent at once."""
        with self._lock:
            self._following = False
            self._after = self._server_now()
            self._silence('hold')

    def stop(self):
        with self._lock:
            self._following = False
            self._silence('stop')

    def close(self):
        self.stop()
        self._alive = False

    # -- the sound ---------------------------------------------------------------------------

    def position(self):
        return self._pos + time.monotonic() - self._since if self._playing else None

    def _log(self, action, t=None, note=''):
        state = {'id': '', 'device': 'pc', 't': None if t is None else round(t, 3), 'title': self._title or ''}
        if note:
            logging.info('Video sound on this PC: %s at %s s (%s)', action, state['t'], note)
        if self._results is not None:
            self._results.put((time.time(), action, 1, state))

    def _silence(self, why, log=True):
        """Ends the decoder and the sound (with the lock held)."""
        was = self._playing
        self._gen += 1
        self._playing = False
        self._diffs = []
        if self._proc is not None:
            try:
                self._proc.kill()
            except OSError:
                pass
            self._proc = None
        if self._channel is not None:
            try:
                self._channel.stop()
            except Exception:  # pylint: disable=broad-except
                pass
        if was and log:
            self._log('pc_sound_stop', None, why)

    def _start(self, pos, why):
        """The sound from pos s (with the lock held): ffmpeg starts at pos; the time it takes to
        start is cut off the front of its first piece, so the sound is at pos + the time since now."""
        self._silence(why, log=False)
        self._gen += 1
        gen = self._gen
        self._playing = True
        self._pos, self._since = max(pos, 0.0), time.monotonic()
        threading.Thread(target=self._decode, args=(gen, self._pos, self._since, self._path), daemon=True).start()
        self._log('pc_sound_start' if why == 'start' else 'pc_sound_resync', self._pos, why)

    def _decode(self, gen, pos, since, path):
        import pygame
        command = [ffmpeg_exe(), '-nostdin', '-loglevel', 'error', '-ss', '%.3f' % pos, '-i', path,
                   '-vn', '-f', 's16le', '-acodec', 'pcm_s16le', '-ac', str(self._channels), '-ar', str(self._rate), '-']
        with self._lock:
            if gen != self._gen:
                return
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            self._proc = proc
        frame = 2 * self._channels
        chunk = int(self._rate * AUDIO_CHUNK_S) * frame
        first = True
        try:
            while gen == self._gen:
                data = proc.stdout.read(chunk)
                if not data:
                    return
                if first:
                    # ffmpeg's start: the sound is already this far on
                    skip = int((time.monotonic() - since) * self._rate) * frame
                    while gen == self._gen and len(data) <= skip:
                        skip -= len(data)
                        data = proc.stdout.read(chunk)
                        if not data:
                            return
                    data = data[skip:]
                    with self._lock:
                        if gen != self._gen:
                            return
                        self._channel.play(pygame.mixer.Sound(buffer=data))
                    first = False
                    continue
                sound = pygame.mixer.Sound(buffer=data)
                while gen == self._gen and self._channel.get_queue() is not None:
                    time.sleep(0.02)
                with self._lock:
                    if gen != self._gen:
                        return
                    if not self._channel.get_busy():
                        self._channel.play(sound)
                    else:
                        self._channel.queue(sound)
        except Exception as error:  # pylint: disable=broad-except
            if gen == self._gen:
                logging.warning('Video sound on this PC: %s', error)

    # -- the device's reports ----------------------------------------------------------------

    def _request(self):
        """The device's last report and the PC time (time.monotonic()) its server_ts stands for, or
        (None, None). One kept-alive connection (no TLS handshake for each request)."""
        url = urllib.parse.urlsplit(self.base)
        for attempt in range(2):
            try:
                if self._conn is None:
                    if url.scheme == 'https':
                        self._conn = http.client.HTTPSConnection(
                            url.hostname, url.port or 443, timeout=4.0,
                            context=ssl._create_unverified_context())  # pylint: disable=protected-access
                    else:
                        self._conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=4.0)
                    self._conn.connect()
                t0, w0 = time.monotonic(), time.time()
                self._conn.request('GET', '/api/state?device=' + self.device, headers=self._headers)
                response = self._conn.getresponse()
                body = response.read()
                t1, w1 = time.monotonic(), time.time()
                if response.status != 200:
                    raise OSError('HTTP %d' % response.status)
                state = json.loads(body.decode('utf-8') or '{}')
                if state.get('server_ts'):
                    self._offset_ms = state['server_ts'] - (w0 + w1) * 500.0
                return state, (t0 + t1) / 2.0
            except (OSError, ValueError, http.client.HTTPException):
                try:
                    self._conn.close()
                except Exception:  # pylint: disable=broad-except
                    pass
                self._conn = None
                if attempt:
                    return None, None
        return None, None

    def _video_path(self, title):
        """The sound's file: the block's video (--video-file), else the one the device shows."""
        name = self._file or title
        if not name:
            return None
        if name != self._title:
            self._title = name
            self._path = find_video(name)
            if self._path is None and name not in self._missing:
                self._missing.add(name)
                logging.warning('Video sound on this PC: %s not found in mrbd-video/media: no sound', name)
        return self._path

    def _run(self):
        while self._alive:
            fast = time.monotonic() < self._fast_until
            time.sleep(FAST_POLL_S if fast else POLL_S)
            if not self._following:
                if self._offset_ms is None:
                    self._request()   # the server's clock, before the first command
                continue
            state, at = self._request()
            with self._lock:
                if not self._following:
                    continue
                self._step(state, at)

    def _step(self, state, at):
        """One report (with the lock held)."""
        if not state or not state.get('received_ts'):
            if self._playing and self._last_received is not None and \
                    self._server_now() is not None and self._server_now() - self._last_received > STALE_S * 1000:
                self._silence('no report for %.0f s' % STALE_S)
            return
        received = state['received_ts']
        age = (state.get('server_ts', received) - received) / 1000.0
        if age > STALE_S:
            if self._playing:
                self._silence('no report for %.0f s' % age)
            return
        if self._after is not None and received <= self._after:
            return   # made before the last command: what it shows may be over
        title = state.get('title') or ''
        if (self._file and title and title != self._file) or state.get('screen') != 'player' or \
                state.get('t') is None or state.get('paused') or state.get('frozen') or state.get('blank'):
            if self._playing:
                self._silence('device %s' % ('paused' if state.get('paused') else 'covered' if state.get('frozen')
                                              else 'not playing ' + (self._file or '')))
            return
        if state.get('muted') is not True:
            if self._playing:
                self._silence('device not muted: its own sound')
            return
        path = self._video_path(title)
        if path is None:
            return
        device_now = float(state['t']) + age + (time.monotonic() - at)   # its position now (at least)
        if not self._playing:
            self._start(device_now + LEAD_S, 'start')
            self._last_received = received
            return
        if received == self._last_received:
            return
        self._last_received = received
        diff = (device_now + LEAD_S) - self.position()   # > 0: the sound behind
        self._diffs = (self._diffs + [diff])[-WINDOW:]
        best = max(self._diffs)
        if abs(diff) > JUMP_S or (len(self._diffs) >= 2 and abs(best) > RESYNC_S):
            self._start(self.position() + (diff if abs(diff) > JUMP_S else best),
                        'off the device by %+.2f s' % (diff if abs(diff) > JUMP_S else best))
