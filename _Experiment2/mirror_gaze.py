#!/usr/bin/env python

"""
Mirror glances from the Glasses 2 scene video: at each gaze sample, is the gaze on the left, the
rear-view or the right mirror? For one block's data folder (abc_experiment.py --g2, with the scene
video saved: g2_scene.ts, g2_data.jsonl, g2_sync.json, frames.csv).

    python _Experiment2/mirror_gaze.py Data/P01_B1_A_glasses
    python _Experiment2/mirror_gaze.py Data/test/1111230415 --images     also a picture of each glance
    python _Experiment2/mirror_gaze.py Data/test/1111230415 --from-csv   the glances again from an earlier
                                                                         mirror_gaze.csv (no matching, seconds)

How: the mirrors are part of the car (drawn at fixed places on the monitors), but where they are in
the scene video depends on the head. Around the gaze point in a frame (a crop of 340 x 220 px) each
mirror is looked for with its outline from the simulator's own picture (mirror_ref/: the glass, its
thick black housing, what is around it): a template of "light band inside - dark ring - light band
outside", matched over sizes, two aspect ratios (the side monitors at an angle) and +-5 degrees of
head roll. The best match counts when its score is MIN_SCORE or more and the housing is darker than
the glass and the surroundings in MIN_RING of its sides (a light shape with a dark edge somewhere
else, e.g. the HUD bar, fails that), and the gaze is in its glass (MARGIN_PX around it: the gaze
error at the mirrors is 1-4 degrees, 12 px per degree). Frames every STEP-th (50 fps video: every
0.06 s). A glance, once started, goes on with a little less (STAY_*: the gaze at the glass's edge
jitters in and out), and gaps up to GAP_S between frames on the same mirror are bridged.

The left mirror with the eyes only (OFF_*): with the head to the front it is at the frame's left
edge or past it, where Glasses 2 has no gaze point. Then, with the eyes turned far left (gd), the
mirror is looked for in the frame's left strip (whole, or cut by the edge) and the gaze extrapolated
from the eye angles; these frames have gaze_from / edge_match in mirror_gaze.csv, and their count
per glance is in mirror_glances.csv (frames_edge, frames_eye), to check or leave out.

Out, into the data folder:
    mirror_gaze.csv      per frame looked at: sim time, gaze px, the mirror of this frame alone (or
                         empty), the glance's mirror (with the hysteresis), score, ring, distance
    mirror_glances.csv   runs of frames on one mirror (gaps of one frame bridged): start, end, s
    mirror_windows.csv   per event gaze window (gaze_windows.csv) and the TOR (alert to the lane change
                         + 2 s): the AOI mirror glanced or not, first glance after the window start,
                         dwell; the other mirrors' dwell
    mirror_gaze/         with --images: the first frame of each glance with the outline and the gaze
"""

from __future__ import print_function

