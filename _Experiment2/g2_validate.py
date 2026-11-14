#!/usr/bin/env python

"""
Tobii Pro Glasses 2: how accurate the gaze is after g2_calibrate.py, in degrees, on two kinds of target.

    python g2_validate.py [HOST]          both: the monitors, then the glasses display
    python g2_validate.py --monitor       only the monitors
    python g2_validate.py --display       only the glasses display (Meta Ray-Ban Display)
    python g2_validate.py --quick         short (the re-wear between blocks, menu "빠른 재착용"): the road
                                          target, the three mirror targets and QUICK_DISPLAY_POINTS; the
                                          same limits (no monitor mean: no corners)

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
import re
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
MIRROR_MESSAGE = ('다음 나타나는 점들은 자연스럽게 고개를 돌려 바라보세요',)   # before the first mirror target (2026-11-14: one short line)
MIN_SAMPLES = 20
# pass (the participant's fit is good enough for the experiment), from the 2026-11-11 pilot
PASS_ROAD_DEG = 1.5              # the road target
PASS_MONITOR_MEAN_DEG = 3.0      # the monitor targets (the mirrors: PASS_MIRROR_DEG, each on its own)
# each mirror target (2026-11-14; before, the mirrors were in the mean above, which a bad mirror could
# pass and a bad monitor corner fail): the side mirrors are judged within 1 degree of their glass
# (mirror_aoi.ENTER_DEG) less the validation offset there, the rear-view mirror within 2.5 (a large
# glass, sky around it). Check drives 1113: right 1.3 degrees -> 6 of 6 glances found, 6.6 / 7.7 -> 2 of 13
PASS_MIRROR_DEG = {'left mirror': 4.0, 'rear-view mirror': 5.0, 'right mirror': 4.0}
PASS_DISPLAY_MEDIAN_DEG = 3.0    # the glasses display ("looking at it": the display is about 12 deg)
# the monitors: (name, monitor: -1 left, 0 middle, 1 right, fraction of its width, of its height). The
# middle monitor's centre and corners, then the centre of each mirror's glass as the experiment draws
# it: MIRRORS_FILE (abc_experiment writes it at every block start), else the fractions below (the
# mirrors since 2026-11-13 afternoon; before, 0.60/0.80, 0.28/0.14, 0.935/0.76 were the old mirrors,
# and after the mirrors moved they stayed: the targets 5.5-7.7 degrees off the glass centres, the
# right one outside its glass). For the mirrors the head may turn, as it does while driving.
MONITOR_POINTS = [('road', 0, 0.5, 0.45), ('middle top left', 0, 0.08, 0.15), ('middle top right', 0, 0.92, 0.15),
                  ('middle bottom right', 0, 0.92, 0.85), ('middle bottom left', 0, 0.08, 0.85),
                  ('left mirror', -1, 0.724, 0.746), ('rear-view mirror', 1, 0.130, 0.123),
                  ('right mirror', 1, 0.768, 0.651)]
MIRRORS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mirrors_last.json')
MIRROR_POINT_NAMES = {'left': 'left mirror', 'rear': 'rear-view mirror', 'right': 'right mirror'}
MONITOR_PX = (1920, 1080)
# the HUD's place (2026-11-14): its centre and four corners, in every block's validation (all conditions: the
# same procedure, and the gaze's error there is known). The rectangle as the experiment draws it
# (abc_experiment writes hud_last.json at each block); the gaze on these points makes the HUD's outline
# as this participant's gaze sees it (hud_gaze.json), the way g2_display.json is the glasses display's
HUD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hud_last.json')
HUD_GAZE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hud_gaze.json')
HUD_POINTS = ('hud centre', 'hud top left', 'hud top right', 'hud bottom right', 'hud bottom left')
# --hud: the short check after a block (the road + the HUD points, no display); --post DIR: its
# outline into that block folder (hud_gaze_post.json); --post-last: the newest block folder under Data
HUD_ONLY = '--hud' in sys.argv
# window px per degree on the middle monitor (1920 px across 43 degrees, at its middle)
PX_PER_DEG = MONITOR_PX[0] / 2.0 / math.tan(math.radians(43.0 / 2.0)) * math.pi / 180.0


def hud_rect():
    """The HUD rectangle [x, y, w, h] in window px (hud_last.json), or None."""
    try:
        with open(HUD_FILE, encoding='utf-8') as handle:
            return json.load(handle)['rect_px']
    except (OSError, ValueError, KeyError):
        return None


def hud_points():
    """(name, monitor, fx, fy) of the HUD's centre and corners (HUD_POINTS), [] without hud_last.json."""
    rect = hud_rect()
    if not rect:
        return []
    x, y, w, h = rect
    places = {'hud centre': (x + w / 2.0, y + h / 2.0), 'hud top left': (x, y), 'hud top right': (x + w, y),
              'hud bottom right': (x + w, y + h), 'hud bottom left': (x, y + h)}
    out = []
    for name in HUD_POINTS:
        px, py = places[name]
        monitor = int(px // MONITOR_PX[0]) - 1
        out.append((name, monitor, round(px / MONITOR_PX[0] - (monitor + 1), 4), round(py / MONITOR_PX[1], 4)))
    return out


def hud_outline(results):
    """The HUD outline as the gaze sees it: each corner where it is drawn plus the gaze's error there
    (gaze - target in the scene camera, degrees, to window px at PX_PER_DEG); None unless all four
    corners were measured."""
    rect = hud_rect()
    points = {p['point']: p for p in results or [] if 'gaze_gp' in p}
    if not rect or not all(n in points for n in HUD_POINTS[1:]):
        return None
    x, y, w, h = rect
    drawn = {'hud top left': (x, y), 'hud top right': (x + w, y), 'hud bottom right': (x + w, y + h),
             'hud bottom left': (x, y + h), 'hud centre': (x + w / 2.0, y + h / 2.0)}
    out, offsets = [], {}
    for name in HUD_POINTS:
        p = points.get(name)
        if p is None:
            continue
        dx = (p['gaze_gp'][0] - p['target_gp'][0]) * SCENE_FOV_DEG[0]
        dy = (p['gaze_gp'][1] - p['target_gp'][1]) * SCENE_FOV_DEG[1]
        offsets[name] = [round(dx, 2), round(dy, 2)]
        if name != 'hud centre':
            out.append([round(drawn[name][0] + dx * PX_PER_DEG, 1), round(drawn[name][1] + dy * PX_PER_DEG, 1)])
    return {'rect_px': rect, 'outline_px': out, 'offset_deg': offsets, 'px_per_deg': round(PX_PER_DEG, 2),
            'accuracy_deg': {n: points[n].get('accuracy_deg') for n in HUD_POINTS if n in points}}


def last_block():
    """The newest block folder under Data (with a run.json), or None."""
    best = None
    for root, dirs, files in os.walk(os.path.join(HERE, 'Data')):
        if 'run.json' in files:
            t = os.path.getmtime(os.path.join(root, 'run.json'))
            if best is None or t > best[0]:
                best = (t, root)
    return best and best[1]


def glass_centre(poly):
    """The centroid of a polygon [(x, y)]."""
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        c = x0 * y1 - x1 * y0
        area += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    return cx / (3.0 * area), cy / (3.0 * area)


def mirror_points():
    """MONITOR_POINTS with the mirrors at their glass centres in MIRRORS_FILE (if there), and where
    they came from."""
    try:
        with open(MIRRORS_FILE, encoding='utf-8') as handle:
            mirrors = json.load(handle)['mirrors']
    except (OSError, ValueError, KeyError):
        return MONITOR_POINTS, 'g2_validate.py MONITOR_POINTS (no mirrors_last.json)'
    points = []
    for name, monitor, fx, fy in MONITOR_POINTS:
        key = next((k for k, v in MIRROR_POINT_NAMES.items() if v == name), None)
        if key in mirrors:
            x, y = glass_centre(mirrors[key]['glass'])
            monitor = int(x // MONITOR_PX[0]) - 1
            fx, fy = round(x / MONITOR_PX[0] - (monitor + 1), 4), round(y / MONITOR_PX[1], 4)
        points.append((name, monitor, fx, fy))
    return points, 'mirrors_last.json (%s)' % time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(MIRRORS_FILE)))
