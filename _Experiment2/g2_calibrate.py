#!/usr/bin/env python

"""
Tobii Pro Glasses 2: calibrates the glasses over their REST API, without the Glasses Controller,
then finds where the Meta Ray-Ban Display's screen is in the Glasses 2 gaze (glasses condition).

    python g2_calibrate.py [HOST]               both steps (HOST: devices.json's g2 when left out)
    python g2_calibrate.py --display-only       only the glasses display step
    python g2_calibrate.py --no-display         only the Glasses 2 calibration

A white window covers the monitors (g2_validate.Screen). It all runs by itself (a countdown before each
step, up to G2_TRIES calibrations); Esc stops; only the result at the end waits for Enter (with
--validate, which the menu passes, a successful one shows for RESULT_S and the validation follows) (menu.py
starts this).

1. Glasses 2 calibration. The participant wears the glasses; the calibration target (black ring, white
   disc, black dot, as g2_validate.py's) is shown at the middle monitor's centre. The participant looks
   at its dot and keeps the head still; Enter starts the calibration, which takes a few seconds. On a
   failure Enter tries again (the glasses on the nose, the head straight at the monitor).

2. The glasses display. The participant wears the Ray-Ban Display too, its app open (mrbd-video, the
   server at devices.json's video). The app's menu is hidden (calib 'blank') through both steps;
   "이제 글래스를 보세요" on it, then a dot in the middle of its screen and then near each
   corner (CALIB_INSET px in from the edges); the participant looks at each dot until it moves on
   (DOT_SETTLE_S + DOT_COLLECT_S each). Both glasses sit on the head, so where the display is in the
   Glasses 2 scene camera stays the same while they are worn: the median gaze at each dot (gaze
   point gp, 0..1 of the scene camera) gives the display's outline there, saved in DISPLAY_FILE (and
   copied into each block's data folder by abc_experiment): gaze inside it = looking at the display.
   Do it again whenever either pair of glasses was taken off or moved on the nose.
"""

from __future__ import print_function

import json
import os
import socket
import statistics
import sys
import threading
import time

from g2_link import CALIBRATION_FILE, G2Link
import g2_stream
from g2_validate import Screen

HERE = os.path.dirname(os.path.abspath(__file__))
DISPLAY_FILE = os.path.join(HERE, 'g2_display.json')
DISPLAY_PX = (600, 600)      # the Ray-Ban Display's screen (mrbd-video's app)
CALIB_INSET = 60             # px from its edges to the corner dots: the display's bottom edge sits at the
                             # bottom of the scene camera's view, where the gaze is lost; the outline
                             # (g2_validate.py's homography) reaches the edges from these four
MIN_APP_VERSION = 12         # the glasses app's calib.js with 'blank' and text
CUE_S = 3.0                  # s of "이제 글래스를 보세요" before the dots
COUNTDOWN_S = 3              # s on the target before the calibration starts (the eyes settle on it)
G2_TRIES = 3                 # calibrations tried in turn before giving up
RESULT_S = 4.0               # s the result shows when the validation follows
DOTS = ('c', 'tl', 'tr', 'br', 'bl')
DOT_NAMES = {'c': '가운데', 'tl': '왼쪽 위', 'tr': '오른쪽 위', 'br': '오른쪽 아래', 'bl': '왼쪽 아래'}
CENTRE = (0, 0.5, 0.5)       # the calibration target: the middle monitor's centre (g2_validate's points)
# its size: the Glasses 2 only takes the manual's marker (ring 43 mm) at true size or so ("lacking
# calibration markers" when it is too small in the scene camera); --target-mm=MM for a larger one
TARGET_MM = 43.0
MONITOR_WIDTH_MM = 708.0     # the 32 inch 16:9 monitors' panel width
# this run's outcome (report()): each step's (ok, detail), the dots' (status, spread, samples)
STATE = {'g2': None, 'g2_detail': '', 'g2_tries': 0, 'display': None, 'display_detail': '', 'dots': {}}
DOT_SETTLE_S = 1.2           # s after a dot appears before its gaze counts (the eyes get there)
DOT_COLLECT_S = 1.5          # s of gaze per dot
MIN_SAMPLES = 20             # valid gaze samples a dot needs (50 Hz: 75 in DOT_COLLECT_S)
MAX_SPREAD = 0.03            # median distance of a dot's samples from their median (0..1 of the scene camera);
                             # the display only has to tell 'looking at it' (about 12 x 12 degrees)


def dot_px(dot):
    w, h = DISPLAY_PX
    i = CALIB_INSET
    return {'c': (w / 2.0, h / 2.0), 'tl': (i, i), 'tr': (w - i, i), 'br': (w - i, h - i), 'bl': (i, h - i)}[dot]


