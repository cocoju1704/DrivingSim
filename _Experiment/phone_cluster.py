#!/usr/bin/env python

"""
Instrument cluster on a phone: the throttle pedal and speed gauges of the driver's view
(takeover_experiment.py --phone-cluster) as a full-screen page in the phone's browser.

The phone reaches this PC over USB tethering (or the same Wi-Fi); open the address that is logged
at the start, e.g. http://10.175.232.179:5009/, turn the phone sideways and tap the page for full
screen. The page gets the latest state up to STREAM_HZ times a second over one HTTP stream
(server-sent events), so it needs no polling and no app install.

    GET /          the cluster page (cluster_app/)
    GET /stream    text/event-stream of {"speed": km/h, "pedal": 0..1, "mode": "AUTONOMOUS", "color": [r, g, b],
                   "blinker": "left" / "right" / ""}

Try it without the simulator (the needles sweep):

    python _Experiment\\phone_cluster.py
"""

from __future__ import print_function

import argparse
import json
import logging
import math
import mimetypes
import os
import socket
import sys
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cluster_app')
DEFAULT_PORT = 5009
STREAM_HZ = 30.0


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A phone that closes the page or loses the link is no error worth a traceback."""
        if not isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            ThreadingHTTPServer.handle_error(self, request, client_address)


def local_addresses():
    """This PC's IPv4 addresses (not loopback), for the address to open on the phone."""
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in addresses if not a.startswith('127.') and not a.startswith('169.254.'))


class PhoneCluster(object):
    def __init__(self, port=DEFAULT_PORT):
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._state = {'speed': 0.0, 'pedal': 0.0, 'mode': '', 'color': [40, 160, 70]}
        self._seq = 0
        self._running = True
        self.clients = 0
        cluster = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                path = urlparse(self.path).path
                if path == '/stream':
                    cluster._stream(self)
                else:
                    self._static(path)

            def _static(self, path):
                name = 'index.html' if path in ('', '/') else path.lstrip('/')
                full = os.path.normpath(os.path.join(APP_DIR, name))
                if not full.startswith(APP_DIR) or not os.path.isfile(full):
                    self.send_error(404)
                    return
                with open(full, 'rb') as handle:
                    data = handle.read()
                kind = mimetypes.guess_type(full)[0] or 'application/octet-stream'
                if kind.startswith('text/') or kind == 'application/javascript':
                    kind += '; charset=utf-8'
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self._server = _QuietServer(('', port), Handler)
        thread = threading.Thread(target=self._server.serve_forever, name='phone-cluster')
        thread.daemon = True
        thread.start()
        addresses = local_addresses()
        logging.info('Phone cluster: open %s on the phone (USB tethering or the same Wi-Fi)',
                     ' or '.join('http://%s:%d/' % (a, port) for a in addresses) or 'http://<this PC>:%d/' % port)

    def update(self, speed_kmh, pedal, mode, color, blinker=''):
        """The latest state; sent to the phones at most STREAM_HZ times a second. Cheap: every frame.
        blinker: 'left', 'right' or '' (the turn signal that is on)."""
        with self._lock:
            self._state = {'speed': round(speed_kmh, 1), 'pedal': round(min(max(pedal, 0.0), 1.0), 3),
                           'mode': mode, 'color': list(color), 'blinker': blinker}
            self._seq += 1
            self._changed.notify_all()

    def _stream(self, handler):
        handler.close_connection = True  # the stream ends the connection
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Connection', 'keep-alive')
        handler.end_headers()
        with self._lock:
            self.clients += 1
        logging.info('Phone cluster: %s connected', handler.client_address[0])
        seq = -1
        try:
            while self._running:
                with self._lock:
                    if seq == self._seq:
                        self._changed.wait(1.0)
                    seq, state = self._seq, dict(self._state)
                handler.wfile.write(('data: %s\n\n' % json.dumps(state)).encode('utf-8'))
                handler.wfile.flush()
                time.sleep(1.0 / STREAM_HZ)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                self.clients -= 1
            logging.info('Phone cluster: %s disconnected', handler.client_address[0])

    def close(self):
        self._running = False
        with self._lock:
            self._changed.notify_all()
        self._server.shutdown()
        self._server.server_close()


def main():
    argparser = argparse.ArgumentParser(description='Phone cluster without the simulator: needles sweep')
    argparser.add_argument('--port', type=int, default=DEFAULT_PORT, help='HTTP port (default: %d)' % DEFAULT_PORT)
    args = argparser.parse_args()
    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)
    cluster = PhoneCluster(args.port)
    start = time.monotonic()
    try:
        while True:
            t = time.monotonic() - start
            manual = int(t / 10) % 2 == 1
            cluster.update(60.0 + 40.0 * math.sin(t / 3.0), 0.5 + 0.5 * math.sin(t), 'MANUAL' if manual else 'AUTONOMOUS',
                           (40, 110, 200) if manual else (40, 160, 70))
            time.sleep(1.0 / STREAM_HZ)
    except KeyboardInterrupt:
        pass
    finally:
        cluster.close()


if __name__ == '__main__':
    main()
