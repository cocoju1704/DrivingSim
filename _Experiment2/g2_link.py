#!/usr/bin/env python

"""
Tobii Pro Glasses 2: the experiment's events as markers in the glasses' recording, over the
glasses' REST API (http://<recording unit>/api/...). The recording unit's address on its own
Wi-Fi is 192.168.71.50; on a cable it is reached by its IPv6 link-local name (see the Glasses 2
API guide).

Markers: POST /api/events {"type": "abc", "tag": "<json>"}. They land in the recording's
livedata.json.gz with the glasses' own time stamp, next to the gaze: the analysis lines the gaze
up with the experiment from them. The recording is started in Tobii Pro Glasses Controller as
usual (calibration there too); with record=True this program starts one itself (a project and a
participant named after the run) and stops it at the end.

The requests run in a thread: a slow or missing recording unit never holds up a frame.
"""

from __future__ import print_function

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request

TIMEOUT = 3.0


class G2Link(object):
    def __init__(self, host, run_name, record=False):
        self._base = 'http://%s' % (('[%s]' % host) if ':' in host and not host.startswith('[') else host)
        self._queue = queue.Queue()
        self._recording = None
        self.ok = None              # None: not known yet, True / False: the last request got through
        self._thread = threading.Thread(target=self._run, args=(run_name, record), daemon=True)
        self._thread.start()

    def _request(self, path, data=None):
        body = None if data is None else json.dumps(data).encode('utf-8')
        request = urllib.request.Request(self._base + path, data=body, method='POST' if body is not None else 'GET',
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            text = response.read().decode('utf-8')
        return json.loads(text) if text.strip() else None

    def _run(self, run_name, record):
        if record:
            try:
                project = self._request('/api/projects', {'pr_info': {'Name': 'ABC'}})['pr_id']
                participant = self._request('/api/participants',
                                            {'pa_project': project, 'pa_info': {'Name': run_name}})['pa_id']
                self._recording = self._request('/api/recordings',
                                                {'rec_participant': participant,
                                                 'rec_info': {'Name': run_name}})['rec_id']
                self._request('/api/recordings/%s/start' % self._recording, {})
                logging.info('Glasses 2: recording %s started', self._recording)
                self.ok = True
            except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
                logging.warning('Glasses 2: could not start a recording (%s): markers only', error)
                self._recording = None
                self.ok = False
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                self._request('/api/events', item)
                if self.ok is not True:
                    logging.info('Glasses 2: markers get through (%s)', self._base)
                self.ok = True
            except (OSError, ValueError, urllib.error.URLError) as error:
                if self.ok is not False:
                    logging.warning('Glasses 2 at %s not reached (%s): markers are lost until it is', self._base, error)
                self.ok = False
        if self._recording is not None:
            try:
                self._request('/api/recordings/%s/stop' % self._recording, {})
                logging.info('Glasses 2: recording %s stopped', self._recording)
            except (OSError, ValueError, urllib.error.URLError) as error:
                logging.warning('Glasses 2: could not stop recording %s (%s)', self._recording, error)

    def mark(self, kind, **fields):
        """A marker now: kind (e.g. 'freeze'), with the fields as its tag, plus the PC's clock."""
        fields['pc_time'] = round(time.time(), 3)
        self._queue.put({'type': 'abc_%s' % kind, 'tag': json.dumps(fields, ensure_ascii=False)})

    def close(self, wait=5.0):
        self._queue.put(None)
        self._thread.join(wait)