def report():
    """This run's outcome as a g2_report report (title, ok, sections)."""
    def step(ok):
        return ('-', None) if ok is None else (('성공', True) if ok else ('실패', False))
    rows = [['Glasses 2 캘리브레이션', step(STATE['g2']), STATE['g2_detail']]]
    if STATE['g2_tries'] > 1:
        rows[0][2] += ' · %d번째 시도' % STATE['g2_tries']
    if STATE['display'] is not None or STATE['dots']:
        rows.append(['안경 화면 보정', step(STATE['display']), STATE['display_detail']])
    if STATE.get('error'):
        rows.append(['오류', ('×', False), STATE['error']])
    sections = [('결과', rows)]
    if STATE['dots']:
        dots = []
        for dot in DOTS:
            status, spread, samples = STATE['dots'].get(dot, ('-', None, None))
            dots.append([DOT_NAMES[dot], (status, {'안정': True, '흔들림': False, '샘플 부족': False}.get(status)),
                         '' if spread is None else '퍼짐 %.3f' % spread,
                         '' if samples is None else '샘플 %d' % samples])
        sections.append(('안경 화면 점', dots))
    ok = STATE['g2'] and STATE['display'] is not False and not STATE.get('error')
    if STATE['g2'] is None:
        ok = None
    return ('캘리브레이션 성공' if ok else '캘리브레이션 실패' if ok is False else '캘리브레이션 중단'), ok, sections


def calibrate_glasses2(g2, screen):
    status = g2._request('/api/system/status')
    print('Glasses 2 %s: battery %s%%, eye tracker %s' % (
        status['sys_name'], status['sys_battery']['level'], status['sys_et']['state']))
    project = next((p['pr_id'] for p in g2._request('/api/projects') if p['pr_info'].get('Name') == 'ABC'), None)
    if project is None:
        project = g2._request('/api/projects', {'pr_info': {'Name': 'ABC'}})['pr_id']
    participant = g2._request('/api/participants', {'pa_project': project, 'pa_info': {'Name': 'calibration'}})['pa_id']
    mm = next((float(a.split('=', 1)[1]) for a in sys.argv[1:] if a.startswith('--target-mm=')), TARGET_MM)
    size = mm / MONITOR_WIDTH_MM
    print('Calibration target: ring %.0f mm' % mm)
    caption = '고개를 고정하고 가운데 점을 보세요'
    for attempt in range(G2_TRIES):
        print('\nTarget on the middle monitor, participant looks at its dot: calibration in %d s (try %d of %d), '
              'Esc on the white window: quit' % (COUNTDOWN_S, attempt + 1, G2_TRIES))
        for left in range(COUNTDOWN_S, 0, -1):
            screen.target(CENTRE, '%s  ·  %d초 뒤 시작  ·  Esc: 끝' % (caption, left), size)
            if not screen.wait(1.0):
                return None
        screen.target(CENTRE, '캘리브레이션 중... 점을 계속 보세요', size)
        STATE['g2_tries'] += 1
        calibration = g2._request('/api/calibrations', {'ca_project': project, 'ca_type': 'default',
                                                        'ca_participant': participant})['ca_id']
        g2._request('/api/calibrations/%s/start' % calibration, {})
        state = 'calibrating'
        started = time.time()
        while state not in ('calibrated', 'failed') and time.time() - started < 30:
            time.sleep(0.5)
            state = g2._request('/api/calibrations/%s/status' % calibration).get('ca_state', state)
            print('  %4.1f s %s' % (time.time() - started, state), end='\r')
        result = g2._request('/api/calibrations/%s' % calibration)
        print()
        if state == 'calibrated':
            with open(CALIBRATION_FILE, 'w', encoding='utf-8') as handle:
                json.dump({'ca_id': calibration, 'ca_participant': participant, 'pc_time': time.time()}, handle)
            print('Calibrated (%s). The recordings from now on use it.' % calibration)
            STATE.update(g2=True, g2_detail='%s · %.1f s' % (calibration, time.time() - started))
            return calibration
        print('Failed: %s (%s)' % (result.get('ca_error', state), result.get('ca_error_code', '')))
        STATE.update(g2=False, g2_detail='%s (%s)' % (result.get('ca_error', state), result.get('ca_error_code', '')))
        caption = '실패 (%s), 다시 합니다: 고개를 고정하고 가운데 점을 보세요' % result.get('ca_error_code', state)
    return None


