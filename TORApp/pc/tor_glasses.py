#!/usr/bin/env python

"""
Send the takeover state to TORApp on the phone, which shows it on the Meta Ray-Ban
Display glasses. PC -> phone over Wi-Fi (UDP), phone -> glasses over Bluetooth (DAT SDK).

Message, JSON in one UDP packet to the phone (port 5007):
    {"v": 1, "seq": 12, "mode": "TOR", "message": "Highway exit ahead",
     "remaining": 3.4, "total": 5.0, "label": "AUTONOMOUS", "text": []}
    mode       AUTO, PRE_ALERT, TOR, MANUAL or OFF
    seq        goes up by one each time mode, message, label or text changes
    remaining  seconds left in the PRE_ALERT / TOR countdown (null otherwise)
    label      text of the mode box on the simulator screen ("" : the app's default)
    text       intervention lines shown under the PRE-ALERT banner ([]: none)
    rtr        only with the NDRT RtR summary (set_rtr): the latest summary request, for the app's
               RtR section: {"id": 3, "state": "pending", "source": "auto", "lines": [], "error": ""}
               state idle, pending, done, error or timeout (see _Experiment/kakao_ndrt.py)
The state is resent every RESEND seconds, so a lost packet only delays it.

The app answers every packet with
    {"seq": 12, "shown": 11, "display": "STARTED", "rtr_request": 0}
    shown      seq of the state now on the glasses (-1: nothing yet)
    display    state of the glasses display (STARTED when it can show content)
    rtr_request  presses of the app's RtR button since the app started: each increase is a
               request for an RtR summary (on_rtr_request)
The first answer with a new "shown" gives the latency: PC send -> on the glasses ->
answer back on the PC (one extra Wi-Fi hop).

Phone address: its Wi-Fi IP (shown in the app), or "usb" with USB tethering on: the phone is
then the gateway of the PC's USB network adapter (Remote NDIS), found by usb_tether_address().

Test without the simulator:

    python TORApp\\pc\\tor_glasses.py usb --demo
    python TORApp\\pc\\tor_glasses.py 192.168.0.23 --demo
    python TORApp\\pc\\tor_glasses.py 192.168.0.23 --mode TOR
    python TORApp\\pc\\tor_glasses.py 192.168.0.23 --mode PRE_ALERT --text _Experiment\\NDRT_scripts\\scenario1_driving_summary.txt
"""

from __future__ import print_function

import argparse
import json
import logging
import os
import socket
import subprocess
import threading
import time

DEFAULT_PORT = 5007
RESEND = 0.2          # seconds between resends of the current state
ALIVE_TIMEOUT = 2.0   # no answer for this long: the app is not running or not reachable
MODES = ('AUTO', 'PRE_ALERT', 'TOR', 'MANUAL', 'OFF')


def usb_tether_address():
    """IP of a phone that shares its connection over USB (USB tethering): the default gateway of
    the PC's USB network adapter (Windows: "Remote NDIS based Internet Sharing Device"). None if
    there is none."""
    if os.name != 'nt':
        return None
    powershell = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32',
                              'WindowsPowerShell', 'v1.0', 'powershell.exe')  # System32 may not be on PATH
    command = ("Get-NetIPConfiguration | Where-Object { $_.InterfaceDescription -match 'NDIS|Tether' "
               "-and $_.IPv4DefaultGateway } | ForEach-Object { $_.IPv4DefaultGateway.NextHop }")
    try:
        output = subprocess.run([powershell, '-NoProfile', '-Command', command], capture_output=True,
                                text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError) as error:
        logging.warning('Glasses: could not look for USB tethering: %s', error)
        return None
    addresses = output.split()
    return addresses[0] if addresses else None


def resolve_host(host):
    """The phone's IP for --glasses: the address itself, or "usb" for USB tethering."""
    if host.lower() != 'usb':
        return host
    address = usb_tether_address()
    if address is None:
        raise RuntimeError('--glasses usb: no USB tethering found. Connect the phone with USB and turn on '
                           'Settings > Connections > Mobile Hotspot and Tethering > USB tethering')
    logging.info('Glasses: phone on USB tethering at %s', address)
    return address


