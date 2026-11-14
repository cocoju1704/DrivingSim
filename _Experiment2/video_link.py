#!/usr/bin/env python

"""
The NDRT video on the glasses (mrbd-video, the Meta Ray-Ban Display player) in step with the
experiment: abc_experiment.py --video http://127.0.0.1:8080 (the mrbd-video server, usually on this
PC: python mrbd-video/server.py).

    block start   play {file, t}: the app opens the video itself if none is open, seeks to t (--video-start)
    SAGAT         freeze: paused and covered (the glasses show nothing), its buttons do nothing
    after 3-2-1   resume: uncovered, playing again if it was playing before
    TOR           alert: as freeze (paused, covered), no text on the glasses / phone: the request is on
                  the monitors (and no text on the HUD either), the same for every condition
    takeover      alert_off: nothing to take away, still covered and paused (manual driving to the end)
    block end     pause

The sound (glasses and phone conditions): played on this PC (its default output, the earphones) by
device_audio.DeviceAudio, in step with the device's reports; play carries mute (the device plays
muted: glasses app v17, phone app v3; an older app reports no "muted" and keeps its own sound, this
PC stays silent). --no-pc-sound / pc_sound=False: the device's own sound. The earphones not the
Windows default output at the block start (earphones_on, devices.json "earphones"): the device's own
sound too (the glasses' speakers, the phone's), not this PC's speakers.

Another condition's block (phone, HUD): the glasses app (v17) shows nothing for the whole block (its
display black from the play to the pause), as it gets every command with the block's condition;
the HUD condition needs a VideoLink for this too (abc_experiment: one in every condition with a
video server).

The commands go to the server (POST /api/control), which passes them to the glasses app over its
event stream, and to the phone app (mrbd-video/phone_app) in the phone condition: each command
carries "device" (the block's condition); the phone app does only those of "phone", the glasses
app all of them. The app reports back (POST /api/state): its position in the video, paused, frozen;
each command here logs what it reported last (state(): that device's report, the server keeps one
per device). Nothing here waits on the glasses: a
missing server or glasses only costs a warning.
"""

from __future__ import print_function

import json
import logging
import queue
import ssl
import threading
import time
import urllib.error
import urllib.request

TIMEOUT = 6.0   # s: through a phone hotspot the TLS handshake alone takes up to ~3 s
CONFIRM_S = 3.0   # s: the phone app's report of a command (it reports at once and every 2 s)
RETRY_S = 12.0    # s: a command sent again until an app got it (the phone: did it) for up to this long
SYNC_S = 2.0      # s: the glasses' sound (phone / HUD condition without earphones) checked against the picture
SYNC_MAX_S = 0.4  # s apart: sought
SEEK_LEAD_S = 0.3  # s: a seek lands this much later (the command's trip, the decoder)
# Cloudflare (https://video.cocoju.dev) answers urllib's default "Python-urllib/x.y" with 403 (error 1010)
HEADERS = {'User-Agent': 'drivingsim-video-link/1.0'}


def earphones_on():
    """(True / False / None, the default output's name): the Windows default output is the earphones
    (devices.json "earphones", part of their name; preflight.check_audio). None: not known (no name
    there, or Windows not read): the sound stays on this PC as before."""
    import os  # pylint: disable=import-outside-toplevel
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(here, 'devices.json'), encoding='utf-8') as handle:
            wanted = (json.load(handle).get('earphones') or '').strip().lower()
    except (OSError, ValueError):
        wanted = ''
    if not wanted:
        return None, ''
    try:
        import sys  # pylint: disable=import-outside-toplevel
        sys.path.insert(0, here)
        from preflight import audio_outputs  # pylint: disable=import-outside-toplevel
        default, _ = audio_outputs()
    except Exception as error:  # pylint: disable=broad-except
        logging.warning('Sound output not read (%s): the video sound stays on this PC', error)
        return None, ''
    return bool(default) and wanted in default.lower(), default or 'none'


