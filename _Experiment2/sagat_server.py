#!/usr/bin/env python

"""
SAGAT on the tablet (iPad Pro 11, Safari) or a laptop: this program serves the page, the tablet only opens
http://<this PC>:5011/ (the page can stay open between runs; add it to the home screen for full screen).
On a laptop on the same Wi-Fi, sagat_laptop.bat (copied there) waits for this server and opens the page
full screen. The page fits 1280x720 and up without scrolling.

The page asks GET /state every 0.3 s:
    {"phase": "idle"}                                          black, waiting
    {"phase": "question", "qid": "A-Q1", "number": 1, "left": 54.2}
    {"phase": "countdown", "count": 3}                         3, 2, 1 before the drive goes on
and sends the answer with POST /answer:
    {"qid": "A-Q1", "items": {"mirror_left": {"present": true, "confidence": 4}, ...}, "answer_ms": 18000}
    items: mirror_left, mirror_rear, mirror_right, beside_left, beside_right, ahead_left, ahead,
    ahead_right (abc_experiment.SAGAT_ITEMS), each yes / no with its own confidence 1..5
"""

from __future__ import print_function

import json
import logging
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, 'sagat_app')
DEFAULT_PORT = 5011


def own_address():
    """This PC's address on the network, or None."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('8.8.8.8', 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


class SagatServer(object):
    def __init__(self, port=DEFAULT_PORT):
        self._lock = threading.Lock()
        self._state = {'phase': 'idle'}
        self._deadline = None
        self._answer = None
        self.last_seen = None          # time.monotonic() of the tablet's last request
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, code, body, kind='application/json; charset=utf-8'):
                data = body if isinstance(body, bytes) else body.encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                server.last_seen = time.monotonic()
                if self.path.startswith('/state'):
                    self._send(200, json.dumps(server.state(), ensure_ascii=False))
                    return
                name = 'index.html' if self.path in ('/', '/index.html') else None
                if name is None:
                    self._send(404, 'not found', 'text/plain')
                    return
                with open(os.path.join(APP_DIR, name), 'rb') as handle:
                    self._send(200, handle.read(), 'text/html; charset=utf-8')

            def do_POST(self):
                server.last_seen = time.monotonic()
                if not self.path.startswith('/answer'):
                    self._send(404, 'not found', 'text/plain')
                    return
                length = int(self.headers.get('Content-Length', 0))
                try:
                    answer = json.loads(self.rfile.read(length).decode('utf-8'))
                except ValueError:
                    self._send(400, '{"ok": false}')
                    return
                self._send(200, json.dumps({'ok': server.receive(answer)}))

        self._http = ThreadingHTTPServer(('0.0.0.0', port), Handler)
        self._http.daemon_threads = True
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._thread.start()
        self.url = 'http://%s:%d/' % (own_address() or '<this PC IP>', port)
        logging.info('SAGAT: open %s on the iPad (Safari) or the laptop (sagat_laptop.bat)', self.url)

    def state(self):
        with self._lock:
            state = dict(self._state)
            if state['phase'] == 'question' and self._deadline is not None:
                state['left'] = round(max(0.0, self._deadline - time.monotonic()), 1)
            return state

    def connected(self, within=5.0):
        return self.last_seen is not None and time.monotonic() - self.last_seen < within

    def ask(self, qid, number, seconds):
        with self._lock:
            self._answer = None
            self._deadline = time.monotonic() + seconds
            self._state = {'phase': 'question', 'qid': qid, 'number': number}

    def receive(self, answer):
        with self._lock:
            if self._state.get('phase') != 'question' or answer.get('qid') != self._state.get('qid'):
                return False
            answer['received'] = time.time()
            self._answer = answer
            return True

    def answer(self):
        with self._lock:
            return self._answer

    def countdown(self, count):
        with self._lock:
            self._state = {'phase': 'countdown', 'count': count}

    def idle(self):
        with self._lock:
            self._state = {'phase': 'idle'}

    def close(self):
        self._http.shutdown()
        self._http.server_close()


if __name__ == '__main__':  # the page alone, to look at it: a question every 20 s
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    server = SagatServer()
    n = 0
    try:
        while True:
            time.sleep(5)
            n += 1
            server.ask('TEST-%d' % n, n, 60)
            while server.answer() is None and server.state().get('left', 0) > 0:
                time.sleep(0.2)
            print(json.dumps(server.answer(), ensure_ascii=False))
            for count in (3, 2, 1):
                server.countdown(count)
                time.sleep(1)
            server.idle()
    except KeyboardInterrupt:
        server.close()