class GlassesLink(object):
    """Keeps the phone up to date with the current state. update() is cheap: call it every frame."""

    def __init__(self, host, port=DEFAULT_PORT, on_rtr_request=None):
        """on_rtr_request(): called (on the receive thread) when the app's RtR button is pressed."""
        self._address = (host, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(('', 0))  # recvfrom needs a bound socket on Windows
        self._socket.settimeout(RESEND)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._running = True
        self._seq = 0
        self._state = ('OFF', '', None, '', ())  # mode, message, total, label, text
        self._deadline = None            # time.monotonic() when the countdown ends
        self._sent_at = {}               # seq -> (time.monotonic() it was first sent, mode)
        self._shown = -1
        self._display = None
        self._last_answer = None
        self._warned_silent = False
        self._rtr = None                 # RtR summary status for the app, None: not sent
        self._rtr_requests = None        # the app's last rtr_request count
        self.on_rtr_request = on_rtr_request  # can be set later
        self.latencies = []              # (mode, seconds) from send to shown on the glasses
        self._threads = [threading.Thread(target=self._send_loop, name='glasses-send'),
                         threading.Thread(target=self._receive_loop, name='glasses-receive')]
        for thread in self._threads:
            thread.daemon = True
            thread.start()
        logging.info('Glasses: sending the takeover state to %s:%d', host, port)

    def update(self, mode, message='', remaining=None, total=None, label='', text=()):
        """mode: AUTO, PRE_ALERT, TOR, MANUAL or OFF. remaining/total: countdown seconds.
        label: the mode box text of the simulator screen, e.g. 'AUTONOMOUS - LOCKED'.
        text: intervention lines shown under the PRE-ALERT banner."""
        if mode not in MODES:
            raise ValueError('unknown mode %r' % mode)
        now = time.monotonic()
        with self._lock:
            self._deadline = None if remaining is None else now + remaining
            state = (mode, message or '', total, label or '', tuple(text or ()))
            if state == self._state:
                return
            self._seq += 1
            self._state = state
        self._wake.set()  # send the change now, not at the next resend

    @property
    def display_ready(self):
        """True while the app answers and its glasses display runs (the alert sounds play there)."""
        return (self._display == 'STARTED' and self._last_answer is not None
                and time.monotonic() - self._last_answer < 3.0)

    def set_rtr(self, status):
        """RtR summary status shown in the app (see rtr in the message above); None: none."""
        with self._lock:
            self._rtr = status
        self._wake.set()

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
            mode, message, total, label, text = self._state
            seq = self._seq
            remaining = None if self._deadline is None else max(self._deadline - now, 0.0)
            self._sent_at.setdefault(seq, (now, mode))
            packet = {'v': 1, 'seq': seq, 'mode': mode, 'message': message,
                      'remaining': None if remaining is None else round(remaining, 2),
                      'total': total, 'label': label, 'text': list(text)}
            if self._rtr is not None:
                packet['rtr'] = self._rtr
        return json.dumps(packet, ensure_ascii=False).encode('utf-8')

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
                rtr_requests = answer.get('rtr_request')
            except (ValueError, TypeError, AttributeError):
                continue
            now = time.monotonic()
            if self._last_answer is None or self._warned_silent:
                logging.info('Glasses: phone app answering')
            self._last_answer = now
            self._warned_silent = False
            if isinstance(rtr_requests, int):
                # presses before this run are not requests: only increases from the first answer on
                if self._rtr_requests is not None and rtr_requests > self._rtr_requests:
                    logging.info('Glasses: RtR button pressed in the app')
                    if self.on_rtr_request is not None:
                        self.on_rtr_request()
                self._rtr_requests = rtr_requests
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


def _countdown(link, mode, message, seconds, text=(), delay=0.0, step=10.0, question=False):
    """text: shown from `delay` s on for len(text) * `step` s, like the experiment's intervention;
    question: one line at a time, each for `step` s."""
    start = time.monotonic()
    end = start + seconds
    while time.monotonic() < end:
        page = int((time.monotonic() - start - delay) // step)
        shown = ()
        if 0 <= page < len(text):
            shown = [text[page]] if question else text
        link.update(mode, message, end - time.monotonic(), seconds, text=shown)
        time.sleep(0.05)


def main():
    argparser = argparse.ArgumentParser(description='Send a test takeover state to TORApp on the phone')
    argparser.add_argument('host', help='IP of the phone (shown in TORApp), or usb for USB tethering')
    argparser.add_argument('--port', type=int, default=DEFAULT_PORT, help='UDP port (default: %d)' % DEFAULT_PORT)
    group = argparser.add_mutually_exclusive_group(required=True)
    group.add_argument('--demo', action='store_true',
                       help='AUTO 5 s -> PRE_ALERT --pre-alert s -> TOR 5 s -> MANUAL 5 s, repeated until Ctrl+C')
    group.add_argument('--mode', choices=MODES, help='hold this mode until Ctrl+C')
    argparser.add_argument('--message', default='Highway exit ahead', help='pre-alert message')
    argparser.add_argument('--text', metavar='FILE',
                           help='intervention text shown under the pre-alert, e.g. '
                                '_Experiment\\NDRT_scripts\\scenario1_driving_summary.txt')
    argparser.add_argument('--question', action='store_true',
                           help='show --text one line at a time, like the question format')
    argparser.add_argument('--delay', metavar='SEC', type=float, default=5.0,
                           help='seconds from the pre-alert to the text (default: 5)')
    argparser.add_argument('--question-seconds', metavar='SEC', type=float, default=10.0,
                           help='seconds per line; the text shows for lines x this (default: 10)')
    argparser.add_argument('--pre-alert', metavar='SEC', type=float, default=60.0,
                           help='PRE_ALERT countdown, as in the experiment (default: 60)')
    args = argparser.parse_args()
    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    text = ()
    if args.text:
        with open(args.text, encoding='utf-8-sig') as handle:
            text = [line.strip() for line in handle if line.strip() and not line.lstrip().startswith('#')]
    window = dict(delay=args.delay, step=args.question_seconds, question=args.question)
    link = GlassesLink(resolve_host(args.host), args.port)
    try:
        while True:
            if args.demo:
                link.update('AUTO')
                time.sleep(5.0)
                _countdown(link, 'PRE_ALERT', args.message, args.pre_alert, text, **window)
                _countdown(link, 'TOR', args.message, 5.0)
                link.update('MANUAL')
                time.sleep(5.0)
            elif args.mode == 'PRE_ALERT':
                _countdown(link, args.mode, args.message, args.pre_alert, text, **window)
            elif args.mode == 'TOR':
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
