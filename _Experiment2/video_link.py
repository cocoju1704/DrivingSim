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
event stream. The app reports back (POST /api/state): its position in the video, paused, frozen;
each command here logs what it reported last (state()). Nothing here waits on the glasses: a
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
# Cloudflare (https://video.cocoju.dev) answers urllib's default "Python-urllib/x.y" with 403 (error 1010)
HEADERS = {'User-Agent': 'drivingsim-video-link/1.0'}


class VideoLink(object):
    def __init__(self, address, video_file=None, start_s=0.0):
        address = address.strip().rstrip('/')
        if not address.startswith(('http://', 'https://')):
            address = 'http://' + address
        if address.startswith('http://') and address.count(':') < 2:  # no port: the server's default
            address += ':8080'
        self.base = address
        self._file = video_file
        self._start = start_s
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
            if state.get('received_ts'):
                return int(state.get('v') or 0)
            time.sleep(0.5)
        return 0

    def state(self):
        """The glasses' last report (position t in s, paused, frozen, title), {} if none."""
        try:
            request = urllib.request.Request(self.base + '/api/state', headers=HEADERS)
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=self._context) as response:
                return json.loads(response.read().decode('utf-8') or '{}')
        except (OSError, ValueError, urllib.error.URLError):
            return {}

    def _send(self, action, **fields):
        self._jobs.put((action, fields))

    def _run(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            action, fields = job
            try:
                result = self._post('/api/control', dict(fields, action=action))
                delivered = result.get('delivered', 0)
                if not delivered:
                    logging.warning('Video: "%s" reached the server, but no glasses are connected to it', action)
            except (OSError, ValueError, urllib.error.URLError) as error:
                logging.warning('Video: "%s" not sent to %s (%s)', action, self.base, error)
                delivered = None
            time.sleep(0.4)  # the glasses' report of what it did
            self.results.put((time.time(), action, delivered, self.state() if delivered else {}))

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