import argparse
import bisect
import csv
import json
import math
import multiprocessing
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(HERE, 'mirror_ref')
MIRRORS = ('left', 'rear', 'right')
AOI = {'left_mirror': 'left', 'rear_mirror': 'rear', 'right_mirror': 'right'}
SCENE_PX = (960, 540)
STEP = 3                    # every 3rd frame of the video (50 fps from the live stream: 0.06 s)
HALF = (170, 110)           # px: the crop around the gaze
# mirror_ref (a 3840 px wide picture of the 3 monitors) -> scene px, per mirror: the size it has when
# looked at (from the practice drive: the right mirror, at the far end of the right monitor, is nearer
# the eye and larger; a smaller match there is something on the middle monitor)
SCALES = {'left': np.linspace(0.26, 0.42, 5), 'rear': np.linspace(0.22, 0.40, 5), 'right': np.linspace(0.33, 0.49, 5)}
ASPECTS = (0.85, 1.0)
ROLLS = (-5, 0, 5)
MIN_SCORE = {'left': 0.58, 'rear': 0.58, 'right': 0.61}
MIN_RING = 0.6
MARGIN_PX = 15.0
GAZE_DT = 0.02              # s: the gaze samples within this of a frame make its gaze point
# a glance once started (hysteresis): it goes on while the same mirror is still found with a little
# less (score MIN_SCORE - STAY_SCORE_DROP, ring STAY_RING) and the gaze within STAY_MARGIN_PX of its
# glass: at the glass's edge the gaze's jitter (and its 1-4 degree error) no longer splits a glance
STAY_SCORE_DROP = 0.08
STAY_RING = 0.45
STAY_MARGIN_PX = 35.0
GAP_S = 0.25                # s: a gap this short between two frames on the same mirror is one glance
# At and off the frame's left edge (a glance at the left mirror with the eyes only, the head to the
# front): the scene camera ends at about 43 degrees of eye yaw to the left, the left mirror is about
# there, and past the frame's edge Glasses 2 drops the gaze point (gp, gp3) but often still has the
# eyes' directions (gd). With the eye yaw OFF_YAW or more to the left and its pitch in OFF_PITCH, and
# the gaze point within OFF_EDGE_PX of the frame's left edge or none, the left mirror is looked for in
# the frame's left strip (OFF_STRIP_PX; the crop around the gaze is cut by the edge): whole (score
# OFF_MIN_SCORE_WHOLE: at the edge of the lens it is blurred and darker, its ring often not found) or
# cut by the edge (at least OFF_MIN_VISIBLE of it in the frame, score OFF_MIN_SCORE_CUT). Without a
# gaze point it is extrapolated from the eye yaw / pitch (a linear fit of the gaze px on the eye
# angles, per block, from the samples with both at EXTRAP_YAW). The gaze counts within OFF_MARGIN_PX
# of the glass: at the frame's edge the gaze (gp too) is 4-8 degrees off, mostly above the glass
# (test drive 1112112929).
OFF_MIRROR = 'left'
OFF_YAW = 34.0              # degrees of eye yaw to the left (gd x > 0)
OFF_PITCH = (-12.0, 16.0)   # degrees of eye pitch (up > 0): not the dashboard, not the ceiling
OFF_EDGE_PX = 60.0
OFF_STRIP_PX = 360
OFF_MIN_VISIBLE = 0.45
OFF_MIN_SCORE_WHOLE = 0.42
OFF_MIN_SCORE_CUT = 0.6
OFF_CUT_STEP = 8            # px: the cuts of the template at the frame's edge
OFF_MARGIN_PX = 100.0
EXTRAP_YAW = (25.0, 45.0)
EXTRAP_MIN = 200            # samples for the fit, else EXTRAP_DEFAULT (from the test drive 1112112929)
EXTRAP_DEFAULT = ((526.6, -12.10, 0.49), (292.6, 0.52, -10.39))


# -- templates ---------------------------------------------------------------------------------


def build_templates(cv2):
    """{mirror: dict(t, lab, hull, centre)}: lab 1 the glass's inner band, 2 the housing, 3 around it."""
    out = {}
    k = lambda n: np.ones((n, n), np.uint8)
    for name in MIRRORS:
        c = cv2.imread(os.path.join(REF_DIR, name + '.png'), cv2.IMREAD_GRAYSCALE)
        n, lab, stats, _ = cv2.connectedComponentsWithStats((c > 75).astype(np.uint8))
        glass = (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
        glass = cv2.morphologyEx(glass, cv2.MORPH_CLOSE, k(13))
        hull = cv2.convexHull(max(cv2.findContours(glass, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0],
                                  key=cv2.contourArea))
        glass = np.zeros_like(glass)
        cv2.fillPoly(glass, [hull], 1)
        inner = glass - cv2.erode(glass, k(25))
        housing = cv2.morphologyEx((cv2.dilate(glass, k(31)) - glass) & (c < 45), cv2.MORPH_CLOSE, k(7))
        near = cv2.dilate(glass, k(85))
        outer = (near - (cv2.dilate(glass | housing, k(11)) & near)) & (c > 45)
        t = np.zeros(c.shape, np.float32)
        t[inner > 0] = 1.0
        t[outer > 0] = 0.7
        labels = np.zeros(c.shape, np.uint8)
        labels[inner > 0] = 1
        labels[housing > 0] = 2
        labels[outer > 0] = 3
        ys, xs = np.nonzero(labels)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        hull = hull.reshape(-1, 2).astype(np.float32) - [x0, y0]
        out[name] = dict(t=t[y0:y1, x0:x1], lab=labels[y0:y1, x0:x1], hull=hull, centre=hull.mean(0))
    return out


def build_poses(cv2, template, name):
    t, lab = template['t'], template['lab']
    h, w = t.shape
    poses = []
    for s in SCALES[name]:
        for a in ASPECTS:
            for r in ROLLS:
                m = cv2.getRotationMatrix2D((0, 0), r, 1.0)
                m[:, :2] = m[:, :2] @ np.diag([s * a, s])
                corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32) @ m[:, :2].T
                m[:, 2] = -corners.min(0)
                size = tuple(int(v) for v in np.ceil(corners.max(0) - corners.min(0)) + 1)
                labels = cv2.warpAffine(lab, m, size, flags=cv2.INTER_NEAREST)
                poses.append(dict(m=m, t=cv2.warpAffine(t, m, size), mask=(labels > 0).astype(np.uint8),
                                  lab=labels, pose=(round(s, 3), a, r)))
    return poses