class GazeReceiver(object):
    """The Glasses 2 live gaze point gp (valid samples), as (PC time, x, y)."""

    def __init__(self, host):
        family, self._address = g2_stream.address(host)
        self._sock = socket.socket(family, socket.SOCK_DGRAM)
        self._sock.settimeout(0.2)
        self._stop = threading.Event()
        self.samples = []
        self.packets = 0
        for target in (self._keepalive, self._receive):
            threading.Thread(target=target, daemon=True).start()

    def _keepalive(self):
        message = {'type': 'live.data.unicast', 'key': 'abc-display', 'op': 'start'}
        while not self._stop.is_set():
            try:
                self._sock.sendto(json.dumps(message).encode(), self._address)
            except OSError:
                pass
            self._stop.wait(1.0)

    def _receive(self):
        while not self._stop.is_set():
            try:
                packet = json.loads(self._sock.recv(65536))
            except (socket.timeout, ValueError, OSError):
                continue
            self.packets += 1
            if 'gp' in packet and packet.get('s') == 0:
                self.samples.append((time.time(), packet['gp'][0], packet['gp'][1]))

    def between(self, start, end):
        return [(x, y) for t, x, y in self.samples if start <= t <= end]

    def close(self):
        self._stop.set()


def _median_point(points):
    mx = statistics.median(x for x, _ in points)
    my = statistics.median(y for _, y in points)
    spread = statistics.median(((x - mx) ** 2 + (y - my) ** 2) ** 0.5 for x, y in points)
    return mx, my, spread


def glasses_link(video_address):
    """The glasses app's link with its menu hidden (calib 'blank'), or None (why printed)."""
    from video_link import VideoLink
    link = VideoLink(video_address)
    try:
        delivered = link.calib_now('blank')
    except OSError as error:
        print('The video server at %s is not reached (%s): start it, open the app on the glasses' % (
            link.base, error))
        link.close()
        return None
    if not delivered:
        print('The glasses app is not connected to %s: open it on the glasses first' % link.base)
        link.close()
        return None
    time.sleep(0.5)                     # its report with the version
    version = link.app_version()
    if version < MIN_APP_VERSION:
        print('The glasses app is v%d, these steps need v%d (calib blank): update it (git pull where the '
              'server runs, then reopen the app; or disconnect and connect the web app in Meta AI)'
              % (version, MIN_APP_VERSION))
        link.calib_now('off')
        link.close()
        return None
    return link


