#!/usr/bin/env python

"""
The NDRT video on the glasses (mrbd-video, the Meta Ray-Ban Display player) in step with the
experiment: abc_experiment.py --video http://127.0.0.1:8080 (the mrbd-video server, usually on this
PC: python mrbd-video/server.py).

    block start   play {file, t}: the app opens the video itself if none is open, seeks to t (--video-start)
    SAGAT         freeze: paused and covered (the glasses show nothing), its buttons do nothing
    after 3-2-1   resume: uncovered, playing again if it was playing before
    TOR           alert: as freeze (paused, covered), no text on the glasses: the request is on the monitors
    takeover      alert_off: nothing to take away, still covered and paused (manual driving to the end)
    block end     pause

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
# Cloudflare (https://video.cocoju.dev) answers urllib's default "Python-urllib/x.y" with 403 (error 1010)
HEADERS = {'User-Agent': 'drivingsim-video-link/1.0'}


class VideoLink(object):
    def __init__(self, address, video_file=None, start_s=0.0, device='glasses'):
        address = address.strip().rstrip('/')
        if not address.startswith(('http://', 'https://')):
            address = 'http://' + address
        if address.startswith('http://') and address.count(':') < 2:  # no port: the server's default
            address += ':8080'
        self.base = address
        self._file = video_file
        self._start = start_s
        self.device = 'phone' if device == 'phone' else 'glasses'   # whose report state() reads
        self._condition = device
        self._context = ssl._create_unverified_context()  # pylint: disable=protected-access  (own certificate)
        self.results = queue.Queue()  # (time.time(), command, delivered, glasses state): the experiment logs them
        self._jobs = queue.Queue()     # one worker: the commands arrive in order
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

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
        self._send('play', **fields)

    def pause(self, qid=''):
        self._send('freeze', id=qid)

    def resume(self, qid=''):
        self._send('resume', id=qid)

    def alert(self, eid='', text=''):
        """The TOR: the video stops and is hidden (as at a question), but no message on the glasses:
        the takeover request is on the monitors (above the cluster, and in the HUD condition the HUD),
        the same for every condition. text is kept for the log only."""
        self._send('freeze', id=eid)

    def alert_off(self, eid=''):
        self._send('alert_off', id=eid)

    def calib(self, dot):
        """Gaze calibration (g2_calibrate.py): one dot on a black screen, c / tl / tr / br / bl, 'off'."""
        self._send('calib', dot=dot)

    def stop(self):
        self._send('pause')
