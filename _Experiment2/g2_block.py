#!/usr/bin/env python

"""
A block's Glasses 2 recording (abc_experiment.py --g2: g2_scene.ts, g2_data.jsonl, g2_sync.json,
frames.csv): the clocks lined up (video ms -> glasses ts -> PC time -> block time), the gaze point and
the eyes' angles at a moment, and what the gaze analyses share: joining frames on one mirror into
glances, and the per event window table (mirror_aoi.py, gaze_video.py, mirror_check.py).
"""

from __future__ import print_function

import bisect
import csv
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MIRRORS = ('left', 'rear', 'right')
AOI = {'left_mirror': 'left', 'rear_mirror': 'rear', 'right_mirror': 'right'}
SCENE_PX = (960, 540)       # the scene video (the live stream)
STEP = 3                    # every 3rd frame of the video (50 fps: 0.06 s)
GAZE_DT = 0.02              # s: the gaze samples within this of a frame make its gaze point
GAP_S = 0.25                # s: a gap this short between two frames on the same mirror is one glance


class Run(object):
    def __init__(self, folder):
        sys.path.insert(0, HERE)
        import g2_validate  # pylint: disable=import-outside-toplevel
        self.dir = folder
        self.video = os.path.join(folder, 'g2_scene.ts')
        with open(os.path.join(folder, 'g2_sync.json'), encoding='utf-8') as handle:
            sync = json.load(handle)
        if 'pts_to_ts' not in sync:
            raise SystemExit('No video sync in g2_sync.json')
        self.a, self.b = sync['ts_to_pc']
        self.pa, self.pb = sync['pts_to_ts']
        self.pts0 = g2_validate.first_video_pts(self.video)
        self.ft, self.fw = [], []
        with open(os.path.join(folder, 'frames.csv'), encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                self.ft.append(float(row['t_sim']))
                self.fw.append(float(row['wall_time']))
        self.gaze_ts, self.gaze = [], []
        samples = {}   # gidx: [ts of its gp, gp or None, [gd of the eyes]]
        with open(os.path.join(folder, 'g2_data.jsonl'), encoding='utf-8') as handle:
            for line in handle:
                _, _, text = line.partition(' ')
                try:
                    p = json.loads(text)
                except ValueError:
                    continue
                if 'gp' in p and p.get('s') == 0:
                    self.gaze.append((p['ts'], p['gp'][0], p['gp'][1]))
                if 'gidx' in p and ('gp' in p or 'gd' in p):
                    s = samples.setdefault(p['gidx'], [None, None, []])
                    if 'gp' in p:
                        s[0] = p['ts']
                        s[1] = p['gp'] if p.get('s') == 0 else None
                    elif p.get('s') == 0:
                        s[2].append(p['gd'])
        self.gaze.sort()
        self.gaze_ts = [g[0] for g in self.gaze]
        # the eyes' direction in the head (the mean of the eyes tracked; Glasses 2: x to the wearer's
        # left, y up, z ahead): yaw (left > 0), pitch (up > 0) in degrees. Still there past about 42
        # degrees, where Glasses 2 has no gaze point any more
        self.eye = []
        for ts, gp, gds in samples.values():
            if ts is None or not gds:
                continue
            x, y, z = np.mean(gds, axis=0)
            if z > 0:
                self.eye.append((ts, math.degrees(math.atan2(x, z)), math.degrees(math.atan2(y, z)), gp))
        self.eye.sort(key=lambda e: e[0])
        self.eye_ts = [e[0] for e in self.eye]

    def ts_of_msec(self, msec):
        return self.pa * (self.pts0 + msec * 90.0) + self.pb

    def pc_of_ts(self, ts):
        return ts / 1e6 + self.a * ts + self.b

    def msec_of_pc(self, w):
        return ((w - self.b) / (1e-6 + self.a) - self.pb) / self.pa / 90.0 - self.pts0 / 90.0

    def sim_of_pc(self, w):
        i = min(max(bisect.bisect_left(self.fw, w), 1), len(self.fw) - 1)
        w0, w1 = self.fw[i - 1], self.fw[i]
        return self.ft[i - 1] + (self.ft[i] - self.ft[i - 1]) * ((w - w0) / (w1 - w0) if w1 > w0 else 0.0)

    def in_block(self, w):
        return self.fw[0] <= w <= self.fw[-1]

    def gaze_at(self, ts):
        """Median gaze point (scene px, maybe off the frame) of the samples within GAZE_DT of ts, None if none."""
        i0 = bisect.bisect_left(self.gaze_ts, ts - GAZE_DT * 1e6)
        i1 = bisect.bisect_right(self.gaze_ts, ts + GAZE_DT * 1e6)
        if i1 <= i0:
            return None
        xs = sorted(g[1] for g in self.gaze[i0:i1])
        ys = sorted(g[2] for g in self.gaze[i0:i1])
        return xs[len(xs) // 2] * SCENE_PX[0], ys[len(ys) // 2] * SCENE_PX[1]

    def eye_at(self, ts):
        """Median eye (yaw, pitch) degrees of the samples within GAZE_DT of ts, None if none."""
        i0 = bisect.bisect_left(self.eye_ts, ts - GAZE_DT * 1e6)
        i1 = bisect.bisect_right(self.eye_ts, ts + GAZE_DT * 1e6)
        if i1 <= i0:
            return None
        return float(np.median([e[1] for e in self.eye[i0:i1]])), float(np.median([e[2] for e in self.eye[i0:i1]]))


def glances(rows):
    """[(mirror, start sim s, end sim s)]: runs of one mirror in rows [(t, mirror or None)], a gap of
    GAP_S or less between two frames on the same mirror bridged."""
    out = []
    for t, mirror in rows:
        if mirror is None:
            continue
        if out and out[-1][0] == mirror and t - out[-1][2] <= GAP_S + 1e-6:
            out[-1][2] = t
        else:
            out.append([mirror, t, t])
    return [tuple(g) for g in out]


def event_windows(folder):
    """[(id, type, AOI mirror, start, end)]: each event's gaze window (gaze_windows.csv) and the TOR
    (alert to the lane change + 2 s, the AOI the side it changed to: tor_events.csv)."""
    windows = []
    path = os.path.join(folder, 'gaze_windows.csv')
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                if row['window_start'] and row['window_end'] and row['aoi'] in AOI:
                    windows.append((row['id'], row['type'], AOI[row['aoi']], float(row['window_start']),
                                    float(row['window_end'])))
    path = os.path.join(folder, 'tor_events.csv')
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                if row.get('t_tor') and row.get('t_lane_change_start'):
                    lane = row.get('chosen_lane')
                    aoi = 'right' if lane == '3' else 'left' if lane == '1' else ''
                    windows.append((row.get('id') or 'TOR', 'TOR', aoi, float(row['t_tor']),
                                    float(row['t_lane_change_start']) + 2.0))
    return windows


def write_windows(folder, name, times, runs, frame_s):
    """name (mirror_aoi_windows.csv): per event window, the AOI mirror glanced or not, the first glance
    after the window start, dwell, the other mirrors' dwell; times: the sim times of the frames looked
    at, runs: the glances [(mirror, start, end)]."""
    windows = event_windows(folder)
    print('\n%-7s %-4s %-6s %-13s %-8s %-10s %-9s %s' % ('event', 'type', 'AOI', 'window s', 'glanced', 'first s',
                                                       'dwell s', 'other mirrors (dwell s)'))
    with open(os.path.join(folder, name), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['id', 'type', 'aoi', 'window_start', 'window_end', 'frames_with_gaze', 'aoi_glanced',
                         'first_glance_after_start_s', 'aoi_dwell_s'] + ['%s_dwell_s' % m for m in MIRRORS])
        for eid, kind, aoi, w0, w1 in windows:
            inside = [(start, end, mirror) for mirror, start, end in runs if end >= w0 and start <= w1]
            dwell = {m: round(sum(min(e, w1) - max(s, w0) + frame_s for s, e, mm in inside if mm == m), 2)
                     for m in MIRRORS}
            first = min((max(s, w0) - w0 for s, e, mm in inside if mm == aoi), default=None)
            n = sum(1 for t in times if w0 <= t <= w1)
            writer.writerow([eid, kind, aoi, w0, w1, n, int(first is not None),
                             '' if first is None else round(first, 2), dwell.get(aoi, '')] + [dwell[m] for m in MIRRORS])
            others = ', '.join('%s %.1f' % (m, dwell[m]) for m in MIRRORS if m != aoi and dwell[m])
            print('%-7s %-4s %-6s %5.1f-%-7.1f %-8s %-10s %-9s %s' % (
                eid, kind, aoi or '-', w0, w1, 'yes' if first is not None else 'no',
                '' if first is None else '%.2f' % first, dwell.get(aoi, ''), others or '-'))