def ring_share(labels, patch, centre, n=8):
    """Share of the n sides (angular sectors around the centre) in which the housing is darker than
    the glass's inner band (by 12) and than what is around it (by 8)."""
    ys, xs = np.nonzero(labels)
    sector = ((np.arctan2(ys - centre[1], xs - centre[0]) + math.pi) / (2 * math.pi) * n).astype(int) % n
    values, kinds = patch[ys, xs], labels[ys, xs]
    ok = total = 0
    for k in range(n):
        sel = sector == k
        med = [np.median(values[sel & (kinds == j)]) if np.any(sel & (kinds == j)) else None for j in (1, 2, 3)]
        if med[0] is None or med[1] is None:
            continue
        total += 1
        ok += med[1] < med[0] - 12 and (med[2] is None or med[1] < med[2] - 8)
    return ok / float(total) if total else 0.0


def look(cv2, gray, gx, gy, templates, poses):
    """The mirror under the gaze (gx, gy px) or None, and per mirror (score, ring, distance px, polygon)."""
    height, width = gray.shape
    x0, y0 = max(0, int(gx - HALF[0])), max(0, int(gy - HALF[1]))
    x1, y1 = min(width, int(gx + HALF[0])), min(height, int(gy + HALF[1]))
    crop = gray[y0:y1, x0:x1].astype(np.float32)
    found, detail = None, {}
    for name in MIRRORS:
        best = None
        for p in poses[name]:
            th, tw = p['t'].shape
            if th >= crop.shape[0] or tw >= crop.shape[1]:
                continue
            res = cv2.matchTemplate(crop, p['t'], cv2.TM_CCOEFF_NORMED, mask=p['mask'])
            res[~np.isfinite(res)] = -1.0
            _, value, _, loc = cv2.minMaxLoc(res)
            if best is None or value > best[0]:
                best = (value, loc, p)
        if best is None:
            continue
        value, loc, p = best
        th, tw = p['t'].shape
        patch = crop[loc[1]:loc[1] + th, loc[0]:loc[0] + tw]
        centre = templates[name]['centre'] @ p['m'][:, :2].T + p['m'][:, 2]
        ring = ring_share(p['lab'], patch, centre)
        poly = templates[name]['hull'] @ p['m'][:, :2].T + p['m'][:, 2] + [loc[0] + x0, loc[1] + y0]
        distance = cv2.pointPolygonTest(poly.astype(np.float32), (float(gx), float(gy)), True)
        detail[name] = (value, ring, distance, poly)
        if value >= MIN_SCORE[name] and ring >= MIN_RING and distance >= -MARGIN_PX:
            if found is None or value > detail[found][0]:
                found = name
    return found, detail