TARGET_DIAMETER = 0.045              # the ring's outer diameter, of a monitor's width (32 inch: 32 mm)
# the glasses display (600 x 600 px): not the five points of g2_calibrate.py
DISPLAY_POINTS = [(300, 30), (570, 300), (300, 570), (30, 300), (165, 165), (435, 165), (435, 435), (165, 435)]
# --quick (the re-wear between blocks): the road and the mirrors (no corners), four display points
QUICK = '--quick' in sys.argv
QUICK_POINTS = ('road', 'left mirror', 'rear-view mirror', 'right mirror')
QUICK_DISPLAY_POINTS = [(165, 165), (435, 165), (435, 435), (165, 435)]


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
    found = find_targets(gray, cv2)
    return found[0][1:] if found else None


def find_targets(gray, cv2):
    """Every calibration-like target in a scene frame, best first: [(score, x px, y px)]."""
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 41, 15)
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    found = []
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
        found.append((roundness - abs(hole_area / area - 0.29), m['m10'] / m['m00'], m['m01'] / m['m00']))
    return sorted(found, reverse=True)


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
            window.bind('<Button-3>', lambda e: self._abort())     # a right click: as Esc
            window.bind('<Return>', lambda e: self.enter.set())
            self.canvases.append(canvas)
        self.canvases[len(self.canvases) // 2].winfo_toplevel().focus_force()
        self.aborted = False
        self.enter = threading.Event()      # Enter on the window (wait_enter)
        self._todo = queue.Queue()
        self.root.after(30, self._poll)

    def _abort(self):
        self.aborted = True
        self.enter.set()

    def wait(self, seconds):
        """Waits seconds (Enter cuts it short); False on Esc."""
        self.enter.clear()
        self.enter.wait(seconds)
        self.enter.clear()
        return not self.aborted

    def wait_enter(self):
        """Waits for Enter on the window; False on Esc."""
        self.enter.clear()
        self.enter.wait()
        self.enter.clear()
        return not self.aborted

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
                    canvas.create_text(x, y + 30, text=sub, fill='#444', font=('Malgun Gothic', 22),
                                       anchor='n', justify='center')
        self._call(draw)

    def target(self, point, caption='', diameter=TARGET_DIAMETER):
        """Draws the target at (monitor, x, y) of a MONITOR_POINTS entry (caption: a line under it;
        diameter: the ring's, of the monitor's width); False when that monitor is not there."""
        index, fx, fy = point
        k = len(self.monitors) // 2 + index
        if not 0 <= k < len(self.monitors):
            return False
        left, top, right, bottom = self.monitors[k]
        x, y = fx * (right - left), fy * (bottom - top)
        r = diameter * (right - left) / 2.0

        def draw():
            for canvas in self.canvases:
                canvas.delete('all')
            for radius, colour in ((r, 'black'), (r * 23 / 43.0, 'white'), (r * 3 / 43.0, 'black')):
                self.canvases[k].create_oval(x - radius, y - radius, x + radius, y + radius, fill=colour,
                                             outline=colour)
            if caption:
                self.canvases[k].create_text(x, y + r + 50, text=caption, fill='#333',
                                             font=('Malgun Gothic', 22))
        self._call(draw)
        return True

    def report(self, title, ok, sections, footer='', advice=()):
        """A g2_report report on every monitor (2026-11-14, was all one size and hard to read): the
        verdict big, under it advice (what to do next, its first line in the verdict's colour), the
        first section (the criteria) large with each row in its mark's colour, the others small and
        side by side under it."""
        import tkinter.font as tkfont
        import g2_report

        def draw():
            big = tkfont.Font(family='Malgun Gothic', size=24)
            big_bold = tkfont.Font(family='Malgun Gothic', size=24, weight='bold')
            small = tkfont.Font(family='Malgun Gothic', size=15)
            small_bold = tkfont.Font(family='Malgun Gothic', size=16, weight='bold')
            for canvas, (left, top, right, bottom) in zip(self.canvases, self.monitors):
                canvas.delete('all')
                w, h = right - left, bottom - top

                def table(centre, y, heading, rows, font, bold, whole_row):
                    line = font.metrics('linespace') + (14 if whole_row else 6)
                    gap = 48 if whole_row else 28
                    n = max([len(r) for r in rows] or [0])
                    widths = [max(font.measure(g2_report.cell(r[i])[0]) for r in rows if i < len(r))
                              for i in range(n)]
                    head = heading.split('\n')
                    x = centre - max([sum(widths) + gap * (n - 1)] + [bold.measure(t) for t in head]) / 2.0
                    for k, text in enumerate(head):
                        canvas.create_text(x, y, text=text, anchor='nw', font=bold if k == 0 else font,
                                           fill='black' if k == 0 else '#666666')
                        y += bold.metrics('linespace') + 4
                    y += 6
                    for r in rows:
                        marks = [g2_report.cell(c)[1] for c in r if g2_report.cell(c)[1] is not None]
                        row_mark = marks[-1] if marks else None
                        if whole_row and row_mark is False:   # a failed criterion: a light red band
                            canvas.create_rectangle(x - 16, y - 5, x + sum(widths) + gap * (n - 1) + 16,
                                                    y + line - 9, fill='#fde8e8', outline='')
                        cx = x
                        for i, c in enumerate(r):
                            text, mark = g2_report.cell(c)
                            colour = g2_report.colour(row_mark if whole_row else mark)
                            if not whole_row and mark is None:
                                colour = '#444444'
                            canvas.create_text(cx, y, text=text, anchor='nw',
                                               font=bold if whole_row and i == 0 else font, fill=colour)
                            cx += widths[i] + gap
                        y += line
                    return y

                canvas.create_text(w / 2.0, h * 0.075, text=title, fill=g2_report.colour(ok),
                                   font=('Malgun Gothic', 60, 'bold'))
                y = h * 0.145
                for k, text in enumerate(advice or ()):
                    canvas.create_text(w / 2.0, y, text=text, anchor='n',
                                       fill=g2_report.colour(ok) if k == 0 else '#333333',
                                       font=('Malgun Gothic', 24 if k == 0 else 20, 'bold' if k == 0 else 'normal'))
                    y += 44 if k == 0 else 36
                y += 24
                if sections:
                    y = table(w / 2.0, y, *sections[0], font=big, bold=big_bold, whole_row=True) + 36
                rest = sections[1:]
                for k, section in enumerate(rest):
                    table(w * (k + 0.5) / len(rest), y, *section, font=small, bold=small_bold, whole_row=False)
                if footer:
                    canvas.create_text(w - 40, h - 30, text=footer, anchor='se', fill='#555555', font=('Malgun Gothic', 20))
        self._call(draw)

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
    points, source = mirror_points()
    if QUICK:
        points = [p for p in points if p[0] in QUICK_POINTS]
    if HUD_ONLY:
        points = [p for p in points if p[0] == 'road']
    points = points + hud_points()
    print('\nMonitors: the participant looks at the dot of each target (%d targets, %.0f s); the mirrors from %s'
          % (len(points), len(points) * (SETTLE_S + COLLECT_S), source))
    for name, monitor, fx, fy in points:
        if 'mirror' in name:
            print('  %-17s monitor %+d at %.3f, %.3f' % (name, monitor, fx, fy))
    screen.message('이제 모니터를 보세요', '점이 나타나면 점의 가운데를 봐 주세요')
    glasses_cue(link, '이제 모니터를 보세요')
    still = (time.time() + 0.5, time.time() + MESSAGE_S)    # the head still: the gyroscope's bias
    time.sleep(MESSAGE_S)
    glasses_cue(link)
    shown = []
    told = False
    for point in points:
        if screen.aborted:
            break
        if 'mirror' in point[0] and not told:
            screen.message(*MIRROR_MESSAGE)
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
        out['screen'] = [point[1], point[2], point[3]]   # monitor, fractions: where the target was drawn
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
    dots = QUICK_DISPLAY_POINTS if QUICK else DISPLAY_POINTS
    print('\nGlasses display: the participant looks at each red dot on the glasses display until it moves '
          '(%d dots, %.0f s)' % (len(dots), len(dots) * (SETTLE_S + COLLECT_S)))
    screen.message('이제 글래스를 보세요', '안경 화면의 빨간 점을 따라 봐 주세요')
    glasses_cue(link, '이제 글래스를 보세요')
    time.sleep(MESSAGE_S)
    shown = []
    try:
        for x, y in dots:
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


POINT_NAMES = {'road': '도로 중앙', 'middle top left': '모니터 왼쪽 위', 'middle top right': '모니터 오른쪽 위',
               'middle bottom right': '모니터 오른쪽 아래', 'middle bottom left': '모니터 왼쪽 아래',
               # the mirror points by where they are on the side monitors (setup wording: no "미러")
               'left mirror': '왼쪽 사이드 모니터', 'rear-view mirror': '오른쪽 사이드 모니터 위',
               'right mirror': '오른쪽 사이드 모니터 아래',
               # the HUD's place (judged by nothing: its outline for the analysis, hud_gaze.json)
               'hud centre': '계기판 위 영상 자리 가운데', 'hud top left': '영상 자리 왼쪽 위',
               'hud top right': '영상 자리 오른쪽 위', 'hud bottom right': '영상 자리 오른쪽 아래',
               'hud bottom left': '영상 자리 왼쪽 아래'}
DISPLAY_NAMES = {(300, 30): '위', (570, 300): '오른쪽', (300, 570): '아래', (30, 300): '왼쪽',
                 (165, 165): '왼쪽 위', (435, 165): '오른쪽 위', (435, 435): '오른쪽 아래', (165, 435): '왼쪽 아래'}
ERROR_NAMES = {'too few gaze samples': '시선 샘플 부족', 'target not seen by the scene camera': '카메라에 안 보임'}


def point_name(name):
    match = re.match(r'display (\d+),(\d+) px', name)
    if match:
        return DISPLAY_NAMES.get((int(match.group(1)), int(match.group(2))), name)
    return POINT_NAMES.get(name, name)


def _deg(value):
    return '-' if value is None else '%.2f°' % value


def criteria(result):
    """[(criterion, value, limit, passed)] for the parts measured this run."""
    rows = []
    if 'monitor' in result:
        points = {p['point']: p for p in result['monitor'] or []}
        road = points.get('road', {}).get('accuracy_deg')
        rows.append(('도로 중앙', _deg(road), '≤ %.1f°' % PASS_ROAD_DEG, road is not None and road <= PASS_ROAD_DEG))
        # each mirror on its own (2026-11-14): what mirror_aoi.py judges glances by is the error there
        for name, limit in ({} if result.get('hud_only') else PASS_MIRROR_DEG).items():
            value = points.get(name, {}).get('accuracy_deg')
            rows.append((POINT_NAMES.get(name, name), _deg(value) if value is not None else '측정 안 됨',
                         '≤ %.1f°' % limit, value is not None and value <= limit))
        values = [p['accuracy_deg'] for name, p in points.items()
                  if 'mirror' not in name and not name.startswith('hud') and p.get('accuracy_deg') is not None]
        mean = sum(values) / len(values) if values else None
        if not result.get('quick') and not result.get('hud_only'):   # --quick / --hud: no corners
            rows.append(('모니터 평균', _deg(mean), '≤ %.1f°' % PASS_MONITOR_MEAN_DEG,
                         mean is not None and mean <= PASS_MONITOR_MEAN_DEG))
    if 'display' in result:
        median = (result.get('display_summary') or {}).get('accuracy_median_deg')
        rows.append(('안경 화면 중앙값', _deg(median), '≤ %.1f°' % PASS_DISPLAY_MEDIAN_DEG,
                     median is not None and median <= PASS_DISPLAY_MEDIAN_DEG))
    return rows


def judge(result):
    """(passed, reasons) for the parts measured this run, None if none was."""
    rows = criteria(result)
    if not rows:
        return None
    reasons = ['%s %s (%s)' % (name, value, limit) for name, value, limit, ok in rows if not ok]
    return not reasons, reasons


def _points_section(heading, points, s):
    if s:
        heading += '\n평균 %.1f° · 중앙값 %.1f° · 최대 %.1f° · 시선 유효 %.0f%%' % (
            s['accuracy_mean_deg'], s['accuracy_median_deg'], s['accuracy_max_deg'],
            100 * (s['gaze_valid_share'] or 0))
    rows = []
    for p in points or []:
        if 'accuracy_deg' in p:
            rows.append([point_name(p['point']), '%.1f°' % p['accuracy_deg'], '정밀도 %.1f°' % p['s2s_rms_deg']])
        else:
            rows.append([point_name(p['point']), ('×', False), ERROR_NAMES.get(p.get('error'), p.get('error', ''))])
    return heading, rows or [['측정 안 됨']]


def advice(result):
    """What to do next, for the report's top: [the step, the criteria short of their limit]."""
    rows = criteria(result)
    if not rows:
        return []
    failed = [name for name, value, limit, ok in rows if not ok]
    if not failed:
        return ['이대로 블록을 시작합니다']
    if result.get('quick'):
        step = '다시: 메뉴 "빠른 재착용" (안 되면 착용 점검 → 캘리브레이션 + 검증)'
    elif all(name.startswith('안경 화면') for name in failed):
        step = '안경 화면만 다시: 메뉴 "안경 화면 보정만"'
    else:
        step = '다시: 착용 점검 → 캘리브레이션 + 검증'
    return [step, '미달 %d개: %s' % (len(failed), ', '.join(failed))]


def report(result):
    """The run's result as a g2_report report (title, ok, sections)."""
    verdict = judge(result)
    title = '검증 끝' if verdict is None else ('통과' if verdict[0] else '다시 착용')
    sections = [('판정 기준', [[name, value, limit, ('통과' if ok else '미달', ok)]
                               for name, value, limit, ok in criteria(result)])]
    if 'monitor' in result:
        sections.append(_points_section('모니터 점', result['monitor'], result.get('monitor_summary')))
    if 'display' in result:
        sections.append(_points_section('안경 화면 점', result['display'], result.get('display_summary')))
    return title, None if verdict is None else verdict[0], sections


def show_result(screen, result):
    """The result on the monitors until Enter (or Esc)."""
    title, ok, sections = report(result)
    screen.report(title, ok, sections, 'Enter: 닫기', advice(result))
    screen.wait_enter()


def run(host, devices, out_dir, screen, result):
    link = None
    try:
        from g2_calibrate import glasses_link      # the menu hidden (calib blank) until the end
        link = glasses_link(devices['video']) if devices.get('video') else None
        if '--display' not in sys.argv:
            result['monitor'], valid = validate_monitor(host, out_dir, screen, link)
            # the summary of the monitor and mirror points (the HUD points are for its outline)
            result['monitor_summary'] = summary([p for p in result['monitor'] or []
                                                 if not p['point'].startswith('hud')], valid)
            result['hud_gaze'] = hud_outline(result['monitor'])
        if '--monitor' not in sys.argv and not HUD_ONLY and not screen.aborted:
            if link is None:
                print('No glasses app: the glasses display check is skipped')
            else:
                result['display'], valid = validate_display(host, out_dir, screen, link)
                result['display_summary'] = summary(result['display'], valid)
        if not screen.aborted:
            show_result(screen, result)
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
    if '--post' in sys.argv and sys.argv.index('--post') + 1 < len(sys.argv):
        args.remove(sys.argv[sys.argv.index('--post') + 1])
    with open(os.path.join(HERE, 'devices.json'), encoding='utf-8') as handle:
        devices = json.load(handle)
    host = args[0] if args else devices['g2']
    out_dir = os.path.join(VALIDATION_DIR, time.strftime('%y%m%d_%H%M%S'))
    os.makedirs(out_dir, exist_ok=True)
    result = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'scene_fov_deg': list(SCENE_FOV_DEG),
              'settle_s': SETTLE_S, 'collect_s': COLLECT_S}
    if QUICK:
        result['quick'] = True       # the short check: road, mirrors, QUICK_DISPLAY_POINTS
    if HUD_ONLY:
        result['hud_only'] = True    # after a block: the road and the HUD points
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
    verdict = judge(result)
    if verdict is not None:
        result['pass'], result['pass_reasons'] = verdict
    if 'monitor' in result or 'display' in result:
        import g2_report
        g2_report.print_report(*report(result))
    if screen.aborted:
        print('Stopped (Esc)')
    with open(os.path.join(out_dir, 'g2_validation.json'), 'w', encoding='utf-8') as handle:
        json.dump(result, handle, indent=1)
    if result.get('hud_gaze'):
        hud = dict(result['hud_gaze'], time=result['time'], validation=os.path.basename(out_dir))
        post = None
        if '--post-last' in sys.argv:
            post = last_block()
        elif '--post' in sys.argv and sys.argv.index('--post') + 1 < len(sys.argv):
            post = sys.argv[sys.argv.index('--post') + 1]
        path = os.path.join(post, 'hud_gaze_post.json') if post else HUD_GAZE_FILE
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(hud, handle, indent=1)
        print('HUD outline as the gaze sees it -> %s' % path)
    elif HUD_ONLY or hud_rect() is None:
        print('No HUD outline (%s)' % ('no hud_last.json: run a block once' if hud_rect() is None
                                       else 'its corners were not all measured'))
    if HUD_ONLY:          # the block's after-check: not the participant's validation (RESULT_FILE)
        return 0 if result.get('hud_gaze') else 3
    # RESULT_FILE keeps the other part from the last run when only one was measured (--monitor,
    # --display): it goes into each block's data folder
    latest = dict(result)
    if '--monitor' in sys.argv or '--display' in sys.argv:
        try:
            with open(RESULT_FILE, encoding='utf-8') as handle:
                before = json.load(handle)
        except (OSError, ValueError):
            before = {}
        for part in ('monitor', 'display'):
            if part not in result and part in before:
                latest[part] = before[part]
                latest[part + '_summary'] = before.get(part + '_summary')
                latest[part + '_time'] = before.get(part + '_time', before.get('time'))
    for part in ('monitor', 'display'):
        if part in result:
            latest[part + '_time'] = result['time']
    with open(RESULT_FILE, 'w', encoding='utf-8') as handle:
        json.dump(latest, handle, indent=1)
    print('-> %s' % RESULT_FILE)
    return 0 if result.get('monitor_summary') or result.get('display_summary') else 3


if __name__ == '__main__':
    sys.exit(main())
