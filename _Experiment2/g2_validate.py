#!/usr/bin/env python

"""
Tobii Pro Glasses 2: how accurate the gaze is after g2_calibrate.py, in degrees, on two kinds of target.

    python g2_validate.py [HOST]          both: the monitors, then the glasses display
    python g2_validate.py --monitor       only the monitors
    python g2_validate.py --display       only the glasses display (Meta Ray-Ban Display)

The glasses' live streams are saved meanwhile (g2_stream.py) in VALIDATION_DIR/<time>/, the result in
there and in RESULT_FILE (the latest, copied into each block's data folder by abc_experiment).

A white window over all the monitors guides the participant: "이제 모니터를 보세요" before the
monitor targets, "이제 글래스를 보세요" before the glasses display's dots (that one on the glasses
too, as the app's alert text, MESSAGE_S each). Esc on the window stops.

1. Monitors. A target like the calibration one (black ring, white disc, black dot) at MONITOR_POINTS
   in turn: the middle monitor's centre and corners, then where the experiment's side and rear-view
   mirrors are. The participant looks at the dot of each target until it moves (SETTLE_S + COLLECT_S);
   for the mirrors the head may turn, as while driving. The glasses app stays blank (its menu hidden). Ground truth: where the target is in each scene camera frame
   (found in the video), so a head movement does not count as an error; the gaze sample nearest each
   frame (glasses clock) is compared with it. A target the scene camera does not see is reported as
   such. Needs OpenCV (pip install opencv-python-headless).

2. Glasses display. The app (mrbd-video) shows a dot at DISPLAY_POINTS, points g2_calibrate.py did not
   use: the middle of each edge and four points between the centre and the corners. Ground truth:
   where g2_display.json's outline puts that point in the scene camera (a homography from its four
   corners). So this error is the gaze's error plus the outline's, and grows when either pair of
   glasses moved on the nose since g2_calibrate.py.

Degrees from gaze point gp (0..1 of the scene camera) with a pinhole camera of SCENE_FOV_DEG (the
Glasses 2 scene camera, 82 x 52 degrees; its lens distortion is left out, so near the edges of the
view the degrees are a few percent off). Per point: accuracy = the angle between the median gaze and the
target; precision = the RMS of the angle between consecutive gaze samples (RMS-S2S) and the SD of the
gaze around its median.
"""

from __future__ import print_function

import ctypes
import ctypes.wintypes
import json
import math
import os
import queue
import statistics
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VALIDATION_DIR = os.path.join(HERE, 'g2_validation')
RESULT_FILE = os.path.join(HERE, 'g2_validation.json')
DISPLAY_FILE = os.path.join(HERE, 'g2_display.json')
SCENE_FOV_DEG = (82.0, 52.0)
SCENE_PX = (960, 540)                # the live scene video
SETTLE_S = 1.0                       # s after a target appears before its gaze counts
COLLECT_S = 1.5                      # s of gaze per target
MESSAGE_S = 3.0                      # s of "이제 ... 보세요" before each part
MIRROR_MESSAGE = '미러는 운전할 때처럼 고개를 돌려서 보세요'   # before the first mirror target
MIN_SAMPLES = 20
# the monitors: (name, monitor: -1 left, 0 middle, 1 right, fraction of its width, of its height). The
# middle monitor's centre and corners, then where the experiment's mirrors are (abc_experiment's driver
# view over 3 x 1920 x 1080, measured on its screen snapshot): for those the head may turn, as it does
# while driving
MONITOR_POINTS = [('road', 0, 0.5, 0.45), ('middle top left', 0, 0.08, 0.15), ('middle top right', 0, 0.92, 0.15),
                  ('middle bottom right', 0, 0.92, 0.85), ('middle bottom left', 0, 0.08, 0.85),
                  ('left mirror', -1, 0.60, 0.80), ('rear-view mirror', 1, 0.50, 0.14),
                  ('right mirror', 1, 0.935, 0.76)]