def calibrate_display(g2_host, link, calibration, screen):
    gaze = GazeReceiver(g2_host)
    try:
        time.sleep(1.5)
        if not gaze.samples:
            print('No valid gaze from the Glasses 2 (%d packets): is the participant wearing them, calibrated?'
                  % gaze.packets)
            STATE.update(display=False, display_detail='Glasses 2 시선이 들어오지 않음 (%d 패킷)' % gaze.packets)
            return False
        print('\nGlasses display: the participant looks at each red dot on the glasses display until it '
              'moves (5 dots, %.0f s). Esc (on the white window): quit'
              % (len(DOTS) * (DOT_SETTLE_S + DOT_COLLECT_S)))
        screen.message('글래스 화면 보정', '고개를 고정하고 빨간 점을 눈으로만 따라가세요  ·  Esc: 끝')
        if not screen.wait(CUE_S):
            return False
        screen.message('이제 글래스를 보세요')
        link.calib_now('blank', '이제 글래스를 보세요')
        time.sleep(CUE_S)
        found = {}
        for dot in DOTS:
            for attempt in range(2):
                link.calib_now('px:%d,%d' % dot_px(dot))
                shown = time.time()
                time.sleep(DOT_SETTLE_S + DOT_COLLECT_S)
                points = gaze.between(shown + DOT_SETTLE_S, shown + DOT_SETTLE_S + DOT_COLLECT_S)
                if len(points) >= MIN_SAMPLES:
                    x, y, spread = _median_point(points)
                    if spread <= MAX_SPREAD:
                        found[dot] = {'gp': [round(x, 4), round(y, 4)], 'spread': round(spread, 4),
                                      'samples': len(points), 'display_px': list(dot_px(dot))}
                        print('  %-2s gaze (%.3f, %.3f), spread %.3f, %d samples' % (dot, x, y, spread, len(points)))
                        STATE['dots'][dot] = ('안정', spread, len(points))
                        break
                    print('  %-2s unsteady (spread %.3f): again' % (dot, spread))
                    STATE['dots'][dot] = ('흔들림', spread, len(points))
                else:
                    print('  %-2s too few valid samples (%d): again' % (dot, len(points)))
                    STATE['dots'][dot] = ('샘플 부족', None, len(points))
        link.calib_now('blank')
    finally:
        gaze.close()
    corners = ('tl', 'tr', 'br', 'bl')
    missing = [d for d in corners if d not in found]
    if 'c' in found and len(missing) == 1:
        # one corner (mostly a bottom one, at the edge of the scene camera's view): from the other three,
        # a parallelogram (opposite = sum of its neighbours minus the far one)
        k = corners.index(missing[0])
        a, b, far = found[corners[(k - 1) % 4]], found[corners[(k + 1) % 4]], found[corners[(k + 2) % 4]]
        gp = [round(a['gp'][i] + b['gp'][i] - far['gp'][i], 4) for i in range(2)]
        found[missing[0]] = {'gp': gp, 'estimated': True, 'display_px': list(dot_px(missing[0]))}
        print('  %-2s estimated from the other three corners: (%.3f, %.3f)' % (missing[0], gp[0], gp[1]))
        STATE['dots'][missing[0]] = ('추정 (세 꼭짓점)', None, None)
    if len(found) < len(DOTS):
        print('Glasses display not found: %s missing. Run again (--display-only).'
              % ', '.join(d for d in DOTS if d not in found))
        STATE.update(display=False, display_detail='%s 못 찾음' % ', '.join(DOT_NAMES[d] for d in DOTS if d not in found))
        return False
    tl, tr, br, bl, c = (found[d]['gp'] for d in ('tl', 'tr', 'br', 'bl', 'c'))
    if not (tl[0] < tr[0] and bl[0] < br[0] and tl[1] < bl[1] and tr[1] < br[1]):
        print('The corners are not in their order (the gaze went elsewhere): run again (--display-only)')
        STATE.update(display=False, display_detail='꼭짓점 순서가 맞지 않음 (시선이 다른 곳)')
        return False
    if not (min(tl[0], bl[0]) < c[0] < max(tr[0], br[0]) and min(tl[1], tr[1]) < c[1] < max(bl[1], br[1])):
        print('The centre is outside the corners: run again (--display-only)')
        STATE.update(display=False, display_detail='가운데 점이 꼭짓점 밖')
        return False
    result = {'dots': found, 'outline_gp': [tl, tr, br, bl], 'display_px': list(DISPLAY_PX),
              'calib_inset_px': CALIB_INSET, 'g2_calibration': calibration, 'pc_time': round(time.time(), 3),
              'about': 'Meta Ray-Ban Display screen in the Glasses 2 gaze (gp, 0..1 of the scene camera): '
                       'the corner dots are CALIB_INSET px inside its edges; g2_calibrate.py'}
    with open(DISPLAY_FILE, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, indent=1)
    width = (tr[0] - tl[0] + br[0] - bl[0]) / 2.0
    height = (bl[1] - tl[1] + br[1] - tr[1]) / 2.0
    print('Glasses display: %.3f x %.3f of the scene camera, centre (%.3f, %.3f) -> %s'
          % (width, height, c[0], c[1], DISPLAY_FILE))
    STATE.update(display=True, display_detail='장면 카메라의 %.3f × %.3f, 가운데 (%.3f, %.3f)' % (width, height, c[0], c[1]))
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    with open(os.path.join(HERE, 'devices.json'), encoding='utf-8') as handle:
        devices = json.load(handle)
    host = args[0] if args else devices['g2']
    g2 = G2Link(host, 'calibration')     # only its requests (no markers, no recording)
    link = None
    if devices.get('video'):
        link = glasses_link(devices['video'])      # the menu hidden from here to the end
        if link is None and '--no-display' not in sys.argv:
            return 3
    screen = Screen()
    outcome = [1]

    def run():
        try:
            outcome[0] = _steps(g2, host, devices, link, screen)
        except Exception as error:      # shown, and the window still closes
            print('Error: %r' % (error,))
            STATE['error'] = repr(error)
        title, ok, sections = report()
        try:
            if not screen.aborted:      # the outcome on the monitors: until Enter when it is the last screen
                if outcome[0] == 0 and '--validate' in sys.argv:
                    screen.report(title, ok, sections, '곧 검증을 시작합니다')
                    screen.wait(RESULT_S)
                else:
                    screen.report(title, ok, sections, 'Enter: 닫기')
                    screen.wait_enter()
        finally:
            if link is not None:
                try:
                    link.calib_now('off')       # the menu back
                except OSError:
                    pass
                link.close()
            screen.close()

    threading.Thread(target=run, daemon=True).start()
    screen.root.mainloop()          # Tk in the main thread; the steps close the window at the end
    import g2_report
    g2_report.print_report(*report())
    if screen.aborted:
        print('Stopped (Esc)')
    return outcome[0]


def _steps(g2, host, devices, link, screen):
    calibration = None
    if '--display-only' not in sys.argv:
        calibration = calibrate_glasses2(g2, screen)
        if calibration is None:
            return 2
    else:
        try:
            with open(CALIBRATION_FILE, encoding='utf-8') as handle:
                calibration = json.load(handle).get('ca_id')
        except (OSError, ValueError):
            calibration = None
    if '--no-display' in sys.argv:
        return 0
    if not devices.get('video'):
        print('No video server in devices.json: the glasses display step is skipped')
        return 0
    return 0 if calibrate_display(host, link, calibration, screen) else 3


if __name__ == '__main__':
    sys.exit(main())
