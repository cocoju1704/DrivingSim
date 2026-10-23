#!/usr/bin/env python

"""
Bridge between the takeover experiment and the Gmail extension (_Experiment/gmail_rtr_extension)
that writes the NDRT ready-to-resume (RtR) summary with the OpenAI API (ChatGPT).

The extension runs in the participant's Chrome, which cannot accept connections, so it asks
this small HTTP server for work every 0.5 s:

    GET  /rtr/next      the oldest request not handed out yet (each one only once, and only
                        while younger than REQUEST_TTL s): {"request": {"id": 3, "source": "auto"}}
                        or {"request": null}
    POST /rtr/result    the summary: {"request_id": 3, "lines": [...], ...} or
                        {"request_id": 3, "error": "..."}; request_id null for the extension's
                        own button
    GET  /rtr/request   a manual request (?source=NAME), e.g. from a browser
    GET  /rtr/status    the latest request and result, for checking by hand

Requests come from the experiment (5 s before the pre-alert), the TORApp button on the phone
(through tor_glasses.GlassesLink) or /rtr/request. Every request and result is appended to
rtr.jsonl in the run's log folder.

Test without the simulator (then press the extension's poll / write in Gmail):

    python _Experiment\\rtr_bridge.py
    python _Experiment\\rtr_bridge.py --request
"""

from __future__ import print_function

import argparse
import datetime
import json
import logging
import os
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DEFAULT_PORT = 5008
REQUEST_TTL = 15.0  # s: an older request is stale, the extension would summarize a later state


class RtrBridge(object):
    def __init__(self, port=DEFAULT_PORT, log_dir=None, on_change=None):
        """log_dir: folder for rtr.jsonl (None: no file). on_change(status): called when the
        latest request or result changes, e.g. to show it in TORApp."""
        self._lock = threading.Lock()
        self._next_id = 1
        self._requests = []        # dicts: id, source, time (monotonic), claimed
        self._result = None        # latest result dict, with 'since' (monotonic)
        self._latest = None        # latest request dict
        self._log_dir = log_dir
        self._on_change = on_change
        self._reported = None      # last status given to on_change
        self._running = True
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlparse(self.path)
                if url.path == '/rtr/next':
                    self._json({'request': bridge._claim()})
                elif url.path == '/rtr/request':
                    source = parse_qs(url.query).get('source', ['http'])[0]
                    self._json({'id': bridge.request(source)})
                elif url.path == '/rtr/status':
                    self._json(bridge.status())
                else:
                    self.send_error(404)

            def do_POST(self):
                if urlparse(self.path).path != '/rtr/result':
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    result = json.loads(self.rfile.read(length).decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    self.send_error(400)
                    return
                bridge._receive(result)
                self._json({'ok': True})

            def _json(self, value):
                body = json.dumps(value, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # every 0.5 s poll would flood the console
                pass

        self._server = ThreadingHTTPServer(('', port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name='rtr-bridge')
        self._thread.daemon = True
        self._thread.start()
        if on_change is not None:  # also report a request that times out
            watcher = threading.Thread(target=self._watch, name='rtr-watch')
            watcher.daemon = True
            watcher.start()
        logging.info('RtR bridge: http://<this PC>:%d (gmail_rtr_extension polls it)', port)

    # -- requests and results ----------------------------------------------------

    def request(self, source):
        """Ask the extension for a summary of the draft now. Returns the request id."""
        with self._lock:
            request = {'id': self._next_id, 'source': source, 'time': time.monotonic(), 'claimed': False}
            self._next_id += 1
            self._requests.append(request)
            self._latest = request
        logging.info('RtR summary requested (#%d, %s)', request['id'], source)
        self.log({'event': 'request', 'id': request['id'], 'source': source})
        self._changed()
        return request['id']

    def result_since(self, since):
        """Latest result with lines for a request made (or, from the extension's button, a result
        received) at time.monotonic() >= since; None if there is none."""
        with self._lock:
            result = self._result
        if result is None or not result.get('lines') or result['since'] < since:
            return None
        return result

    def status(self):
        """Small summary for TORApp and /rtr/status: id, source, state, lines, error."""
        with self._lock:
            request, result = self._latest, self._result
        if request is None and result is None:
            return {'id': 0, 'state': 'idle', 'source': '', 'lines': [], 'error': ''}
        if request is not None and (result is None or result['since'] < request['time']):  # not answered yet
            state = 'pending' if time.monotonic() - request['time'] < REQUEST_TTL else 'timeout'
            return {'id': request['id'], 'state': state, 'source': request['source'], 'lines': [], 'error': ''}
        return {'id': result['request_id'] or 0, 'state': 'error' if result.get('error') else 'done',
                'source': result['source'], 'lines': result.get('lines') or [], 'error': result.get('error') or ''}

    def log(self, entry):
        """Append one line to rtr.jsonl in the log folder."""
        if self._log_dir is None:
            return
        entry = dict(entry, wall_time=datetime.datetime.now().isoformat(timespec='milliseconds'))
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            with open(os.path.join(self._log_dir, 'rtr.jsonl'), 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except OSError as error:
            logging.error('RtR bridge: could not write rtr.jsonl: %s', error)

    def close(self):
        self._running = False
        self._server.shutdown()
        self._server.server_close()

    def _claim(self):
        now = time.monotonic()
        with self._lock:
            self._requests = [r for r in self._requests if now - r['time'] < REQUEST_TTL]
            for request in self._requests:
                if not request['claimed']:
                    request['claimed'] = True
                    return {'id': request['id'], 'source': request['source']}
        return None

    def _receive(self, result):
        now = time.monotonic()
        request_id = result.get('request_id')
        with self._lock:
            request = next((r for r in self._requests if r['id'] == request_id), None)
            if request_id is not None and request is None and self._latest is not None \
                    and self._latest['id'] == request_id:
                request = self._latest
            stored = {
                'request_id': request_id,
                'source': request['source'] if request else result.get('source', 'extension'),
                'since': request['time'] if request else now,  # the button's result counts from now
                'lines': [str(line) for line in result.get('lines') or []],
                'error': result.get('error'),
            }
            self._result = stored
        if stored['error']:
            logging.warning('RtR summary #%s failed: %s', request_id, stored['error'])
        else:
            logging.info('RtR summary #%s (%s, %.1f s): %s', request_id, stored['source'], now - stored['since'],
                         ' / '.join(stored['lines']))
        self.log(dict(result, event='result', seconds=round(now - stored['since'], 2), source=stored['source']))
        self._changed()

    def _changed(self):
        if self._on_change is None:
            return
        status = self.status()
        if status != self._reported:
            self._reported = status
            self._on_change(status)

    def _watch(self):
        while self._running:
            time.sleep(1.0)
            self._changed()


def main():
    argparser = argparse.ArgumentParser(description='RtR bridge for gmail_rtr_extension, without the simulator')
    argparser.add_argument('--port', type=int, default=DEFAULT_PORT, help='HTTP port (default: %d)' % DEFAULT_PORT)
    argparser.add_argument('--request', action='store_true', help='request a summary right away, then every 30 s')
    argparser.add_argument('--log-dir', metavar='DIR', help='write rtr.jsonl here')
    args = argparser.parse_args()
    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)
    bridge = RtrBridge(args.port, args.log_dir)
    try:
        while True:
            if args.request:
                bridge.request('test')
            time.sleep(30.0)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()


if __name__ == '__main__':
    main()