TARGET_DIAMETER = 0.045              # the ring's outer diameter, of a monitor's width (32 inch: 32 mm)
# the glasses display (600 x 600 px): not the five points of g2_calibrate.py
DISPLAY_POINTS = [(300, 30), (570, 300), (300, 570), (30, 300), (165, 165), (435, 165), (435, 435), (165, 435)]


# ---------------------------------------------------------------- geometry
def ray(x, y):
    tx = math.tan(math.radians(SCENE_FOV_DEG[0] / 2.0))
    ty = math.tan(math.radians(SCENE_FOV_DEG[1] / 2.0))
    v = ((x - 0.5) * 2.0 * tx, (y - 0.5) * 2.0 * ty, 1.0)
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def angle(a, b):
    """Degrees between gaze points a and b (gp, 0..1)."""
    ra, rb = ray(*a), ray(*b)
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(p * q for p, q in zip(ra, rb))))))


def homography(src, dst):
    import numpy as np
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    h = np.linalg.svd(np.array(rows, dtype=float))[2][-1]
    return (h / h[-1]).reshape(3, 3)


def apply(h, x, y):
    u, v, w = h.dot([x, y, 1.0])
    return u / w, v / w


def precision(points):
    s2s = [angle(points[i], points[i + 1]) for i in range(len(points) - 1)]
    mx = statistics.median(p[0] for p in points)
    my = statistics.median(p[1] for p in points)
    dev = [angle(p, (mx, my)) for p in points]
    return (math.sqrt(sum(d * d for d in s2s) / len(s2s)) if s2s else None,
            math.sqrt(sum(d * d for d in dev) / len(dev)) if dev else None)


# ---------------------------------------------------------------- the glasses' streams
class Recording(object):
    """g2_stream.py into a folder; after stop(): gaze samples and the sync."""

    def __init__(self, host, out_dir):
        self.dir = out_dir
        self._proc = subprocess.Popen([sys.executable, os.path.join(HERE, 'g2_stream.py'), host, out_dir],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def stop(self):
        try:
            self._proc.communicate(b'stop\n', timeout=20)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        with open(os.path.join(self.dir, 'g2_sync.json'), encoding='utf-8') as handle:
            self.sync = json.load(handle)
        self.gaze = []                  # (glasses ts us, PC time, x, y): valid gp samples
        self.gyro = []                  # (glasses ts us, [x, y, z] deg/s): the head unit's gyroscope
        self.gaze_packets = 0
        with open(os.path.join(self.dir, 'g2_data.jsonl'), encoding='utf-8') as handle:
            for line in handle:
                pc, _, text = line.partition(' ')
                try:
                    p = json.loads(text)
                except ValueError:
                    continue
                if 'gy' in p and p.get('s') == 0:
                    self.gyro.append((p['ts'], p['gy']))
                if 'gp' in p:
                    self.gaze_packets += 1
                    if p.get('s') == 0:
                        self.gaze.append((p['ts'], float(pc), p['gp'][0], p['gp'][1]))
        self.gaze.sort()
        self.gyro.sort()

    def head_rotation(self, still, start):
        """The head's rotation (deg about the head unit's x, y, z) from PC time start on, as a function of
        glasses ts: the gyroscope less its bias (its median while the head is still, PC times still[0]..
        still[1]) summed up. Drifts by a degree or so over half a minute."""
        t0, t1 = self.pc_to_ts(still[0]), self.pc_to_ts(still[1])
        rest = [g for t, g in self.gyro if t0 <= t <= t1] or [g for _, g in self.gyro[:100]]
        bias = [statistics.median(g[i] for g in rest) for i in range(3)] if rest else [0.0, 0.0, 0.0]
        begin = self.pc_to_ts(start)
        angle_now, prev, series = [0.0, 0.0, 0.0], None, []
        for t, g in self.gyro:
            if t < begin:
                continue
            if prev is not None:
                for i in range(3):
                    angle_now[i] += (g[i] - bias[i]) * (t - prev) / 1e6
            prev = t
            series.append((t, list(angle_now)))
        return series, bias

    def valid_share(self):
        return round(len(self.gaze) / float(self.gaze_packets), 3) if self.gaze_packets else None

    def pc_to_ts(self, pc):
        a, b = self.sync['ts_to_pc']
        return (pc - b) * 1e6 / (1.0 + a * 1e6)

    def gaze_between(self, pc0, pc1):
        t0, t1 = self.pc_to_ts(pc0), self.pc_to_ts(pc1)
        return [(t, x, y) for t, _, x, y in self.gaze if t0 <= t <= t1]


def first_video_pts(path):
    """The first video PTS (90 kHz) in an MPEG-TS file."""
    with open(path, 'rb') as handle:
        data = handle.read(188 * 20000)
    for i in range(0, len(data) - 188, 188):
        pkt = data[i:i + 188]
        if pkt[0] != 0x47 or not pkt[1] & 0x40:
            continue
        start = 4
        if pkt[3] & 0x20:
            start += 1 + pkt[4]
        pes = pkt[start:]
        if len(pes) > 14 and pes[:3] == b'\x00\x00\x01' and 0xE0 <= pes[3] <= 0xEF and pes[7] & 0x80:
            p = pes[9:14]
            return (((p[0] >> 1) & 7) << 30) | (p[1] << 22) | ((p[2] >> 1) << 15) | (p[3] << 7) | (p[4] >> 1)
    return None


def find_target(gray, cv2):
    """The calibration-like target (dark ring around a light disc) in a scene frame: centre px or None."""
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 41, 15)
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return None
    best = None
    for i, (nxt, prev, child, parent) in enumerate(hierarchy[0]):
        if parent != -1 or child == -1:
            continue
        outer = contours[i]
        area = cv2.contourArea(outer)
        if not 60 <= area <= 15000:
            continue
        perimeter = cv2.arcLength(outer, True)
        roundness = 4 * math.pi * area / (perimeter * perimeter) if perimeter else 0
        if roundness < 0.75:
            continue
        hole = max((contours[j] for j in _children(hierarchy[0], child)), key=cv2.contourArea)
        hole_area = cv2.contourArea(hole)
        if not 0.12 <= hole_area / area <= 0.55:
            continue
        m = cv2.moments(hole)
        if not m['m00']:
            continue
        score = roundness - abs(hole_area / area - 0.29)
        if best is None or score > best[0]:
            best = (score, m['m10'] / m['m00'], m['m01'] / m['m00'])
    return best[1:] if best else None


