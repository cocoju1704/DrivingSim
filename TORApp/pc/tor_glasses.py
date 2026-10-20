#!/usr/bin/env python

"""
Send the takeover state to TORApp on the phone, which shows it on the Meta Ray-Ban
Display glasses. PC -> phone over Wi-Fi (UDP), phone -> glasses over Bluetooth (DAT SDK).

Message, JSON in one UDP packet to the phone (port 5007):
    {"v": 1, "seq": 12, "mode": "TOR", "message": "Highway exit ahead",
     "remaining": 3.4, "total": 5.0, "label": "AUTONOMOUS"}
    mode       AUTO, PRE_ALERT, TOR, MANUAL or OFF
    seq        goes up by one each time mode, message or label changes
    remaining  seconds left in the PRE_ALERT / TOR countdown (null otherwise)
    label      text of the mode box on the simulator screen ("" : the app's default)
The state is resent every RESEND seconds, so a lost packet only delays it.

The app answers every packet with
    {"seq": 12, "shown": 11, "display": "STARTED"}
    shown      seq of the state now on the glasses (-1: nothing yet)
    display    state of the glasses display (STARTED when it can show content)
The first answer with a new "shown" gives the latency: PC send -> on the glasses ->
answer back on the PC (one extra Wi-Fi hop).

Test without the simulator (phone IP: shown in the app):

    python TORApp\\pc\\tor_glasses.py 192.168.0.23 --demo
    python TORApp\\pc\\tor_glasses.py 192.168.0.23 --mode TOR
"""

from __future__ import print_function

import argparse
import json
import logging
import socket
import threading
import time

DEFAULT_PORT = 5007
RESEND = 0.2          # seconds between resends of the current state
ALIVE_TIMEOUT = 2.0   # no answer for this long: the app is not running or not reachable
MODES = ('AUTO', 'PRE_ALERT', 'TOR', 'MANUAL', 'OFF')