class VideoLink(object):
    def __init__(self, address, video_file=None, start_s=0.0, device='glasses', resume=True, pc_sound=True,
                 glasses_sound=False, master=None):
        address = address.strip().rstrip('/')
        if not address.startswith(('http://', 'https://')):
            address = 'http://' + address
        if address.startswith('http://') and address.count(':') < 2:  # no port: the server's default
            address += ':8080'
        self.base = address
        self._file = video_file
        self._start = start_s
        self._resume = resume   # start_s 0: from where it was left (False: from the start, the set's clip)
        self.device = 'phone' if device == 'phone' else 'glasses'   # whose report state() reads
        self._condition = device
        self._context = ssl._create_unverified_context()  # pylint: disable=protected-access  (own certificate)
        self.results = queue.Queue()  # (time.time(), command, delivered, glasses state): the experiment logs them
        self._jobs = queue.Queue()     # one worker: the commands arrive in order
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()
        self.audio = None   # the video's sound on this PC (device_audio), glasses / phone condition
        self._pc_sound = pc_sound and device in ('glasses', 'phone')   # made at the first start()
        # 2026-11-14: no earphones on the PC, phone / HUD condition: the glasses play the video's sound under
        # their black screen (app v18, play {sound}); the phone plays muted. Kept with the picture: master
        # (HUD: the HudVideo; phone: None = the phone's reports), a seek to the glasses alone when apart
        self.glasses_sound = bool(glasses_sound) and device in ('phone', 'hud')
        self._master = master
        self._sync = None
        if self.glasses_sound:
            self._pc_sound = False

    def _post(self, path, data, tries=3):
        """POST JSON; tried again (up to tries) on a failure: through the tunnel a request now and then
        comes back 400 (its body cut) or 5xx, and the next one goes through."""
        body = json.dumps(data).encode('utf-8')
        for attempt in range(tries):
            request = urllib.request.Request(self.base + path, data=body, method='POST',
                                             headers=dict(HEADERS, **{'Content-Type': 'application/json'}))
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT, context=self._context) as response:
                    return json.loads(response.read().decode('utf-8') or '{}')
            except urllib.error.HTTPError as error:
                if error.code not in (400, 408, 429, 500, 502, 503, 504) or attempt == tries - 1:
                    raise
            except OSError:
                if attempt == tries - 1:
                    raise
            time.sleep(0.2)

    def calib_now(self, dot, text=None):
        """The glasses app's calibration layer (calib.js): dot 'c' / 'tl' ... / 'px:X,Y' (600x600 px),
        'blank' (black, i.e. see-through, over the menu), 'off'; text: a line of guidance on it.
        Sent at once (calib() below queues it for the experiment's worker); returns how many apps got
        it. Raises when the server is not reached."""
        data = {'action': 'calib', 'dot': dot}
        if text:
            data['text'] = text
        return self._post('/api/control', data).get('delivered', 0)

    def app_version(self, tries=4):
        """The glasses app's version (APP_VERSION) from its last report, 0 if none or older than v9
        (tried again: through the hotspot a request now and then gets no answer)."""
        for attempt in range(tries):
            state = self.state()
            # a server older than the phone app keeps one report for all: the phone's (its own
            # version) is not the glasses'
            if state.get('received_ts') and state.get('device', self.device) == self.device:
                return int(state.get('v') or 0)
            time.sleep(0.5)
        return 0

    def state(self):
        """The glasses' last report (position t in s, paused, frozen, title), {} if none."""
        try:
            request = urllib.request.Request(self.base + '/api/state?device=' + self.device, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=self._context) as response:
                return json.loads(response.read().decode('utf-8') or '{}')
        except (OSError, ValueError, urllib.error.URLError):
            return {}

    def _send(self, action, **fields):
        fields['device'] = self._condition
        self._jobs.put((action, fields))

    @staticmethod
    def _applied(action, fields, state):
        """Whether the phone app's report shows the command done (its 2 s status reports overwrite the
        command's own, so the state is looked at, not the action)."""
        if action == 'play':
            return state.get('screen') == 'player' and (not fields.get('file') or state.get('title') == fields['file'])
        if action == 'freeze':
            return bool(state.get('frozen'))
        if action == 'resume':
            return not state.get('frozen')
        if action == 'pause':
            return state.get('screen') != 'player' or state.get('paused') is True
        return True   # alert_off, seek, calib: nothing to see

    def _send_once(self, action, fields):
        """POST the command; delivered (the number of apps on the event stream), None if not sent."""
        try:
            return self._post('/api/control', dict(fields, action=action)).get('delivered', 0)
        except (OSError, ValueError, urllib.error.URLError) as error:
            logging.warning('Video: "%s" not sent to %s (%s)', action, self.base, error)
            return None

    def _run(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            action, fields = job
            # The server passes a command only to the apps on its event stream at that moment: the
            # phone app's stream drops now and then (through the tunnel) and the command is lost.
            # So it is sent again until it reaches an app and, in the phone condition, until the
            # phone's report (every 2 s) shows it done; up to RETRY_S.
            first = time.time()
            tries = 0
            while True:
                tries += 1
                sent = time.time()
                delivered = self._send_once(action, fields)
                state = {}
                if delivered:
                    if self.device != 'phone':
                        time.sleep(0.4)  # the glasses' report of what it did
                        state = self.state()
                        break
                    done = False
                    while time.time() - sent < CONFIRM_S:
                        time.sleep(0.3)
                        state = self.state()
                        # a report received after this command was sent (server clock only)
                        age = (state.get('server_ts', 0) - state.get('received_ts', 0)) / 1000.0
                        if state.get('received_ts') and age <= time.time() - sent and self._applied(action, fields, state):
                            done = True
                            break
                    if done:
                        break
                if time.time() - first > RETRY_S:
                    if delivered == 0:
                        logging.warning('Video: "%s" reached the server, but no %s app is connected to it', action, self.device)
                    elif delivered:
                        logging.warning('Video: "%s" sent %d times, the %s app did not report it done', action, tries, self.device)
                    break
                if delivered is None:
                    break   # the server itself not reached: warned already
                time.sleep(0.5)
            if tries > 1:
                logging.info('Video: "%s" sent %d times', action, tries)
            self.results.put((time.time(), action, delivered, state))

    def close(self, wait=3.0):
        self._sync = None
        if self.audio is not None:
            self.audio.close()
        self._jobs.put(None)
        self._worker.join(wait)

    def start(self):
        """play with the video's name and start: the app (v13+) opens it itself when no video is open
        (its home screen) or another one is (--video-file; without it the one last saved on the
        glasses), then seeks to t."""
        fields = {}
        if self._file:
            fields['file'] = self._file
        if self._start > 0:
            fields['t'] = self._start
        elif not self._resume:
            fields['restart'] = True   # from the start: the phone app v2+, the glasses app v15+
        if self._pc_sound and self.audio is None:
            self._pc_sound = False
            on, output = earphones_on()
            if on is False:
                # 2026-11-14: no earphones on this PC: the device keeps its own sound (the glasses' speakers;
                # the phone's), not this PC's speakers
                logging.warning('Earphones not the default output (%s): the %s plays the video sound itself',
                                output, self.device)
            else:
                self._pc_sound = True
        if self._pc_sound and self.audio is None:
            self._pc_sound = False
            try:
                from device_audio import DeviceAudio
                self.audio = DeviceAudio(self.base, self.device, HEADERS, self._file, self.results)
                if not self.audio.ok:
                    self.audio = None
            except Exception as error:  # pylint: disable=broad-except
                logging.warning('Video sound on this PC: none (%s): the device plays it', error)
                self.audio = None
        if self.audio is not None:
            fields['mute'] = True      # the sound on this PC: the glasses app v17+, the phone app v3+
            self.audio.follow()
        if self.glasses_sound:
            fields['sound'] = True     # the glasses app v18: the video's sound under its black screen
            if self._condition == 'phone':
                fields['mute'] = True  # the phone silent (the glasses ignore mute in sound-only)
            logging.info('Video sound: the glasses (no earphones on this PC), %s condition', self._condition)
            if self._sync is None:
                self._sync = threading.Thread(target=self._follow, daemon=True)
                self._sync.start()
        self._send('play', **fields)

    def _position(self, device):
        """(t now, playing) of a device from its last report (t moved on by the report's age), or None."""
        try:
            request = urllib.request.Request(self.base + '/api/state?device=' + device, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=self._context) as response:
                s = json.loads(response.read().decode('utf-8') or '{}')
        except (OSError, ValueError, urllib.error.URLError):
            return None
        if s.get('t') is None or not s.get('received_ts') or not s.get('server_ts'):
            return None
        playing = s.get('paused') is False and not s.get('frozen')
        age = max(0.0, (s['server_ts'] - s['received_ts']) / 1000.0)
        if age > 6.0:
            return None
        return s['t'] + (age if playing else 0.0), playing

    def _follow(self):
        """The glasses' sound kept with the picture (HUD / phone): every SYNC_S, a seek to the glasses
        alone (device glasses: the phone app ignores it) when they are SYNC_MAX_S apart, both playing."""
        while self._sync is not None:
            time.sleep(SYNC_S)
            if self._master is not None:
                master = self._master.sync_position()
            else:
                master = self._position('phone')
            glasses = self._position('glasses')
            if not master or not glasses or not master[1] or not glasses[1]:
                continue
            apart = glasses[0] - master[0]
            if abs(apart) > SYNC_MAX_S and self._jobs.empty():   # not behind other commands (they come first)
                t = round(master[0] + SEEK_LEAD_S, 2)
                self._jobs.put(('seek', {'t': t, 'device': 'glasses'}))
                logging.info('Video sound: the glasses %.2f s %s the picture, sought to %.2f s', abs(apart),
                             'ahead of' if apart > 0 else 'behind', t)

    def pause(self, qid=''):
        if self.audio is not None:
            self.audio.hold()
        self._send('freeze', id=qid)

    def resume(self, qid=''):
        if self.audio is not None:
            self.audio.follow()
        self._send('resume', id=qid)

    def alert(self, eid='', text=''):
        """The TOR: the video stops and is hidden (as at a question), but no message on the glasses:
        the takeover request is on the monitors (above the cluster, and in the HUD condition the HUD),
        the same for every condition. text is kept for the log only."""
        if self.audio is not None:
            self.audio.hold()
        self._send('freeze', id=eid)

    def alert_off(self, eid=''):
        self._send('alert_off', id=eid)

    def calib(self, dot):
        """Gaze calibration (g2_calibrate.py): one dot on a black screen, c / tl / tr / br / bl, 'off'."""
        self._send('calib', dot=dot)

    def blank(self, on=True):
        """The glasses app's display all black (v17), or back (on False); the block's other commands
        do this by themselves outside the glasses condition (see above)."""
        self._send('blank', on=bool(on))

    def stop(self):
        if self.audio is not None:
            self.audio.stop()
        self._send('pause')