def look_edge(cv2, gray, gx, gy, templates, poses, margin):
    """The left mirror at the frame's left edge (whole in the strip or cut by the edge) under the gaze
    (gx, gy px, gx may be < 0): (found, (score, ring, distance px, polygon), 'whole' / 'cut')."""
    name = OFF_MIRROR
    strip = gray[:, :OFF_STRIP_PX].astype(np.float32)
    whole = cut = None   # (score, x, y, cut px, pose)
    for p in poses[name]:
        t, mask = p['t'], p['mask']
        th, tw = t.shape
        if th >= strip.shape[0]:
            continue
        if tw < strip.shape[1]:
            res = cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED, mask=mask)
            res[~np.isfinite(res)] = -1.0
            _, value, _, loc = cv2.minMaxLoc(res)
            if whole is None or value > whole[0]:
                whole = (value, loc[0], loc[1], 0, p)
        area = float(mask.sum())
        for c in range(OFF_CUT_STEP, tw, OFF_CUT_STEP):
            m = np.ascontiguousarray(mask[:, c:])
            if m.sum() < OFF_MIN_VISIBLE * area:
                break
            res = cv2.matchTemplate(strip[:, :tw - c], np.ascontiguousarray(t[:, c:]), cv2.TM_CCOEFF_NORMED, mask=m)
            res[~np.isfinite(res)] = -1.0
            _, value, _, loc = cv2.minMaxLoc(res)
            if cut is None or value > cut[0]:
                cut = (value, 0, loc[1], c, p)
    out = []
    for kind, best in (('whole', whole), ('cut', cut)):
        if best is None:
            continue
        value, x, y, c, p = best
        th, tw = p['t'].shape
        patch = np.zeros((th, tw), np.float32)
        patch[:, c:] = strip[y:y + th, x:x + tw - c]
        labels = p['lab'].copy()
        labels[:, :c] = 0
        centre = templates[name]['centre'] @ p['m'][:, :2].T + p['m'][:, 2]
        ring = ring_share(labels, patch, centre)
        poly = templates[name]['hull'] @ p['m'][:, :2].T + p['m'][:, 2] + [x - c, y]
        distance = cv2.pointPolygonTest(poly.astype(np.float32), (float(gx), float(gy)), True)
        ok = value >= (OFF_MIN_SCORE_WHOLE if kind == 'whole' else OFF_MIN_SCORE_CUT)
        out.append((ok, (value, ring, distance, poly), kind))
    if not out:
        return False, None, ''
    ok, detail, kind = max(out, key=lambda o: (o[0], o[2] == 'whole', o[1][0]))
    return ok and detail[2] >= -margin, detail, kind


# -- the recording -----------------------------------------------------------------------------


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
        # the eyes' direction (the mean of the eyes tracked; Glasses 2: x to the wearer's left, y up,
        # z ahead): yaw (left > 0), pitch (up > 0) in degrees
        self.eye = []
        for ts, gp, gds in samples.values():
            if ts is None or not gds:
                continue
            x, y, z = np.mean(gds, axis=0)
            if z > 0:
                self.eye.append((ts, math.degrees(math.atan2(x, z)), math.degrees(math.atan2(y, z)), gp))
        self.eye.sort(key=lambda e: e[0])
        self.eye_ts = [e[0] for e in self.eye]
        fit = [e for e in self.eye if e[3] is not None and EXTRAP_YAW[0] <= e[1] <= EXTRAP_YAW[1]]
        if len(fit) >= EXTRAP_MIN:
            a = np.array([(1.0, e[1], e[2]) for e in fit])
            self.extrap = tuple(tuple(np.linalg.lstsq(a, np.array([e[3][k] * SCENE_PX[k] for e in fit]), rcond=None)[0])
                                for k in (0, 1))
            self.extrap_n = len(fit)
        else:
            self.extrap, self.extrap_n = EXTRAP_DEFAULT, 0

    def ts_of_msec(self, msec):
        return self.pa * (self.pts0 + msec * 90.0) + self.pb

    def pc_of_ts(self, ts):
        return ts / 1e6 + self.a * ts + self.b

    def sim_of_pc(self, w):
        i = min(max(bisect.bisect_left(self.fw, w), 1), len(self.fw) - 1)
        w0, w1 = self.fw[i - 1], self.fw[i]
        return self.ft[i - 1] + (self.ft[i] - self.ft[i - 1]) * ((w - w0) / (w1 - w0) if w1 > w0 else 0.0)

    def in_block(self, w):
        return self.fw[0] <= w <= self.fw[-1]

    def gaze_at(self, ts):
        """Median gaze point (px) of the samples within GAZE_DT of ts, None if none."""
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

    def extrapolate(self, eye):
        """The gaze px (maybe off the frame) from the eye (yaw, pitch)."""
        return tuple(c[0] + c[1] * eye[0] + c[2] * eye[1] for c in self.extrap)