class GlassesLink(object):
    """Keeps the phone up to date with the current state. update() is cheap: call it every frame."""

    def __init__(self, host, port=DEFAULT_PORT):
        self._address = (host, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(('', 0))  # recvfrom needs a bound socket on Windows
        self._socket.settimeout(RESEND)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._running = True
        self._seq = 0
        self._state = ('OFF', '', None, '')  # mode, message, total, label
        self._deadline = None            # time.monotonic() when the countdown ends
        self._sent_at = {}               # seq -> (time.monotonic() it was first sent, mode)
        self._shown = -1
        self._display = None
        self._last_answer = None
        self._warned_silent = False
        self.latencies = []              # (mode, seconds) from send to shown on the glasses
        self._threads = [threading.Thread(target=self._send_loop, name='glasses-send'),
                         threading.Thread(target=self._receive_loop, name='glasses-receive')]
        for thread in self._threads:
            thread.daemon = True
            thread.start()
        logging.info('Glasses: sending the takeover state to %s:%d', host, port)

    def update(self, mode, message='', remaining=None, total=None, label=''):
        """mode: AUTO, PRE_ALERT, TOR, MANUAL or OFF. remaining/total: countdown seconds.
        label: the mode box text of the simulator screen, e.g. 'AUTONOMOUS - LOCKED'."""
        if mode not in MODES:
            raise ValueError('unknown mode %r' % mode)
        now = time.monotonic()
        with self._lock:
            self._deadline = None if remaining is None else now + remaining
            state = (mode, message or '', total, label or '')
            if state == self._state:
                return
            self._seq += 1
            self._state = state
        self._wake.set()  # send the change now, not at the next resend

    @property
    def alive(self):
        return self._last_answer is not None and time.monotonic() - self._last_answer < ALIVE_TIMEOUT

    def close(self):
        self.update('OFF')
        time.sleep(3 * RESEND)  # a few sends, so the glasses clear even if one is lost
        self._running = False
        self._wake.set()
        for thread in self._threads:
            thread.join(1.0)
        self._socket.close()
        if self.latencies:
            values = sorted(seconds for _, seconds in self.latencies)
            logging.info('Glasses: %d state changes shown, latency median %.0f ms, max %.0f ms',
                         len(values), 1000.0 * values[len(values) // 2], 1000.0 * values[-1])

    def _packet(self):
        now = time.monotonic()
        with self._lock:
            mode, message, total, label = self._state
            seq = self._seq
            remaining = None if self._deadline is None else max(self._deadline - now, 0.0)
            self._sent_at.setdefault(seq, (now, mode))
        return json.dumps({'v': 1, 'seq': seq, 'mode': mode, 'message': message,
                           'remaining': None if remaining is None else round(remaining, 2),
                           'total': total, 'label': label}).encode('utf-8')

    def _send_loop(self):
        while self._running:
            self._wake.clear()
            try:
                self._socket.sendto(self._packet(), self._address)
            except OSError as error:  # no network: keep trying
                logging.debug('Glasses: send failed: %s', error)
            if self._last_answer is not None and not self.alive and not self._warned_silent:
                self._warned_silent = True
                logging.warning('Glasses: no answer from the phone app for %.0f s', ALIVE_TIMEOUT)
            self._wake.wait(RESEND)

    def _receive_loop(self):
        while self._running:
            try:
                data, _ = self._socket.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:  # Windows: ICMP port unreachable while the app is not running
                if not self._running:
                    return
                continue
            try:
                answer = json.loads(data.decode('utf-8'))
                shown = int(answer.get('shown', -1))
                display = answer.get('display')
            except (ValueError, TypeError, AttributeError):
                continue
            now = time.monotonic()
            if self._last_answer is None or self._warned_silent:
                logging.info('Glasses: phone app answering')
            self._last_answer = now
            self._warned_silent = False
            if display != self._display:
                self._display = display
                if display == 'STARTED':
                    logging.info('Glasses: display ready')
                else:
                    logging.warning('Glasses: display not ready (%s), start it in the phone app', display)
            # only states this run sent, each once (the app may still report one from an earlier run)
            if self._shown < shown <= self._seq:
                self._shown = shown
                with self._lock:
                    sent = self._sent_at.pop(shown, None)
                    for old in [seq for seq in self._sent_at if seq < shown]:
                        del self._sent_at[old]
                if sent is not None:
                    sent_time, mode = sent
                    self.latencies.append((mode, now - sent_time))
                    logging.info('Glasses: %s shown %.0f ms after it was sent', mode, 1000.0 * (now - sent_time))


def _countdown(link, mode, message, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        link.update(mode, message, end - time.monotonic(), seconds)
        time.sleep(0.05)


def main():
    argparser = argparse.ArgumentParser(description='Send a test takeover state to TORApp on the phone')
    argparser.add_argument('host', help='IP of the phone (shown in TORApp)')
    argparser.add_argument('--port', type=int, default=DEFAULT_PORT, help='UDP port (default: %d)' % DEFAULT_PORT)
    group = argparser.add_mutually_exclusive_group(required=True)
    group.add_argument('--demo', action='store_true',
                       help='AUTO 5 s -> PRE_ALERT 5 s -> TOR 5 s -> MANUAL 5 s, repeated until Ctrl+C')
    group.add_argument('--mode', choices=MODES, help='hold this mode until Ctrl+C')
    argparser.add_argument('--message', default='Highway exit ahead', help='pre-alert message')
    args = argparser.parse_args()
    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    link = GlassesLink(args.host, args.port)
    try:
        while True:
            if args.demo:
                link.update('AUTO')
                time.sleep(5.0)
                _countdown(link, 'PRE_ALERT', args.message, 5.0)
                _countdown(link, 'TOR', args.message, 5.0)
                link.update('MANUAL')
                time.sleep(5.0)
            elif args.mode in ('PRE_ALERT', 'TOR'):
                _countdown(link, args.mode, args.message, 5.0)
            else:
                link.update(args.mode)
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()


if __name__ == '__main__':
    main()
