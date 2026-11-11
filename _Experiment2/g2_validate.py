#!/usr/bin/env python

"""
Tobii Pro Glasses 2: how accurate the gaze is after g2_calibrate.py, in degrees, on two kinds of target.

    python g2_validate.py [HOST]          both: the monitor, then the glasses display
    python g2_validate.py --monitor       only the monitor
    python g2_validate.py --display       only the glasses display (Meta Ray-Ban Display)

The glasses' live streams are saved meanwhile (g2_stream.py) in VALIDATION_DIR/<time>/, the result in
there and in RESULT_FILE (the latest, copied into each block's data folder by abc_experiment).

1. Monitor. A full-screen window on the main monitor (the middle one) shows a target like the
   calibration one (black ring, white disc, black dot) at MONITOR_POINTS in turn. The participant
   keeps the head still and looks at the dot of each target until it moves (SETTLE_S + COLLECT_S).
   Ground truth: where the target is in each scene camera frame (found in the video), so a head
   movement does not count as an error; the gaze sample nearest each frame (glasses clock) is compared
   with it. Needs OpenCV (pip install opencv-python-headless).

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
import json
import math
import os
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VALIDATION_DIR = os.path.join(HERE, 'g2_validation')
RESULT_FILE = os.path.join(HERE, 'g2_validation.json')
DISPLAY_FILE = os.path.join(HERE, 'g2_display.json')
SCENE_FOV_DEG = (82.0, 52.0)
SCENE_PX = (960, 540)                # the live scene video
SETTLE_S = 1.0                       # s after a target appears before its gaze counts
COLLECT_S = 1.5                      # s of gaze per target
MIN_SAMPLES = 20
# the monitor: fractions of its width and height (the centre first); the scene camera of this setup points
# low, so the rows sit in the lower two thirds
MONITOR_POINTS = [(0.5, 0.6), (0.2, 0.35), (0.5, 0.35), (0.8, 0.35), (0.8, 0.6), (0.8, 0.85),
                  (0.5, 0.85), (0.2, 0.85), (0.2, 0.6)]
TARGET_DIAMETER = 0.045              # the ring's outer diameter, of the monitor width (32 inch: 32 mm)
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
        with open(os.path.join(self.dir, 'g2_data.jsonl'), encoding='utf-8') as handle:
            for line in handle:
                pc, _, text = line.partition(' ')
                try:
                    p = json.loads(text)
                except ValueError:
                    continue
                if 'gp' in p and p.get('s') == 0:
                    self.gaze.append((p['ts'], float(pc), p['gp'][0], p['gp'][1]))
        self.gaze.sort()

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


# ---------------------------------------------------------------- 1. the monitor
def show_monitor_targets(points):
    """A full-screen window on the main monitor with each target in turn: [(point, PC time shown)]."""
    import tkinter as tk
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    root.configure(background='white', cursor='none')
    root.attributes('-fullscreen', True)
    root.attributes('-topmost', True)
    w, h = root.winfo_screenwidth(), root.winfo_screenheight()
    canvas = tk.Canvas(root, width=w, height=h, background='white', highlightthickness=0)
    canvas.pack()
    r = TARGET_DIAMETER * w / 2.0
    shown = []

    def draw(k):
        canvas.delete('all')
        if k >= len(points):
            root.after(300, root.destroy)
            return
        x, y = points[k][0] * w, points[k][1] * h
        for radius, colour in ((r, 'black'), (r * 23 / 43.0, 'white'), (r * 3 / 43.0, 'black')):
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=colour, outline=colour)
        root.update_idletasks()
        shown.append((points[k], time.time()))
        root.after(int((SETTLE_S + COLLECT_S) * 1000), lambda: draw(k + 1))

    root.after(1500, lambda: draw(0))   # the window settles first
    root.mainloop()
    return shown


def validate_monitor(host, out_dir):
    try:
        import cv2
    except ImportError:
        print('The monitor check needs OpenCV: python -m pip install opencv-python-headless')
        return None
    rec = Recording(host, os.path.join(out_dir, 'monitor'))
    time.sleep(1.0)
    print('\nMonitor: the participant keeps the head still and looks at the dot of each target on the main '
          'monitor (%d targets, %.0f s)' % (len(MONITOR_POINTS), len(MONITOR_POINTS) * (SETTLE_S + COLLECT_S)))
    shown = show_monitor_targets(MONITOR_POINTS)
    time.sleep(0.5)
    rec.stop()
    if 'pts_to_ts' not in rec.sync:
        print('No video sync from the glasses: not measured')
        return None
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
        results.append(_point_result('monitor %.2f,%.2f' % point, gaze, targets, errors,
                                     len([1 for ft, _ in frames if t0 <= ft <= t1])))
    return results


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
def validate_display(host, video_address, out_dir):
    from video_link import VideoLink
    try:
        with open(DISPLAY_FILE, encoding='utf-8') as handle:
            display = json.load(handle)
    except (OSError, ValueError):
        print('No %s: run g2_calibrate.py first' % DISPLAY_FILE)
        return None
    corners = [display['dots'][d] for d in ('tl', 'tr', 'br', 'bl')]
    h = homography([c['display_px'] for c in corners], [c['gp'] for c in corners])
    link = VideoLink(video_address)
    try:
        delivered = link._post('/api/control', {'action': 'calib', 'dot': 'off'}).get('delivered', 0)
    except OSError as error:
        print('The video server at %s is not reached (%s)' % (link.base, error))
        return None
    if not delivered:
        print('The glasses app is not connected to %s: open it on the glasses' % link.base)
        return None
    rec = Recording(host, os.path.join(out_dir, 'display'))
    time.sleep(1.0)
    print('\nGlasses display: the participant looks at each red dot on the glasses display until it moves '
          '(%d dots, %.0f s)' % (len(DISPLAY_POINTS), len(DISPLAY_POINTS) * (SETTLE_S + COLLECT_S)))
    shown = []
    try:
        for x, y in DISPLAY_POINTS:
            link._post('/api/control', {'action': 'calib', 'dot': 'px:%d,%d' % (x, y)})
            shown.append(((x, y), time.time()))
            time.sleep(SETTLE_S + COLLECT_S)
    finally:
        link._post('/api/control', {'action': 'calib', 'dot': 'off'})
        link.close()
    time.sleep(0.5)
    rec.stop()
    results = []
    for (x, y), at in shown:
        target = apply(h, x, y)
        gaze = rec.gaze_between(at + SETTLE_S, at + SETTLE_S + COLLECT_S)
        errors = [angle((gx, gy), target) for _, gx, gy in gaze]
        targets = [target] * len(errors)
        results.append(_point_result('display %d,%d px' % (x, y), gaze, targets, errors))
    return results


def summary(results):
    ok = [r for r in results or [] if 'accuracy_deg' in r]
    if not ok:
        return None
    acc = [r['accuracy_deg'] for r in ok]
    return {'points': len(results), 'measured': len(ok), 'accuracy_mean_deg': round(sum(acc) / len(acc), 2),
            'accuracy_max_deg': round(max(acc), 2),
            's2s_rms_mean_deg': round(sum(r['s2s_rms_deg'] for r in ok) / len(ok), 3),
            'sd_mean_deg': round(sum(r['sd_deg'] for r in ok) / len(ok), 3)}


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
    if '--display' not in sys.argv:
        result['monitor'] = validate_monitor(host, out_dir)
        result['monitor_summary'] = summary(result['monitor'])
    if '--monitor' not in sys.argv:
        if devices.get('video'):
            result['display'] = validate_display(host, devices['video'], out_dir)
            result['display_summary'] = summary(result['display'])
        else:
            print('No video server in devices.json: the glasses display check is skipped')
    print()
    for key, name in (('monitor_summary', 'Monitor'), ('display_summary', 'Glasses display')):
        s = result.get(key)
        if s:
            print('%-16s accuracy %.2f deg mean (max %.2f), precision RMS-S2S %.2f / SD %.2f deg, %d of %d points'
                  % (name, s['accuracy_mean_deg'], s['accuracy_max_deg'], s['s2s_rms_mean_deg'], s['sd_mean_deg'],
                     s['measured'], s['points']))
        elif key.split('_')[0] in result:
            print('%-16s not measured' % name)
    for path in (os.path.join(out_dir, 'g2_validation.json'), RESULT_FILE):
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, indent=1)
    print('-> %s' % RESULT_FILE)
    return 0 if result.get('monitor_summary') or result.get('display_summary') else 3


if __name__ == '__main__':
    sys.exit(main())