def _rounded(detail):
    return {k: (round(v[0], 3), round(v[1], 2), round(v[2], 1), v[3].round(1).tolist()) for k, v in detail.items()}


def _work(args):
    """One worker: frames [first, last) of the video, every STEP-th; [(frame, msec, gx, gy, mirror, detail,
    extra)], extra (gaze from 'gp' / 'eye', left-edge match '' / 'whole' / 'cut', eye yaw, eye pitch)."""
    folder, first, last = args
    import cv2  # pylint: disable=import-outside-toplevel
    cv2.setNumThreads(1)
    run = Run(folder)
    templates = build_templates(cv2)
    poses = {name: build_poses(cv2, templates[name], name) for name in MIRRORS}
    capture = cv2.VideoCapture(run.video)
    capture.set(cv2.CAP_PROP_POS_FRAMES, first)
    out = []
    index = first
    while index < last:
        ok = capture.grab()
        if not ok:
            break
        if (index - first) % STEP == 0:
            msec = capture.get(cv2.CAP_PROP_POS_MSEC)
            ts = run.ts_of_msec(msec)
            if not run.in_block(run.pc_of_ts(ts)):
                index += 1
                continue
            gaze, eye = run.gaze_at(ts), run.eye_at(ts)
            edge_eye = eye is not None and eye[0] >= OFF_YAW and OFF_PITCH[0] <= eye[1] <= OFF_PITCH[1]
            if gaze is not None and 0 <= gaze[0] < SCENE_PX[0] and 0 <= gaze[1] < SCENE_PX[1]:
                source = 'gp'
            elif edge_eye and (gaze is None or gaze[0] < OFF_EDGE_PX):
                source = 'eye'
                gaze = run.extrapolate(eye)
            else:
                index += 1
                continue
            _, frame = capture.retrieve()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, detail, edge = None, {}, ''
            if source == 'gp':
                found, detail = look(cv2, gray, gaze[0], gaze[1], templates, poses)
            if found is None and edge_eye and gaze[0] < OFF_EDGE_PX:
                ok, d, kind = look_edge(cv2, gray, gaze[0], gaze[1], templates, poses, OFF_MARGIN_PX)
                if d is not None and (ok or OFF_MIRROR not in detail):
                    detail[OFF_MIRROR] = d
                if ok:
                    found, edge = OFF_MIRROR, kind
            out.append((index, msec, gaze[0], gaze[1], found, _rounded(detail),
                        (source, edge, None if eye is None else round(eye[0], 1),
                         None if eye is None else round(eye[1], 1))))
        index += 1
    return out


def classify(rows):
    """[(t, mirror or None)] per looked-at frame, with the hysteresis: rows [(t, found, detail)],
    detail {mirror: (score, ring, distance px, ...)}; found = the strict per-frame result."""
    out = []
    current = None
    for t, found, detail in rows:
        if current is not None:
            d = detail.get(current)
            stays = d is not None and d[0] != '' and float(d[0]) >= MIN_SCORE[current] - STAY_SCORE_DROP                 and float(d[1]) >= STAY_RING and float(d[2]) >= -STAY_MARGIN_PX
            if not stays or (found and found != current):
                current = found or None
        else:
            current = found or None
        out.append((t, current))
    return out


def glances(rows):
    """[(mirror, start sim s, end sim s)]: runs of one mirror (classify()), a gap of GAP_S or less
    between two frames on the same mirror bridged."""
    out = []
    for t, mirror in rows:
        if mirror is None:
            continue
        if out and out[-1][0] == mirror and t - out[-1][2] <= GAP_S + 1e-6:
            out[-1][2] = t
        else:
            out.append([mirror, t, t])
    return [tuple(g) for g in out]


