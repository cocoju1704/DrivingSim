#!/usr/bin/env python

"""
Tobii Pro Glasses 2: the experiment's events as markers in the glasses' recording, over the
glasses' REST API (http://<recording unit>/api/...). The recording unit's address on its own
Wi-Fi is 192.168.71.50; on a cable it is reached by its IPv6 link-local name (see the Glasses 2
API guide).

Markers: POST /api/events {"type": "abc_<what>", "tag": "id=...;t_sim=...;pc_time=..."}. They land in the recording's
livedata.json.gz with the glasses' own time stamp, next to the gaze: the analysis lines the gaze
up with the experiment from them. The recording is started in Tobii Pro Glasses Controller as
usual (calibration there too); with record=True this program starts one itself (named after the
run, under the participant of the last calibration: g2_calibrate.py) and stops it at the end.

The requests run in a thread: a slow or missing recording unit never holds up a frame.

With stream_dir, the glasses' live gaze and scene video are also saved on this PC (g2_stream.py,
its own process): the block's data folder has them without the SD card.
"""

from __future__ import print_function

import http.client
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

TIMEOUT = 3.0
CALIBRATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'g2_calibration.json')


def tag(fields):
    """A marker's tag: key=value;key=value. The glasses put the tag into their JSON (livedata, the
    live data stream) without escaping it: a " or \\ in it would break that line."""
    return ';'.join('%s=%s' % (key, str(value).replace('"', "'").replace('\\', '/').replace(';', ','))
                    for key, value in fields.items())


def parse_tag(text):
    """tag() back to a dict (the values as text)."""
    return dict(item.split('=', 1) for item in text.split(';') if '=' in item)


class G2Link(object):
    def __init__(self, host, run_name, record=False, stream_dir=None):
        """stream_dir: also save the live gaze and scene video there (g2_stream.py, own process)."""
        self._stream = None
        if stream_dir:
            try:
                self._stream = subprocess.Popen(
                    [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'g2_stream.py'),
                     host, stream_dir], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    universal_newlines=True)
                logging.info('Glasses 2: saving the live gaze and scene video to %s', stream_dir)
            except OSError as error:
                logging.warning('Glasses 2: live streams not saved (%s)', error)
        if ':' in host:
            # IPv6 (the cable): a link-local address carries its interface, fe80::...%15; in a URL
            # the % is written %25, or urllib reads %15 as an escaped character.
            host = host.strip('[]')
            if '%' in host and '%25' not in host:
                host = host.replace('%', '%25')
            host = '[%s]' % host
        self._base = 'http://%s' % host
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
        try:
            return json.loads(text) if text.strip() else None
        except ValueError:
            return text             # /api/events answers in plain text: "OK, event sync received!"

    def calibrated_participant(self):
        """(participant, calibration) to record with: the glasses tie a recording to the
        participant's calibration, so a recording under a new participant has none.
        1. the latest calibration since the glasses were switched on (each participant is
           calibrated before the drive, g2_calibrate.py or the Controller);
        2. none: the one g2_calibrate.py made last (CALIBRATION_FILE);
        3. none either: the glasses' latest stored one by date (a fallback: someone else's eyes).
        The glasses' clock restarts at 2000-01-01 on every power-on, so dates only compare within
        one power-on; its start is sys_time - sys_uptime."""
        calibrations = {c['ca_id']: c for c in self._request('/api/calibrations') or []
                        if c.get('ca_state') == 'calibrated'}
        if not calibrations:
            return None, None
        status = self._request('/api/system/status')
        now = time.mktime(time.strptime(status['sys_time'][:19], '%Y-%m-%dT%H:%M:%S'))
        stamp = lambda t: time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t))   # noqa: E731
        boot, until = stamp(now - float(status['sys_uptime']) - 5), stamp(now + 5)
        newest = lambda cs: max(cs, key=lambda c: c.get('ca_created', ''))['ca_id']   # noqa: E731
        # from an earlier power-on a calibration can carry a later date (2000-01-07 vs now 2000-01-01)
        session = [c for c in calibrations.values() if boot <= c.get('ca_created', '')[:19] <= until]
        if session:
            last = newest(session)
        else:
            try:
                with open(CALIBRATION_FILE, encoding='utf-8') as handle:
                    last = json.load(handle).get('ca_id')
            except (OSError, ValueError):
                last = None
            if last not in calibrations:
                last = newest(calibrations.values())
            logging.warning('Glasses 2: no calibration since the glasses were switched on: '
                            'recording with the earlier calibration %s (python g2_calibrate.py first)', last)
        return calibrations[last]['ca_participant'], last

    def _run(self, run_name, record):
        if record:
            try:
                participant, calibration = self.calibrated_participant()
                if participant is None:
                    logging.warning('Glasses 2: no calibration to record with (python g2_calibrate.py): '
                                    'the recording has no calibrated gaze')
                    project = self._request('/api/projects', {'pr_info': {'Name': 'ABC'}})['pr_id']
                    participant = self._request('/api/participants',
                                                {'pa_project': project, 'pa_info': {'Name': run_name}})['pa_id']
                self._recording = self._request('/api/recordings',
                                                {'rec_participant': participant,
                                                 'rec_info': {'Name': run_name}})['rec_id']
                self._request('/api/recordings/%s/start' % self._recording, {})
                logging.info('Glasses 2: recording %s started (calibration %s)', self._recording, calibration)
                self.ok = True
            except (OSError, ValueError, KeyError, http.client.HTTPException) as error:
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
            except (OSError, ValueError, http.client.HTTPException) as error:
                if self.ok is not False:
                    logging.warning('Glasses 2 at %s not reached (%s): markers are lost until it is', self._base, error)
                self.ok = False
        if self._recording is not None:
            try:
                self._request('/api/recordings/%s/stop' % self._recording, {})
                logging.info('Glasses 2: recording %s stopped', self._recording)
            except (OSError, ValueError, http.client.HTTPException) as error:
                logging.warning('Glasses 2: could not stop recording %s (%s)', self._recording, error)

    def mark(self, kind, **fields):
        """A marker now: kind (e.g. 'freeze'), with the fields as its tag, plus the PC's clock."""
        fields['pc_time'] = round(time.time(), 3)
        self._queue.put({'type': 'abc_%s' % kind, 'tag': tag(fields)})

    def close(self, wait=5.0):
        self._queue.put(None)
        self._thread.join(wait)
        if self._stream is not None:
            try:
                output, _ = self._stream.communicate('stop\n', timeout=10.0)
                for line in output.strip().splitlines():
                    logging.info('%s', line)
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                logging.warning('Glasses 2: the live stream saver did not stop (%s)', error)
                self._stream.kill()
            self._stream = None
