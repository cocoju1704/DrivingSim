#!/usr/bin/env python

"""
SAGAT on the tablet (iPad Pro 11, Safari) or a laptop: this program serves the page, the tablet only opens
http://<this PC>:5011/ (the page can stay open between runs; add it to the home screen for full screen).
On a laptop on the same Wi-Fi, sagat_laptop.bat (copied there) waits for this server and opens the page
full screen. The page fits 1280x720 and up without scrolling.

The page asks GET /state every 0.3 s:
    {"phase": "idle", "run": "18c2..."}                        black, waiting (run: this block's id;
                                                               a new one: the page reloads itself)
    {"phase": "question", "qid": "A-Q1", "number": 1, "left": 24.2, "preload": [...]}
                                                               the SAGAT questions (preload: the NDRT
                                                               frames that follow, loaded unseen)
    {"phase": "wait", "qid": "A-Q1"}                           answered: wait for the video questions
    {"phase": "ndrt", "qid": "A-Q1", "images": [...], "left": 38.0}
                                                               the NDRT video questions: one frame at a
                                                               time, was this scene in the video
    {"phase": "countdown", "count": 3}                         3, 2, 1 before the drive goes on
and sends the answers with POST /answer:
    {"qid": "A-Q1", "items": {"behind_left": {"present": true, "confidence": 4}, ...}, "answer_ms": 18000}
    items: behind_left, behind, behind_right, ahead (abc_experiment.SAGAT_ITEMS, four zones since
    2026-11-13), each yes / no with its own confidence 1..5
    {"qid": "A-Q1", "kind": "ndrt", "answers": [{"image": "A/A-Q1-1.jpg", "shown": true, "confidence": 3,
     "ms": 4100}, ...], "answer_ms": 21000}                    the video questions, in the order asked
The frames are served from ndrt_items/ (GET /ndrt/A/A-Q1-1.jpg).
"""

from __future__ import print_function

import json
import logging
import os
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, 'sagat_app')
NDRT_DIR = os.path.join(HERE, 'ndrt_items')   # the NDRT video question frames (make_items.py)
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
        # this run's id in every /state: an open page reloads itself when it changes (a new block: the
        # same qids again, e.g. the practice drive run twice, would find it on "sent")
        self.run = '%x' % int(time.time() * 1000)
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
                if self.path.startswith('/ndrt/'):
                    path = os.path.normpath(os.path.join(NDRT_DIR, urllib.parse.unquote(self.path[6:].split('?')[0])))
                    if path.startswith(NDRT_DIR + os.sep) and path.lower().endswith('.jpg') and os.path.isfile(path):
                        with open(path, 'rb') as handle:
                            self._send(200, handle.read(), 'image/jpeg')
                    else:
                        self._send(404, 'not found', 'text/plain')
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
            state = dict(self._state, run=self.run)
            if state['phase'] in ('question', 'ndrt') and self._deadline is not None:
                state['left'] = round(max(0.0, self._deadline - time.monotonic()), 1)
            return state

    def connected(self, within=5.0):
        return self.last_seen is not None and time.monotonic() - self.last_seen < within

    def ask(self, qid, number, seconds, preload=()):
        """The SAGAT questions; preload: the NDRT frames (ndrt_items/ paths) the page loads meanwhile."""
        with self._lock:
            self._answer = None
            self._deadline = time.monotonic() + seconds
            self._state = {'phase': 'question', 'qid': qid, 'number': number,
                           'preload': ['/ndrt/' + p for p in preload]}

    def wait(self, qid):
        """Answered (or out of time): "wait" until the video questions."""
        with self._lock:
            self._state = {'phase': 'wait', 'qid': qid}

    def ask_ndrt(self, qid, images, seconds):
        """The NDRT video questions: the frames (ndrt_items/ paths), in this order."""
        with self._lock:
            self._answer = None
            self._deadline = time.monotonic() + seconds
            self._state = {'phase': 'ndrt', 'qid': qid, 'images': ['/ndrt/' + p for p in images]}

    def receive(self, answer):
        with self._lock:
            phase = self._state.get('phase')
            if answer.get('qid') != self._state.get('qid') or                     phase != ('ndrt' if answer.get('kind') == 'ndrt' else 'question'):
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


if __name__ == '__main__':  # the page alone, to look at it: SAGAT, then the practice's video questions
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    server = SagatServer()
    with open(os.path.join(NDRT_DIR, 'ndrt_items.json'), encoding='utf-8') as handle:
        frames = [i['image'] for i in json.load(handle)['P']['stops']['P-Q1']['items']]
    n = 0
    try:
        while True:
            time.sleep(5)
            n += 1
            server.ask('TEST-%d' % n, n, 30, frames)
            while server.answer() is None and server.state().get('left', 0) > 0:
                time.sleep(0.2)
            print(json.dumps(server.answer(), ensure_ascii=False))
            server.wait('TEST-%d' % n)
            time.sleep(3)
            server.ask_ndrt('TEST-%d' % n, frames, 40)
            while server.answer() is None and server.state().get('left', 0) > 0:
                time.sleep(0.2)
            print(json.dumps(server.answer(), ensure_ascii=False))
            for count in (3, 2, 1):
                server.countdown(count)
                time.sleep(1)
            server.idle()
    except KeyboardInterrupt:
        server.close()