def read_csv_rows(folder):
    """The frames of an earlier run (mirror_gaze.csv): [(t, found, msec, gx, gy, detail, extra, frame)]."""
    rows = []
    with open(os.path.join(folder, 'mirror_gaze.csv'), encoding='utf-8') as handle:
        for r in csv.DictReader(handle):
            detail = {m: (r['%s_score' % m], r['%s_ring' % m], r['%s_distance_px' % m], None) for m in MIRRORS
                      if r['%s_score' % m] != ''}
            extra = (r.get('gaze_from') or 'gp', r.get('edge_match', ''), r.get('eye_yaw') or None,
                     r.get('eye_pitch') or None)
            rows.append((float(r['t_sim']), r['mirror'] or None, None, float(r['gaze_x_px']), float(r['gaze_y_px']),
                         detail, extra, int(r['frame'])))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder', help='a block data folder (with g2_scene.ts)')
    parser.add_argument('--images', action='store_true', help='a picture of the first frame of each glance')
    parser.add_argument('--workers', type=int, default=max(1, multiprocessing.cpu_count() - 2))
    parser.add_argument('--from-csv', action='store_true',
                        help='no matching: the glances again from the mirror_gaze.csv of an earlier run (fast)')
    args = parser.parse_args()
    import cv2  # pylint: disable=import-outside-toplevel
    folder = os.path.abspath(args.folder)
    run = Run(folder)
    capture = cv2.VideoCapture(run.video)
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    capture.release()
    frame_s = STEP / fps   # s between two looked-at frames: what a glance of one frame lasts
    print('gaze extrapolation off the frame (px = a + b yaw + c pitch): x %s, y %s (%s)' % (
        tuple(round(v, 2) for v in run.extrap[0]), tuple(round(v, 2) for v in run.extrap[1]),
        '%d samples' % run.extrap_n if run.extrap_n else 'default: too few samples'))
    if args.from_csv:
        old = read_csv_rows(folder)
        rows = [r[:7] for r in old]
        indices = [r[7] for r in old]
    else:
        if frames <= 0:
            raise SystemExit('Cannot read %s' % run.video)
        chunk = int(math.ceil(frames / float(args.workers * 4) / STEP)) * STEP
        jobs = [(folder, k, min(frames, k + chunk)) for k in range(0, frames, chunk)]
        print('%d frames, %d jobs on %d workers...' % (frames, len(jobs), args.workers))
        results = []
        with multiprocessing.Pool(args.workers) as pool:
            for k, part in enumerate(pool.imap(_work, jobs)):
                results.extend(part)
                print('\r  %d of %d' % (k + 1, len(jobs)), end='')
        print()
        results.sort()
        rows = [(run.sim_of_pc(run.pc_of_ts(run.ts_of_msec(msec))), found, msec, gx, gy, detail, extra)
                for index, msec, gx, gy, found, detail, extra in results]
        indices = [r[0] for r in results]
    states = classify([(t, found, detail) for t, found, _, _, _, detail, _ in rows])
    with open(os.path.join(folder, 'mirror_gaze.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        # mirror: this frame alone (strict); glance: with the hysteresis (classify), what the glances use;
        # gaze_from: gp (the gaze point) or eye (extrapolated off the frame from the eye angles);
        # edge_match: the left mirror found at the frame's left edge, whole or cut by it
        writer.writerow(['t_sim', 'frame', 'gaze_x_px', 'gaze_y_px', 'mirror', 'glance'] +
                        ['%s_%s' % (m, f) for m in MIRRORS for f in ('score', 'ring', 'distance_px')] +
                        ['gaze_from', 'edge_match', 'eye_yaw', 'eye_pitch'])
        for (t, found, msec, gx, gy, detail, extra), index, (_, state) in zip(rows, indices, states):
            writer.writerow([round(t, 3), index, round(gx, 1), round(gy, 1), found or '', state or ''] +
                            [x for m in MIRRORS for x in (detail.get(m, ('', '', ''))[:3])] +
                            ['' if v is None else v for v in extra])
    runs = glances(states)
    with open(os.path.join(folder, 'mirror_glances.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        # frames_edge: frames of the glance found at the frame's left edge, of which frames_eye with
        # the gaze extrapolated off the frame
        writer.writerow(['mirror', 'start', 'end', 'duration_s', 'frames', 'frames_edge', 'frames_eye'])
        for mirror, start, end in runs:
            inside = [(r, s) for r, (_, s) in zip(rows, states) if start <= r[0] <= end and s == mirror]
            writer.writerow([mirror, round(start, 2), round(end, 2), round(end - start + frame_s, 2), len(inside),
                             sum(1 for r, _ in inside if r[6][1]), sum(1 for r, _ in inside if r[6][0] == 'eye')])
    # the event windows and the TOR
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
    print('\n%-7s %-4s %-6s %-13s %-8s %-10s %-9s %s' % ('event', 'type', 'AOI', 'window s', 'glanced', 'first s',
                                                       'dwell s', 'other mirrors (dwell s)'))
    with open(os.path.join(folder, 'mirror_windows.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['id', 'type', 'aoi', 'window_start', 'window_end', 'frames_with_gaze', 'aoi_glanced',
                         'first_glance_after_start_s', 'aoi_dwell_s'] + ['%s_dwell_s' % m for m in MIRRORS])
        for eid, kind, aoi, w0, w1 in windows:
            inside = [(start, end, mirror) for mirror, start, end in runs if end >= w0 and start <= w1]
            dwell = {m: round(sum(min(e, w1) - max(s, w0) + frame_s for s, e, mm in inside if mm == m), 2)
                     for m in MIRRORS}
            first = min((max(s, w0) - w0 for s, e, mm in inside if mm == aoi), default=None)
            n = sum(1 for t, *_ in rows if w0 <= t <= w1)
            writer.writerow([eid, kind, aoi, w0, w1, n, int(first is not None),
                             '' if first is None else round(first, 2), dwell.get(aoi, '')] + [dwell[m] for m in MIRRORS])
            others = ', '.join('%s %.1f' % (m, dwell[m]) for m in MIRRORS if m != aoi and dwell[m])
            print('%-7s %-4s %-6s %5.1f-%-7.1f %-8s %-10s %-9s %s' % (
                eid, kind, aoi or '-', w0, w1, 'yes' if first is not None else 'no',
                '' if first is None else '%.2f' % first, dwell.get(aoi, ''), others or '-'))
    total = {m: sum(e - s + frame_s for mm, s, e in runs if mm == m) for m in MIRRORS}
    print('\nglances in the block: ' + ', '.join('%s %d (%.1f s)' % (m, sum(1 for r in runs if r[0] == m), total[m])
                                               for m in MIRRORS))
    print('frames looked at: %d (with a gaze point; %d extrapolated off the frame), on a mirror: %d '
          '(%d at the left edge, %d of them off the frame)' % (
              len(rows), sum(1 for r in rows if r[6][0] == 'eye'), sum(1 for r in rows if r[1]),
              sum(1 for r in rows if r[1] and r[6][1]), sum(1 for r in rows if r[1] and r[6][0] == 'eye')))
    if args.images and not args.from_csv:
        out_dir = os.path.join(folder, 'mirror_gaze')
        os.makedirs(out_dir, exist_ok=True)
        for old in os.listdir(out_dir):   # the pictures of an earlier run
            if old.endswith('.jpg'):
                os.remove(os.path.join(out_dir, old))
        capture = cv2.VideoCapture(run.video)
        colours = {'left': (0, 255, 0), 'rear': (255, 0, 0), 'right': (0, 255, 255)}
        for mirror, start, end in runs:
            # the first frame of the glance found in this frame alone (a glance starts with one)
            t, found, msec, gx, gy, detail, extra = next(r for r in rows if start <= r[0] <= end and r[1] == mirror)
            capture.set(cv2.CAP_PROP_POS_MSEC, msec)
            ok, frame = capture.read()
            if not ok:
                continue
            poly = np.array(detail[mirror][3], np.float32)
            # off the frame (the gaze, the cut glass): a black band on the left
            pad = int(max(0.0, -min(gx - 15, poly[:, 0].min() - 5)))
            if pad:
                frame = cv2.copyMakeBorder(frame, 0, 0, pad, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            cv2.polylines(frame, [(poly + [pad, 0]).astype(np.int32)], True, colours[mirror], 2)
            cv2.circle(frame, (int(gx + pad), int(gy)), 10, (0, 0, 255), 2)
            cv2.putText(frame, '%s %.1f-%.1f s  score %.2f ring %.2f%s' % (
                mirror, start, end, detail[mirror][0], detail[mirror][1],
                '  edge %s, gaze from %s' % (extra[1], extra[0]) if extra[1] else ''),
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imwrite(os.path.join(out_dir, 't%06.1f_%s.jpg' % (start, mirror)), frame)
        print('pictures: %s' % out_dir)


if __name__ == '__main__':
    main()
