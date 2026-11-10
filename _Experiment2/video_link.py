#!/usr/bin/env python

"""
The NDRT video on the glasses (mrbd-video, the Meta Ray-Ban Display player) in step with the
experiment: abc_experiment.py --video http://127.0.0.1:8080 (the mrbd-video server, usually on this
PC: python mrbd-video/server.py).

    block start   seek (--video-start, if > 0), play
    SAGAT         freeze: paused and covered (the glasses show nothing), its buttons do nothing
    after 3-2-1   resume: uncovered, playing again if it was playing before
    TOR           alert: paused, covered, "지금 직접 운전하세요" in red on it
    takeover      alert_off: the text goes, still covered and paused (manual driving to the end)
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

TIMEOUT = 2.0
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

    def _post(self, path, data):
        request = urllib.request.Request(self.base + path, data=json.dumps(data).encode('utf-8'), method='POST',
                                         headers=dict(HEADERS, **{'Content-Type': 'application/json'}))
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=self._context) as response:
            return json.loads(response.read().decode('utf-8') or '{}')

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
        if self._start > 0:
            self._send('seek', t=self._start)
        self._send('play')

    def pause(self, qid=''):
        self._send('freeze', id=qid)

    def resume(self, qid=''):
        self._send('resume', id=qid)

    def alert(self, eid='', text=''):
        self._send('alert', id=eid, text=text)

    def alert_off(self, eid=''):
        self._send('alert_off', id=eid)

    def stop(self):
        self._send('pause')