def _children(h, first):
    j = first
    while j != -1:
        yield j
        j = h[j][0]


# ---------------------------------------------------------------- the window over the monitors
def monitors():
    """The monitors' rectangles (left, top, right, bottom), physical px, left to right."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.POINTER(ctypes.wintypes.RECT), ctypes.wintypes.LPARAM)

    def callback(handle, dc, rect, data):
        r = rect.contents
        found.append((r.left, r.top, r.right, r.bottom))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(callback), 0)
    return sorted(found)


class Screen(object):
    """A white window on each monitor (one window over all of them is cut to one monitor by Windows), drawn
    by the Tk thread (the main one); the steps run in another thread and call message() / target() /
    clear() / close()."""

    def __init__(self):
        import tkinter as tk
        self.monitors = monitors()
        self.root = tk.Tk()
        self.root.withdraw()
        self.canvases = []
        for left, top, right, bottom in self.monitors:
            window = tk.Toplevel(self.root)
            window.overrideredirect(True)
            window.geometry('%dx%d%+d%+d' % (right - left, bottom - top, left, top))
            window.configure(background='white', cursor='none')
            window.attributes('-topmost', True)
            canvas = tk.Canvas(window, width=right - left, height=bottom - top, background='white',
                               highlightthickness=0)
            canvas.pack()
            window.bind('<Escape>', lambda e: self._abort())
            self.canvases.append(canvas)
        self.canvases[len(self.canvases) // 2].winfo_toplevel().focus_force()
        self.aborted = False
        self._todo = queue.Queue()
        self.root.after(30, self._poll)

    def _abort(self):
        self.aborted = True

    def _poll(self):
        try:
            while True:
                job = self._todo.get_nowait()
                if job is None:
                    self.root.destroy()
                    return
                job()
        except queue.Empty:
            pass
        self.root.after(15, self._poll)

    def _call(self, job):
        """Runs job in the Tk thread and waits for it."""
        done = threading.Event()

        def run():
            job()
            self.root.update_idletasks()
            done.set()

        self._todo.put(run)
        done.wait(5)

    def message(self, text, sub=''):
        def draw():
            for canvas, (left, top, right, bottom) in zip(self.canvases, self.monitors):
                canvas.delete('all')
                x, y = (right - left) / 2.0, (bottom - top) / 2.0
                canvas.create_text(x, y - 20, text=text, fill='black', font=('Malgun Gothic', 44, 'bold'))
                if sub:
                    canvas.create_text(x, y + 50, text=sub, fill='#444', font=('Malgun Gothic', 22))
        self._call(draw)

    def target(self, point):
        """Draws the target at (monitor, x, y) of a MONITOR_POINTS entry; False when that monitor is not there."""
        index, fx, fy = point
        k = len(self.monitors) // 2 + index
        if not 0 <= k < len(self.monitors):
            return False
        left, top, right, bottom = self.monitors[k]
        x, y = fx * (right - left), fy * (bottom - top)
        r = TARGET_DIAMETER * (right - left) / 2.0

        def draw():
            for canvas in self.canvases:
                canvas.delete('all')
            for radius, colour in ((r, 'black'), (r * 23 / 43.0, 'white'), (r * 3 / 43.0, 'black')):
                self.canvases[k].create_oval(x - radius, y - radius, x + radius, y + radius, fill=colour,
                                             outline=colour)
        self._call(draw)
        return True

    def clear(self):
        self._call(lambda: [canvas.delete('all') for canvas in self.canvases])

    def close(self):
        self._todo.put(None)


def glasses_cue(link, text=None):
    """The glasses app blank (its menu hidden), with a line of guidance or none."""
    if link is None:
        return
    try:
        link.calib_now('blank', text)
    except OSError:
        pass


# ---------------------------------------------------------------- 1. the monitors
def validate_monitor(host, out_dir, screen, link):
    try:
        import cv2
    except ImportError:
        print('The monitor check needs OpenCV: python -m pip install opencv-python-headless')
        return None, None
    rec = Recording(host, os.path.join(out_dir, 'monitor'))
    print('\nMonitors: the participant looks at the dot of each target (%d targets, %.0f s)'
          % (len(MONITOR_POINTS), len(MONITOR_POINTS) * (SETTLE_S + COLLECT_S)))
    screen.message('이제 모니터를 보세요', '점이 나타나면 점의 가운데를 봐 주세요')
    glasses_cue(link, '이제 모니터를 보세요')
    still = (time.time() + 0.5, time.time() + MESSAGE_S)    # the head still: the gyroscope's bias
    time.sleep(MESSAGE_S)
    glasses_cue(link)
    shown = []
    told = False
    for point in MONITOR_POINTS:
        if screen.aborted:
            break
        if 'mirror' in point[0] and not told:
            screen.message(MIRROR_MESSAGE)
            time.sleep(MESSAGE_S)
            told = True
        if screen.target(point[1:]):
            shown.append((point, time.time()))
            time.sleep(SETTLE_S + COLLECT_S)
    screen.clear()
    time.sleep(0.5)
    rec.stop()
    if 'pts_to_ts' not in rec.sync:
        print('No video sync from the glasses: not measured')
        return None, rec.valid_share()
    video = os.path.join(rec.dir, 'g2_scene.ts')
    pts0 = first_video_pts(video)
    a, b = rec.sync['pts_to_ts']
    capture = cv2.VideoCapture(video)
    frames = []                         # (glasses ts, target gp or None)
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        pts = pts0 + capture.get(cv2.CAP_PROP_POS_MSEC) * 90.0
        found = find_target(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2)
        frames.append((a * pts + b, None if found is None else (found[0] / SCENE_PX[0], found[1] / SCENE_PX[1])))
    results = []
    rotation, bias = rec.head_rotation(still, shown[0][1] if shown else still[1])
    for point, at in shown:
        t0, t1 = rec.pc_to_ts(at + SETTLE_S), rec.pc_to_ts(at + SETTLE_S + COLLECT_S)
        gaze = [(t, x, y) for t, _, x, y in rec.gaze if t0 <= t <= t1]
        errors, targets = [], []
        for ft, target in frames:
            if not t0 <= ft <= t1 or target is None or not gaze:
                continue
            t, x, y = min(gaze, key=lambda g: abs(g[0] - ft))
            if abs(t - ft) <= 30000:
                errors.append(angle((x, y), target))
                targets.append(target)
        name = point[0]
        out = _point_result(name, gaze, targets, errors, len([1 for ft, _ in frames if t0 <= ft <= t1]))
        turned = [a for t, a in rotation if t0 <= t <= t1]
        if turned:
            # from the first target (the road ahead): which axis is the head's yaw and its sign is
            # the head unit's; read it off a run where the head turned
            out['head_rotation_deg'] = [round(statistics.median(a[i] for a in turned), 1) for i in range(3)]
            out['shown_pc'] = round(at, 3)
            print('  %-22s head rotation from the road target: x %+.1f, y %+.1f, z %+.1f deg'
                  % ('', out['head_rotation_deg'][0], out['head_rotation_deg'][1], out['head_rotation_deg'][2]))
        results.append(out)
    return results, rec.valid_share()


def _point_result(name, gaze, targets, errors, frames=None):
    out = {'point': name, 'samples': len(gaze)}
    if frames is not None:
        out['frames'] = frames
        out['frames_with_target'] = len(targets)
    if len(gaze) < MIN_SAMPLES or not errors:
        out['error'] = 'too few gaze samples' if len(gaze) < MIN_SAMPLES else 'target not seen by the scene camera'
        print('  %-22s %s (%d gaze samples%s)' % (name, out['error'], len(gaze),
                                                  ', %d/%d frames' % (len(targets), frames) if frames else ''))
        return out
    pts = [(x, y) for _, x, y in gaze]
    s2s, sd = precision(pts)
    out.update(accuracy_deg=round(statistics.median(errors), 2), s2s_rms_deg=round(s2s, 3), sd_deg=round(sd, 3),
               gaze_gp=[round(statistics.median(p[0] for p in pts), 4), round(statistics.median(p[1] for p in pts), 4)],
               target_gp=[round(statistics.median(t[0] for t in targets), 4),
                          round(statistics.median(t[1] for t in targets), 4)])
    print('  %-22s accuracy %5.2f deg   precision RMS-S2S %.2f, SD %.2f deg   (%d samples)'
          % (name, out['accuracy_deg'], s2s, sd, len(gaze)))
    return out


# ---------------------------------------------------------------- 2. the glasses display
def validate_display(host, out_dir, screen, link):
    try:
        with open(DISPLAY_FILE, encoding='utf-8') as handle:
            display = json.load(handle)
    except (OSError, ValueError):
        print('No %s: run g2_calibrate.py first' % DISPLAY_FILE)
        return None, None
    corners = [display['dots'][d] for d in ('tl', 'tr', 'br', 'bl')]
    h = homography([c['display_px'] for c in corners], [c['gp'] for c in corners])
    rec = Recording(host, os.path.join(out_dir, 'display'))
    print('\nGlasses display: the participant looks at each red dot on the glasses display until it moves '
          '(%d dots, %.0f s)' % (len(DISPLAY_POINTS), len(DISPLAY_POINTS) * (SETTLE_S + COLLECT_S)))
    screen.message('이제 글래스를 보세요', '안경 화면의 빨간 점을 따라 봐 주세요')
    glasses_cue(link, '이제 글래스를 보세요')
    time.sleep(MESSAGE_S)
    shown = []
    try:
        for x, y in DISPLAY_POINTS:
            if screen.aborted:
                break
            link.calib_now('px:%d,%d' % (x, y))
            shown.append(((x, y), time.time()))
            time.sleep(SETTLE_S + COLLECT_S)
    finally:
        glasses_cue(link)
    time.sleep(0.5)
    rec.stop()
    results = []
    for (x, y), at in shown:
        target = apply(h, x, y)
        gaze = rec.gaze_between(at + SETTLE_S, at + SETTLE_S + COLLECT_S)
        errors = [angle((gx, gy), target) for _, gx, gy in gaze]
        results.append(_point_result('display %d,%d px' % (x, y), gaze, [target] * len(errors), errors))
    return results, rec.valid_share()


def summary(results, valid):
    ok = [r for r in results or [] if 'accuracy_deg' in r]
    if not ok:
        return None
    acc = [r['accuracy_deg'] for r in ok]
    return {'points': len(results), 'measured': len(ok), 'accuracy_mean_deg': round(sum(acc) / len(acc), 2),
            'accuracy_median_deg': round(statistics.median(acc), 2), 'accuracy_max_deg': round(max(acc), 2),
            's2s_rms_mean_deg': round(sum(r['s2s_rms_deg'] for r in ok) / len(ok), 3),
            'sd_mean_deg': round(sum(r['sd_deg'] for r in ok) / len(ok), 3), 'gaze_valid_share': valid}


def run(host, devices, out_dir, screen, result):
    link = None
    try:
        from g2_calibrate import glasses_link      # the menu hidden (calib blank) until the end
        link = glasses_link(devices['video']) if devices.get('video') else None
        if '--display' not in sys.argv:
            result['monitor'], valid = validate_monitor(host, out_dir, screen, link)
            result['monitor_summary'] = summary(result['monitor'], valid)
        if '--monitor' not in sys.argv and not screen.aborted:
            if link is None:
                print('No glasses app: the glasses display check is skipped')
            else:
                result['display'], valid = validate_display(host, out_dir, screen, link)
                result['display_summary'] = summary(result['display'], valid)
        screen.message('끝났습니다')
        time.sleep(1.0)
    finally:
        if link is not None:
            try:
                link.calib_now('off')      # the menu back
            except OSError:
                pass
            link.close()
        screen.close()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    with open(os.path.join(HERE, 'devices.json'), encoding='utf-8') as handle:
        devices = json.load(handle)
    host = args[0] if args else devices['g2']
    out_dir = os.path.join(VALIDATION_DIR, time.strftime('%y%m%d_%H%M%S'))
    os.makedirs(out_dir, exist_ok=True)
    result = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'scene_fov_deg': list(SCENE_FOV_DEG),
              'settle_s': SETTLE_S, 'collect_s': COLLECT_S}
    try:
        with open(os.path.join(HERE, 'g2_calibration.json'), encoding='utf-8') as handle:
            result['g2_calibration'] = json.load(handle).get('ca_id')
    except (OSError, ValueError):
        pass
    screen = Screen()
    result['monitors'] = screen.monitors
    worker = threading.Thread(target=run, args=(host, devices, out_dir, screen, result), daemon=True)
    worker.start()
    screen.root.mainloop()          # Tk in the main thread; the worker closes the window at the end
    worker.join(30)
    print()
    for key, name in (('monitor_summary', 'Monitors'), ('display_summary', 'Glasses display')):
        s = result.get(key)
        if s:
            print('%-16s accuracy %.2f deg mean, %.2f median (max %.2f), precision RMS-S2S %.2f / SD %.2f deg, '
                  '%d of %d points, gaze valid %.0f %%'
                  % (name, s['accuracy_mean_deg'], s['accuracy_median_deg'], s['accuracy_max_deg'],
                     s['s2s_rms_mean_deg'], s['sd_mean_deg'], s['measured'], s['points'],
                     100 * (s['gaze_valid_share'] or 0)))
        elif key.split('_')[0] in result:
            print('%-16s not measured' % name)
    if screen.aborted:
        print('Stopped (Esc)')
    for path in (os.path.join(out_dir, 'g2_validation.json'), RESULT_FILE):
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, indent=1)
    print('-> %s' % RESULT_FILE)
    return 0 if result.get('monitor_summary') or result.get('display_summary') else 3


if __name__ == '__main__':
    sys.exit(main())
