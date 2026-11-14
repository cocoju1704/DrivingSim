#!/usr/bin/env python

"""
After a block (abc_experiment.py starts this by itself at the end of a run with the Glasses 2
streams; or by hand): the gaze analyses of the block folder, in the background at idle priority,
so a block started meanwhile keeps its frame rate. Log: <folder>/postprocess.log.

    1. mirror_aoi.py                mirror glances through the bezel markers (mirror_aoi.csv,
                                    mirror_aoi_glances.csv, mirror_aoi_windows.csv), when the
                                    folder has mirrors.json and bezel_screen.json
    2. sagat_gaze.csv               the gaze before each SAGAT freeze (below)
    3. display_gaze.csv             the gaze on the glasses display over the drive, the mirror
                                    events' windows and each TOR (below)
    3b. display_position.csv,       where the glasses display lay over the monitors (glasses
        display_heatmap.png         condition; mirror_aoi.csv's display_* columns), per segment
    4. gaze_video.py                gaze_video.mp4: the scene video with the gaze and the drive

    python _Experiment2/postprocess.py <block folder>
    python _Experiment2/postprocess.py <block folder> --detach      (abc_experiment.py --post)
    python _Experiment2/postprocess.py --pending    every block under Data not analysed yet (menu "블록 분석",
                                                    after the session: the experiment no longer starts it)
    python _Experiment2/postprocess.py <block folder> --gaze-only   (only 2, 3 and 3b, in the foreground)

On the glasses display: the Glasses 2 gaze point inside the display's outline (the glasses
condition: from g2_display.json, +15 %). Shares on it are of the valid samples; missing_share is
the share of the gaze samples without a gaze (lost eyes, skipped samples), and
missing_after_on_share the share of those that came while the last valid gaze was on the display.
missing_after_on_share well above on_display_share: the eyes are lost mostly at the display, and
on_display_share understates the time on it. A SAGAT freeze (no frames) is left out.

sagat_gaze.csv, one row per question, over the PRE_S seconds of driving before the freeze: the
share of the gaze on the display, the missing shares, the time since the gaze last left the
display and the longest stretch off it; the mirror glances in those seconds (mirror_aoi.csv).
What a driver could know at the freeze depends on whether they looked up just before it, so the
SAGAT scores are read with these; left_ok / rear_ok / right_ok / ahead_ok: each question right (1),
wrong (0) or unscored, next to that mirror's glances.

display_gaze.csv, one row per window: the whole drive (block), each mirror event's gaze window
(gaze_windows.csv), and for each TOR the PRE_S before the alert (TOR_pre) and TOR_POST_S after it
(TOR_post). Each: the shares above and the display glances (on it, gaps under GLANCE_GAP_S
bridged, at least MIN_GLANCE_S): count, mean and longest. TOR_post also: on the display at the
alert, the eyes off it (s after the alert, 0 when not on it then) and back on it (s after the
alert, the first glance after that).
"""

from __future__ import print_function

import argparse
import bisect
import csv
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PRE_S = 10.0
DISPLAY_MARGIN = 0.15
DISPLAY_PX = 600        # the glasses display, square
NDRT_ASPECT = 16 / 9.0  # the NDRT videos: a band 600 x 338 on it
NDRT_TOP_FROM_APP = 14  # glasses app v14 on: the band at the display's top (before: in the middle)
NDRT_SMALL_FROM_APP = 17  # v17 on: 400 px wide (about 10 deg, as the HUD) at the display's top right
NDRT_SMALL_W = 400      # px: 400 x 225 for 16:9
TOR_POST_S = 10.0       # s after the TOR alert in display_gaze.csv
GLANCE_GAP_S = 0.12     # off the display / missing shorter than this: the display glance goes on
MIN_GLANCE_S = 0.1      # shorter display glances are not counted
FREEZE_GAP_S = 0.5      # frames further apart: a SAGAT freeze, its gaze left out


def log(folder, text):
    line = '%s %s' % (time.strftime('%H:%M:%S'), text)
    print(line)
    with open(os.path.join(folder, 'postprocess.log'), 'a', encoding='utf-8') as handle:
        handle.write(line + '\n')


def wait_for_streams(folder, timeout=180.0):
    """g2_stream.py writes g2_sync.json when it stops (at the end of the run)."""
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(os.path.join(folder, 'g2_sync.json')) and os.path.exists(os.path.join(folder, 'summary.json')):
            return True
        time.sleep(3)
    return False


def run_step(folder, args):
    log(folder, 'run: ' + ' '.join(os.path.basename(a) if i == 0 else a for i, a in enumerate(args)))
    with open(os.path.join(folder, 'postprocess.log'), 'a', encoding='utf-8') as handle:
        # -u: the step's progress ("k of n") in the log as it goes, not only at its end
        code = subprocess.call([sys.executable, '-u'] + args, stdout=handle, stderr=subprocess.STDOUT, cwd=HERE)
    log(folder, '  exit %d' % code)
    return code == 0


def inside(poly, x, y, margin):
    cx = sum(p[0] for p in poly) / 4.0
    cy = sum(p[1] for p in poly) / 4.0
    poly = [(cx + (px - cx) * (1 + margin), cy + (py - cy) * (1 + margin)) for px, py in poly]
    hit = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def block_condition(folder):
    try:
        with open(os.path.join(folder, 'run.json'), encoding='utf-8') as handle:
            run = json.load(handle)
        # abc_experiment writes the options under 'args' (a top-level 'condition' is not there)
        return run.get('condition') or (run.get('args') or {}).get('condition') or ''
    except (OSError, ValueError, AttributeError):
        return ''


def display_map(folder):
    """display px -> gaze point (0..1 of the scene camera): a function, from the block's
    g2_display.json; None outside the glasses condition (the NDRT is not there) or without the file."""
    path = os.path.join(folder, 'g2_display.json')
    if not os.path.exists(path) or block_condition(folder) not in ('glasses', ''):
        return None
    sys.path.insert(0, HERE)
    import g2_validate  # pylint: disable=import-outside-toplevel
    with open(path, encoding='utf-8') as handle:
        display = json.load(handle)
    corners = ('tl', 'tr', 'br', 'bl')
    h = g2_validate.homography([display['dots'][d]['display_px'] for d in corners],
                               [display['dots'][d]['gp'] for d in corners])
    return lambda x, y: g2_validate.apply(h, x, y)


def ndrt_rect(folder):
    """(left, top, right, bottom) display px of the NDRT video on the glasses display, by the glasses
    app's version (glasses_app.json, written at the block start): from NDRT_SMALL_FROM_APP on
    NDRT_SMALL_W wide at the top right (200, 0, 600, 225), from NDRT_TOP_FROM_APP on the display's
    width at its top (0, 0, 600, 337.5), before in the middle."""
    try:
        with open(os.path.join(folder, 'glasses_app.json'), encoding='utf-8') as handle:
            version = int(json.load(handle).get('v') or 0)
    except (OSError, ValueError):
        version = 0
    if version >= NDRT_SMALL_FROM_APP:
        return float(DISPLAY_PX - NDRT_SMALL_W), 0.0, float(DISPLAY_PX), NDRT_SMALL_W / NDRT_ASPECT
    height = DISPLAY_PX / NDRT_ASPECT
    top = 0.0 if version >= NDRT_TOP_FROM_APP else (DISPLAY_PX - height) / 2.0
    return 0.0, top, float(DISPLAY_PX), top + height


def ndrt_band(folder):
    """(top, bottom) display px of the NDRT video (ndrt_rect without its sides: from app v17 on the
    video does not span the display's width, use ndrt_rect)."""
    _, top, _, bottom = ndrt_rect(folder)
    return top, bottom


def display_outline(folder, margin=0.0):
    """The NDRT video's outline on the glasses display (its band, ndrt_band: the rest of the display is
    black, i.e. see-through) in the Glasses 2 scene camera (gaze point units, 0..1: tl, tr, br, bl),
    widened by margin (0.15: DISPLAY_MARGIN); None outside the glasses condition or without
    g2_display.json."""
    to_gp = display_map(folder)
    if to_gp is None:
        return None
    left, top, right, bottom = ndrt_rect(folder)
    poly = [to_gp(x, y) for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))]
    cx = sum(p[0] for p in poly) / 4.0
    cy = sum(p[1] for p in poly) / 4.0
    return [(cx + (px - cx) * (1 + margin), cy + (py - cy) * (1 + margin)) for px, py in poly]


class BlockGaze(object):
    """The block's Glasses 2 gaze on the PC clock, with the glasses display test and the drive's
    stretches (the frames; a SAGAT freeze is a gap in them, its gaze is on the tablet, left out).

    Each gaze sample (one gidx) is valid (s == 0, a gaze point) or missing (a sample with s != 0, or a
    gidx the stream skipped). Missing samples are counted, not dropped silently: under the Ray-Ban
    Display the eyes are lost most when they look down at it, so a share over the valid samples alone
    can understate the time on the display; missing_after_on_share tells whether that happened."""

    def __init__(self, folder):
        with open(os.path.join(folder, 'g2_sync.json'), encoding='utf-8') as handle:
            a, b = json.load(handle)['ts_to_pc']
        self.f_t, self.f_w = [], []
        with open(os.path.join(folder, 'frames.csv'), encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                self.f_t.append(float(row['t_sim']))
                self.f_w.append(float(row['wall_time']))
        by_gidx = {}
        with open(os.path.join(folder, 'g2_data.jsonl'), encoding='utf-8') as handle:
            for line in handle:
                _, _, text = line.partition(' ')
                try:
                    p = json.loads(text)
                except ValueError:
                    continue
                if 'gp' not in p or 'gidx' not in p:
                    continue
                w = p['ts'] / 1e6 + a * p['ts'] + b
                xy = (p['gp'][0], p['gp'][1]) if p.get('s') == 0 else None
                if xy or p['gidx'] not in by_gidx:
                    by_gidx[p['gidx']] = (w, p['gidx'], xy)
        self.samples = sorted(by_gidx.values())
        self.s_w = [s[0] for s in self.samples]
        self.condition = block_condition(folder)
        self.outline = display_outline(folder)
        # on the display: True / False for a valid sample, None for a missing one (or no outline)
        self.on = [None if xy is None or self.outline is None else inside(self.outline, xy[0], xy[1], DISPLAY_MARGIN)
                   for _, _, xy in self.samples]
        self.glances = self._glances()

    def sim_to_pc(self, t):
        # the last frame at or before t: the frames of a freeze share one sim time
        i = max(bisect.bisect_right(self.f_t, t) - 1, 0)
        return self.f_w[i]

    def driving(self, w):
        i = bisect.bisect_right(self.f_w, w) - 1
        return 0 <= i < len(self.f_w) - 1 and self.f_w[i + 1] - self.f_w[i] <= FREEZE_GAP_S

    def indices(self, w0, w1):
        return [i for i in range(bisect.bisect_left(self.s_w, w0), bisect.bisect_left(self.s_w, w1))
                if self.driving(self.s_w[i])]

    def stats(self, w0, w1):
        """Samples, missing share, on-display share (of the valid ones) and the share of the missing
        samples that came while the last valid gaze was on the display, in [w0, w1) of driving."""
        idx = self.indices(w0, w1)
        total = missing = missing_after_on = on = valid = 0
        last_on, prev = None, None
        for i in idx:
            w, gidx, xy = self.samples[i]
            skipped = 0
            if prev is not None and self.samples[prev][0] + FREEZE_GAP_S > w:
                skipped = max(gidx - self.samples[prev][1] - 1, 0)   # gidx the stream left out
            gone = skipped + (1 if xy is None else 0)
            total += skipped + 1
            missing += gone
            if last_on:
                missing_after_on += gone
            if xy is not None:
                valid += 1
                if self.on[i] is not None:
                    last_on = self.on[i]
                    on += self.on[i]
            prev = i
        row = {'gaze_samples': total, 'missing_share': round(missing / float(total), 3) if total else ''}
        if self.outline is not None and valid:
            row['on_display_share'] = round(on / float(valid), 3)
            row['missing_after_on_share'] = round(missing_after_on / float(missing), 3) if missing else ''
        return row

    def _glances(self):
        """Display glances (start, end) on the PC clock: on-display samples, a gap off it or missing
        shorter than GLANCE_GAP_S kept within the glance; at least MIN_GLANCE_S long."""
        if self.outline is None:
            return []
        glances = []
        start = last = None
        for i, (w, _, _) in enumerate(self.samples):
            if not self.on[i] or not self.driving(w):
                continue
            if last is not None and w - last <= GLANCE_GAP_S:
                last = w
                continue
            if last is not None:
                glances.append((start, last))
            start = last = w
        if last is not None:
            glances.append((start, last))
        return [g for g in glances if g[1] - g[0] >= MIN_GLANCE_S]

    def glances_in(self, w0, w1):
        return [g for g in self.glances if g[1] > w0 and g[0] < w1]


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def sagat_gaze(folder, gaze):
    questions = []
    path = os.path.join(folder, 'sagat.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as handle:
            questions = json.load(handle)
    mirrors = [(float(r['t_sim']), r.get('glance') or r['mirror'])
               for r in read_csv(os.path.join(folder, 'mirror_aoi.csv')) if r.get('glance') or r['mirror']]

    rows = []
    for q in questions:
        t = float(q['t'])
        w1 = gaze.sim_to_pc(t - 0.05)
        w0 = gaze.sim_to_pc(t - PRE_S)
        score = q.get('score') or {}
        row = {'id': q['id'], 't': t, 'pre_s': PRE_S, 'score': score.get('score'),
               'behind': score.get('behind'), 'beside': score.get('beside'), 'ahead': score.get('ahead')}
        # per question since 2026-11-13 (four zones; 'beside' only in older runs): correct or not, '' unscored
        for key, col in (('behind_left', 'left_ok'), ('behind', 'rear_ok'), ('behind_right', 'right_ok'),
                         ('ahead', 'ahead_ok')):
            ok = (score.get('correct') or {}).get(key)
            row[col] = '' if ok is None else int(ok)
        row.update(gaze.stats(w0, w1))
        idx = [i for i in gaze.indices(w0, w1) if gaze.on[i] is not None]
        row['valid_samples'] = len(idx)
        if idx:
            last_off = next((gaze.s_w[i] for i in reversed(idx) if not gaze.on[i]), None)
            row['since_last_off_display_s'] = round(w1 - last_off, 2) if last_off else ''
            # the longest stretch off the display
            longest = run = 0.0
            for k in range(1, len(idx)):
                if not gaze.on[idx[k]] and not gaze.on[idx[k - 1]]:
                    run += gaze.s_w[idx[k]] - gaze.s_w[idx[k - 1]]
                    longest = max(longest, run)
                else:
                    run = 0.0
            row['longest_off_display_s'] = round(longest, 2)
        for name in ('left', 'rear', 'right'):
            row['%s_mirror_frames' % name] = sum(1 for mt, m in mirrors if t - PRE_S <= mt < t and m == name)
        rows.append(row)
    keys = ['id', 't', 'pre_s', 'valid_samples', 'gaze_samples', 'missing_share', 'on_display_share',
            'missing_after_on_share', 'since_last_off_display_s', 'longest_off_display_s', 'left_mirror_frames',
            'rear_mirror_frames', 'right_mirror_frames', 'score', 'behind', 'beside', 'ahead', 'left_ok', 'rear_ok',
            'right_ok', 'ahead_ok']
    with open(os.path.join(folder, 'sagat_gaze.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    for row in rows:
        log(folder, '  %s: on the display %s (missing %s, of it after on %s), since the gaze last left it %s s, '
            'mirror frames L%d R%d Rt%d, score %s' % (
                row['id'], row.get('on_display_share', '-'), row.get('missing_share', '-'),
                row.get('missing_after_on_share', '-'), row.get('since_last_off_display_s', '-'),
                row['left_mirror_frames'], row['rear_mirror_frames'], row['right_mirror_frames'], row['score']))


def display_gaze(folder, gaze):
    """display_gaze.csv: the whole drive, each mirror event's gaze window (gaze_windows.csv) and each
    TOR (tor_events.csv: the PRE_S before the alert, TOR_POST_S after it, and when the eyes left the
    display after the alert)."""
    rows = []

    def window_row(rid, kind, t0, t1, w0=None, w1=None):
        w0 = gaze.sim_to_pc(t0) if w0 is None else w0
        w1 = gaze.sim_to_pc(t1) if w1 is None else w1
        row = {'id': rid, 'type': kind, 'window_start': round(t0, 3), 'window_end': round(t1, 3)}
        row.update(gaze.stats(w0, w1))
        if gaze.outline is not None:
            durations = [e - s for s, e in gaze.glances_in(w0, w1)]
            row['display_glances'] = len(durations)
            if durations:
                row['display_glance_mean_s'] = round(sum(durations) / len(durations), 2)
                row['display_glance_max_s'] = round(max(durations), 2)
        return row

    if gaze.f_t:
        rows.append(window_row('block', 'block', gaze.f_t[0], gaze.f_t[-1], gaze.f_w[0], gaze.f_w[-1]))
    for r in read_csv(os.path.join(folder, 'gaze_windows.csv')):
        if r.get('window_start') and r.get('window_end'):
            rows.append(window_row(r['id'], r['type'], float(r['window_start']), float(r['window_end'])))
    for r in read_csv(os.path.join(folder, 'tor_events.csv')):
        if not r.get('t_tor'):
            continue
        t = float(r['t_tor'])
        rid = 'TOR-%s' % r.get('block', '')
        rows.append(window_row(rid, 'TOR_pre', t - PRE_S, t))
        row = window_row(rid, 'TOR_post', t, t + TOR_POST_S)
        if gaze.outline is not None:
            w = gaze.sim_to_pc(t)
            at = next((g for g in gaze.glances if g[0] <= w <= g[1] + GLANCE_GAP_S), None)
            row['on_display_at_alert'] = int(at is not None)
            # the eyes off the display: the end of the glance going on at the alert (0: not on it)
            row['eyes_off_display_after_alert_s'] = round(max(at[1] - w, 0.0), 2) if at else 0.0
            back = next((g for g in gaze.glances if g[0] > (at[1] if at else w)), None)
            row['back_on_display_after_alert_s'] = round(back[0] - w, 2) if back else ''
        rows.append(row)

    keys = ['id', 'type', 'window_start', 'window_end', 'gaze_samples', 'missing_share', 'on_display_share',
            'missing_after_on_share', 'display_glances', 'display_glance_mean_s', 'display_glance_max_s',
            'on_display_at_alert', 'eyes_off_display_after_alert_s', 'back_on_display_after_alert_s']
    with open(os.path.join(folder, 'display_gaze.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    if gaze.outline is None:
        log(folder, '  display_gaze: no glasses display outline (condition %s): the missing shares only'
            % (gaze.condition or '?'))
    for row in rows:
        log(folder, '  %-8s %-8s on the display %s, missing %s (of it after on %s), glances %s (mean %s s)%s' % (
            row['id'], row['type'], row.get('on_display_share', '-'), row.get('missing_share', '-'),
            row.get('missing_after_on_share', '-'), row.get('display_glances', '-'),
            row.get('display_glance_mean_s', '-'),
            ', eyes off the display %s s after the alert, back on it %s s' % (
                row['eyes_off_display_after_alert_s'], row.get('back_on_display_after_alert_s') or '-')
            if 'eyes_off_display_after_alert_s' in row else ''))


HEAT_CELL_PX = 4          # window px per heatmap cell
HEAT_PAD_PX = 300         # window px shown above and below the monitors (bezel, desk)
WINDOW_PX = (5760, 1080)  # the experiment window: 3 monitors of 1920 x 1080
# event positions in window px (display_position.csv: the NDRT band over them): the road ahead (the
# validation's 'road' point, middle monitor 0.5 / 0.45: where the lead car's brake lights (F) and the
# TOR's stopped car are)
EVENT_POINTS = {'road_ahead': (1920 + 0.5 * 1920, 0.45 * 1080)}


def _poly(text):
    return [[float(v) for v in p.split(',')] for p in text.split()] if text else None


def display_position(folder, gaze):
    """display_heatmap.png and display_position.csv: where the glasses display (the NDRT band, and the
    whole 600 x 600) lay over the monitors, from mirror_aoi.csv's display_* columns (mirror_aoi.py,
    glasses condition). Per segment (block, auto, sagat_pre = all SAGAT pre-windows, sagat_pre <id>,
    tor_pre, tor_post; mirror_aoi.segments): the frames, the share located, on which monitor, the
    band's centre (median, quartiles; window px), the share of located frames whose band (whole
    display) overlaps each mirror's glass and the mean share of the glass covered, and the share with
    the band over each EVENT_POINTS point. The frames of a SAGAT freeze are left out. The heatmap:
    per cell the share of the segment's frames with the band (top: the whole display over the block)
    there; the monitors (the middle one approximated from the inner bezel markers) and the mirrors."""
    import numpy as np  # pylint: disable=import-outside-toplevel
    import cv2  # pylint: disable=import-outside-toplevel
    sys.path.insert(0, HERE)
    import mirror_aoi  # pylint: disable=import-outside-toplevel
    if display_map(folder) is None:
        log(folder, '  display_position: not the glasses condition or no g2_display.json')
        return
    rows = [r for r in read_csv(os.path.join(folder, 'mirror_aoi.csv')) if not r.get('dropout')]
    if not any(r.get('display_only') or r.get('display_band_px') for r in rows):
        log(folder, '  display_position: no display places in mirror_aoi.csv (written before 2026-11-14 or with '
            '--from-csv from such a file: mirror_aoi.py without --from-csv)')
        return
    if not any(r.get('display_band_px') for r in rows):
        log(folder, '  display_position: the display was never located')
        return
    # the SAGAT freezes: frames.csv rows further apart than FREEZE_GAP_S (sim time stands still there)
    freezes = [(gaze.f_t[i], gaze.f_t[i + 1]) for i in range(len(gaze.f_t) - 1)
               if gaze.f_w[i + 1] - gaze.f_w[i] > FREEZE_GAP_S]
    rows = [r for r in rows if not any(a <= float(r['t_sim']) <= b for a, b in freezes)]
    with open(os.path.join(folder, 'mirrors.json'), encoding='utf-8') as handle:
        mirrors = json.load(handle)['mirrors']
    width, height = WINDOW_PX[0] // HEAT_CELL_PX, (WINDOW_PX[1] + 2 * HEAT_PAD_PX) // HEAT_CELL_PX

    class Mask(object):
        """A polygon rasterised in heatmap cells, kept as its bounding box (x0, y0) and the box's mask."""
        def __init__(self, poly):
            p = ((np.float32(poly) + [0, HEAT_PAD_PX]) / HEAT_CELL_PX).round().astype(np.int32)
            p[:, 0] = p[:, 0].clip(0, width - 1)
            p[:, 1] = p[:, 1].clip(0, height - 1)
            self.x0, self.y0 = int(p[:, 0].min()), int(p[:, 1].min())
            self.m = np.zeros((int(p[:, 1].max()) - self.y0 + 1, int(p[:, 0].max()) - self.x0 + 1), np.uint8)
            cv2.fillPoly(self.m, [p - [self.x0, self.y0]], 1)

        def add_to(self, acc):
            acc[self.y0:self.y0 + self.m.shape[0], self.x0:self.x0 + self.m.shape[1]] += self.m

        def overlap(self, other):
            """Cells of other covered by self, over other's cells."""
            x0, y0 = max(self.x0, other.x0), max(self.y0, other.y0)
            x1 = min(self.x0 + self.m.shape[1], other.x0 + other.m.shape[1])
            y1 = min(self.y0 + self.m.shape[0], other.y0 + other.m.shape[0])
            if x1 <= x0 or y1 <= y0:
                return 0.0
            a = self.m[y0 - self.y0:y1 - self.y0, x0 - self.x0:x1 - self.x0]
            b = other.m[y0 - other.y0:y1 - other.y0, x0 - other.x0:x1 - other.x0]
            return float((a & b).sum()) / max(float(other.m.sum()), 1.0)

    mask = Mask
    glass = {n: mask(m['glass']) for n, m in mirrors.items()}
    frames = []   # (t, display_on, band centre, band mask, full mask, {mirror: (band share, full share)}, {event: in})
    for r in rows:
        band, full = _poly(r.get('display_band_px')), _poly(r.get('display_full_px'))
        if not band:
            frames.append((float(r['t_sim']), '', None, None, None, {}, {}))
            continue
        bm, fm = mask(band), mask(full) if full else None
        cover = {n: (bm.overlap(g), fm.overlap(g) if fm is not None else 0.0) for n, g in glass.items()}
        contour = np.float32(band).reshape(-1, 1, 2)
        events = {e: cv2.pointPolygonTest(contour, p, False) >= 0 for e, p in EVENT_POINTS.items()}
        frames.append((float(r['t_sim']), r.get('display_on', ''), np.float32(band).mean(axis=0), bm, fm, cover, events))
    run = type('Frames', (), {'ft': gaze.f_t})()
    segments = mirror_aoi.segments(folder, run)
    pre = [s for s in segments if s[0].startswith('sagat_pre ')]
    groups = [(s[0], [(s[1], s[2])]) for s in segments if not s[0].startswith('sagat_pre ')]
    if pre:
        groups.insert(2, ('sagat_pre', [(a, b) for _, a, b in pre]))
    groups += [(s[0], [(s[1], s[2])]) for s in pre]
    out, heat = [], {}
    for name, spans in groups:
        mine = [f for f in frames if any(a <= f[0] < b for a, b in spans)]
        located = [f for f in mine if f[2] is not None]
        row = {'segment': name, 'start': round(spans[0][0], 2), 'end': round(spans[-1][1], 2), 'frames': len(mine),
               'located': len(located), 'located_share': round(len(located) / float(len(mine)), 3) if mine else ''}
        for where in ('middle', 'left', 'right'):
            row['on_%s_share' % where] = round(sum(1 for f in located if f[1] == where) / float(len(located)), 3) if located else ''
        if located:
            c = np.array([f[2] for f in located])
            for k, axis in ((0, 'x'), (1, 'y')):
                q1, med, q3 = np.percentile(c[:, k], [25, 50, 75])
                row.update({'band_c%s_median' % axis: round(float(med)), 'band_c%s_q1' % axis: round(float(q1)),
                            'band_c%s_q3' % axis: round(float(q3))})
            for n in sorted(glass):
                row['band_over_%s_share' % n] = round(sum(1 for f in located if f[5][n][0] > 0) / float(len(located)), 3)
                row['band_covers_%s_mean' % n] = round(sum(f[5][n][0] for f in located) / len(located), 4)
                row['full_over_%s_share' % n] = round(sum(1 for f in located if f[5][n][1] > 0) / float(len(located)), 3)
            for e in sorted(EVENT_POINTS):
                row['band_over_%s_share' % e] = round(sum(1 for f in located if f[6][e]) / float(len(located)), 3)
        out.append(row)
        if not name.startswith('sagat_pre '):
            band = np.zeros((height, width), np.float32)
            full = np.zeros((height, width), np.float32)
            for f in located:
                f[3].add_to(band)
                if f[4] is not None:
                    f[4].add_to(full)
            heat[name] = (band / max(len(mine), 1), full / max(len(mine), 1), row)
    keys = []
    for row in out:
        keys += [k for k in row if k not in keys]
    with open(os.path.join(folder, 'display_position.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(out)
    for row in out:
        log(folder, '  display %-14s located %s of %d frames, band centre x %s (%s-%s) y %s (%s-%s), over mirrors %s, '
            'over the road ahead %s' % (
                row['segment'], row['located_share'], row['frames'], row.get('band_cx_median', '-'),
                row.get('band_cx_q1', '-'), row.get('band_cx_q3', '-'), row.get('band_cy_median', '-'),
                row.get('band_cy_q1', '-'), row.get('band_cy_q3', '-'),
                ' '.join('%s %s' % (n, row.get('band_over_%s_share' % n, '-')) for n in sorted(glass)),
                row.get('band_over_road_ahead_share', '-')))
    heat_png(folder, heat, mirrors)


def heat_png(folder, heat, mirrors):
    """display_heatmap.png: the whole display over the block, then the band per segment."""
    import numpy as np  # pylint: disable=import-outside-toplevel
    import matplotlib  # pylint: disable=import-outside-toplevel
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
    titles = {'block': '전체 주행', 'auto': '자율주행 (TOR 경고 전)', 'sagat_pre': 'SAGAT 정지 전 10초 (모두)',
              'tor_pre': 'TOR 경고 전 10초', 'tor_post': 'TOR 경고 후 10초'}
    panels = []
    if 'block' in heat:
        panels.append(('block', 1, '전체 주행 - 글래스 화면 전체 (600×600)'))
    panels += [(n, 0, '%s - NDRT 영상 영역' % titles[n]) for n in titles if n in heat]
    plt.rcParams['font.family'] = ['Malgun Gothic', 'DejaVu Sans']
    fig, axes = plt.subplots(len(panels), 1, figsize=(16, 4.6 * len(panels)))
    ink, muted, accent = '#222222', '#888888', '#d0632a'
    w, h, pad = WINDOW_PX[0], WINDOW_PX[1], HEAT_PAD_PX
    for ax, (name, which, title) in zip(np.atleast_1d(axes), panels):
        share = heat[name][which] * 100
        row = heat[name][2]
        im = ax.imshow(share, cmap='Blues', vmin=0, vmax=max(1e-6, float(share.max())), extent=(0, w, h + pad, -pad),
                       interpolation='bilinear')
        for k in range(3):
            ax.add_patch(plt.Rectangle((k * 1920, 0), 1920, 1080, fill=False, ec=muted, lw=1))
        for mirror, m in mirrors.items():
            g = np.array(m['glass'] + [m['glass'][0]])
            ax.plot(g[:, 0], g[:, 1], color=accent, lw=1.2)
            ax.text(g[:, 0].mean(), g[:, 1].max() + 20, mirror, color=ink, fontsize=8, ha='center', va='top')
        for e, (x, y) in EVENT_POINTS.items():
            ax.plot([x], [y], marker='+', ms=10, color=ink, mew=1.2)
            ax.text(x + 25, y - 15, '도로 앞' if e == 'road_ahead' else e, color=ink, fontsize=8)
        for k, label in enumerate(('왼쪽 모니터', '가운데 모니터 (근사)', '오른쪽 모니터')):
            ax.text(k * 1920 + 15, h + 15, label, color=muted, fontsize=8, va='top')
        ax.set_title('%s   (%.0f–%.0f s, 위치 추정된 프레임 %d / %d = %.0f %%)' % (
            title, row['start'], row['end'], row['located'], row['frames'], 100.0 * (row['located_share'] or 0)),
            fontsize=10, color=ink, loc='left')
        ax.set_xlim(0, w)
        ax.set_ylim(h + pad, -pad)
        ax.set_xticks([0, 1920, 3840, 5760])
        ax.set_yticks([0, 1080])
        ax.tick_params(labelsize=7, colors=muted)
        for spine in ax.spines.values():
            spine.set_visible(False)
        bar = fig.colorbar(im, ax=ax, fraction=0.015, pad=0.01)
        bar.set_label('프레임 비율 (%)', fontsize=8)
        bar.ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(folder, 'display_heatmap.png'), dpi=100)
    plt.close(fig)
    log(folder, '  display_heatmap.png written')


def detach(folder):
    """Starts this script on its own, idle priority, no window: the experiment does not wait."""
    flags = 0
    if os.name == 'nt':
        # NEW_GROUP, IDLE, NO_WINDOW: a hidden console of its own (its multiprocessing workers share it:
        # no windows). Not DETACHED_PROCESS: the workers then failed (PermissionError, DuplicateHandle)
        flags = 0x00000200 | 0x00000040 | 0x08000000
    subprocess.Popen([sys.executable, os.path.abspath(__file__), folder], cwd=HERE, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


# -- the NDRT screens judged alike (2026-11-14) ------------------------------------------------------

SCREEN_MARGINS_DEG = (0.0, 1.0, 2.0, 3.0)   # on the screen = in its outline or this near it; 1 deg the main one
SCREEN_MAIN_MARGIN_DEG = 1.0
SCREEN_JOIN_S = 0.2       # off it (or missing) shorter than this: the glance goes on (in and out at the border)
SCREEN_MIN_GLANCE_S = 0.1
SCENE_FOV_DEG = (82.0, 52.0)   # the Glasses 2 scene camera: gaze point units to degrees
HUD_PX_PER_DEG = 1920 / 2.0 / 0.39391930 * 0.017453293   # middle monitor: 960 px / tan(21.5 deg), per degree
HUD_SHIFT_FLAG_DEG = 1.5  # the outlines before and after the block further apart: the block is flagged


def _near(poly, x, y, margin, sx, sy):
    """(x, y) in the polygon, or within margin degrees of its edge (coordinates times sx, sy = degrees)."""
    if inside(poly, x, y, 0.0):
        return True
    if margin <= 0.0:
        return False
    px, py = x * sx, y * sy
    best = None
    for i in range(len(poly)):
        ax, ay = poly[i][0] * sx, poly[i][1] * sy
        bx, by = poly[(i + 1) % len(poly)][0] * sx, poly[(i + 1) % len(poly)][1] * sy
        dx, dy = bx - ax, by - ay
        u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1.0)))
        d = ((px - ax - u * dx) ** 2 + (py - ay - u * dy) ** 2) ** 0.5
        best = d if best is None else min(best, d)
    return best <= margin


def hud_outline(folder):
    """The HUD's outline in window px and where it came from: the validation's (hud_gaze.json, before
    the block) and the after-check's (hud_gaze_post.json) averaged corner by corner, one of them, or the
    rectangle as drawn (hud.json). Also how far the two were apart (degrees, mean of the corners)."""
    def load(name):
        try:
            with open(os.path.join(folder, name), encoding='utf-8') as handle:
                data = json.load(handle)
            return data.get('outline_px') or None
        except (OSError, ValueError):
            return None
    pre, post = load('hud_gaze.json'), load('hud_gaze_post.json')
    if pre and post:
        shift = sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(pre, post)) / 4.0 / HUD_PX_PER_DEG
        return [((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0) for a, b in zip(pre, post)], 'gaze before+after', round(shift, 2)
    if pre or post:
        return pre or post, 'gaze before' if pre else 'gaze after', None
    try:
        with open(os.path.join(folder, 'hud.json'), encoding='utf-8') as handle:
            x, y, w, h = json.load(handle)['rect_px']
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], 'drawn (no HUD validation points)', None
    except (OSError, ValueError, KeyError):
        return None, None, None


def screen_gaze(folder, gaze):
    """screen_gaze.csv: the NDRT screen of the block's condition judged by one rule in every condition
    (TODO 2026-11-14): its outline as this participant's gaze sees it (glasses: g2_display.json; HUD:
    hud_gaze.json from the validation points, before and after the block), on it = inside or within
    m degrees (SCREEN_MARGINS_DEG, 1 deg the main), glances with SCREEN_JOIN_S bridged and at least
    SCREEN_MIN_GLANCE_S. The phone (app v4, phone_screen.json): its video as its markers place it in
    each scene frame (mirror_aoi.csv phone_deg: the gaze's distance from it), the same rule; a frame
    without PHONE_MIN_MARKERS of its markers is missing.
    Rows: block, auto (to the TOR), sagat_pre (PRE_S before each freeze), TOR_pre, TOR_post."""
    condition = gaze.condition or block_condition(folder)
    if condition == 'glasses':
        poly = display_outline(folder)
        if poly is None:
            return
        scale, source, shift = SCENE_FOV_DEG, 'g2_display.json', None
        samples = [(w, xy) for w, _, xy in gaze.samples if gaze.driving(w)]
    elif condition == 'hud':
        poly, source, shift = hud_outline(folder)
        if poly is None:
            log(folder, '  screen_gaze: no HUD outline (hud.json / hud_gaze.json)')
            return
        scale = (1.0 / HUD_PX_PER_DEG, 1.0 / HUD_PX_PER_DEG)
        samples = []
        for r in read_csv(os.path.join(folder, 'mirror_aoi.csv')):
            if r.get('display_only') not in (None, '', '0'):
                continue
            w = gaze.sim_to_pc(float(r['t_sim']))
            if not gaze.driving(w):
                continue
            xy = (float(r['window_x_px']), float(r['window_y_px'])) if r.get('window_x_px') else None
            samples.append((w, xy))
        if not samples:
            log(folder, '  screen_gaze: no mirror_aoi.csv frames (run mirror_aoi.py)')
            return
    elif condition == 'phone':
        if not os.path.exists(os.path.join(folder, 'phone_screen.json')):
            log(folder, '  screen_gaze: no phone_screen.json (phone app v4 markers)')
            return
        poly, scale, source, shift = None, None, 'phone markers', None
        samples = []
        for r in read_csv(os.path.join(folder, 'mirror_aoi.csv')):
            if r.get('display_only') not in (None, '', '0') or not r.get('gaze_x_px'):
                continue
            w = gaze.sim_to_pc(float(r['t_sim']))
            if gaze.driving(w):
                samples.append((w, float(r['phone_deg']) if r.get('phone_deg') else None))
        if not samples:
            log(folder, '  screen_gaze: no mirror_aoi.csv frames (run mirror_aoi.py)')
            return
    else:
        log(folder, '  screen_gaze: %s condition: no screen outline' % (condition or '?'))
        return
    samples.sort(key=lambda sample: sample[0])
    if poly is None:   # the phone: the distance (deg) already
        on = {m: [None if d is None else d <= m for _, d in samples] for m in SCREEN_MARGINS_DEG}
    else:
        on = {m: [None if xy is None else _near(poly, xy[0], xy[1], m, scale[0], scale[1]) for _, xy in samples]
              for m in SCREEN_MARGINS_DEG}
    ws = [w for w, _ in samples]

    def glances(flags, w0, w1):
        out, start, last = [], None, None
        for (w, _), hit in zip(samples, flags):
            if w < w0 or w >= w1 or not hit:
                continue
            if last is not None and w - last <= SCREEN_JOIN_S:
                last = w
                continue
            if last is not None:
                out.append((start, last))
            start = last = w
        if last is not None:
            out.append((start, last))
        return [g for g in out if g[1] - g[0] >= SCREEN_MIN_GLANCE_S]

    def row(rid, kind, w0, w1):
        i0, i1 = bisect.bisect_left(ws, w0), bisect.bisect_left(ws, w1)
        valid = [k for k in range(i0, i1) if samples[k][1] is not None]
        out = {'id': rid, 'type': kind, 'screen': condition, 'outline': source,
               'outline_shift_deg': '' if shift is None else shift,
               'flag_shift': '' if shift is None else int(shift > HUD_SHIFT_FLAG_DEG),
               'samples': i1 - i0, 'missing_share': round(1 - len(valid) / float(i1 - i0), 3) if i1 > i0 else ''}
        for m in SCREEN_MARGINS_DEG:
            out['on_share_%gdeg' % m] = round(sum(on[m][k] for k in valid) / float(len(valid)), 3) if valid else ''
        g = glances(on[SCREEN_MAIN_MARGIN_DEG], w0, w1)
        minutes = (w1 - w0) / 60.0
        out['glances_per_min'] = round(len(g) / minutes, 2) if minutes > 0 else ''
        if g:
            durations = sorted(b - a for a, b in g)
            out['glance_median_s'] = round(durations[len(durations) // 2], 2)
        return out

    rows = []
    if not gaze.f_w:
        return
    t_tor = None
    for r in read_csv(os.path.join(folder, 'tor_events.csv')):
        if r.get('t_tor'):
            t_tor = float(r['t_tor'])
    rows.append(row('block', 'block', gaze.f_w[0], gaze.f_w[-1]))
    rows.append(row('auto', 'auto', gaze.f_w[0], gaze.sim_to_pc(t_tor) if t_tor is not None else gaze.f_w[-1]))
    for r in read_csv(os.path.join(folder, 'events.csv')):
        what = r.get('what') or r.get('event') or ''
        if what.startswith('freeze (SAGAT'):
            t = float(r.get('t_sim') or r.get('t') or 0)
            rows.append(row(r.get('id') or r.get('eid') or 'Q', 'sagat_pre', gaze.sim_to_pc(t - PRE_S), gaze.sim_to_pc(t)))
    if t_tor is not None:
        rows.append(row('TOR', 'TOR_pre', gaze.sim_to_pc(t_tor - PRE_S), gaze.sim_to_pc(t_tor)))
        rows.append(row('TOR', 'TOR_post', gaze.sim_to_pc(t_tor), gaze.sim_to_pc(t_tor + TOR_POST_S)))
    keys = ['id', 'type', 'screen', 'outline', 'outline_shift_deg', 'flag_shift', 'samples', 'missing_share'] + \
        ['on_share_%gdeg' % m for m in SCREEN_MARGINS_DEG] + ['glances_per_min', 'glance_median_s']
    with open(os.path.join(folder, 'screen_gaze.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    for r in rows:
        log(folder, '  screen %-6s %-9s on %s (0/1/2/3 deg: %s), %s glances/min, median %s s; outline %s%s' % (
            r['id'], r['type'], condition, ' / '.join(str(r['on_share_%gdeg' % m]) for m in SCREEN_MARGINS_DEG),
            r['glances_per_min'], r.get('glance_median_s', '-'), source,
            '' if shift is None else ', before/after %.1f deg apart%s' % (shift, ' (FLAG)' if shift > HUD_SHIFT_FLAG_DEG else '')))


def pending(test=False):
    """Block folders under Data with Glasses 2 streams (g2_sync.json) and no finished postprocess
    (no 'done' in postprocess.log), oldest first. Data/test only with test."""
    data = os.path.join(HERE, 'Data')
    found = []
    for root, dirs, files in os.walk(data):
        if not test and os.path.abspath(root) == os.path.join(data, 'test'):
            dirs[:] = []
            continue
        if 'g2_sync.json' in files and 'run.json' in files:
            done = False
            try:
                with open(os.path.join(root, 'postprocess.log'), encoding='utf-8', errors='replace') as handle:
                    done = any(line.rstrip().endswith(' done') for line in handle)
            except OSError:
                pass
            if not done:
                found.append((os.path.getmtime(os.path.join(root, 'run.json')), root))
    return [root for _, root in sorted(found)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder', nargs='?')
    parser.add_argument('--pending', action='store_true',
                        help='every block under Data not analysed yet, one after another (after the session)')
    parser.add_argument('--test', action='store_true', help='with --pending: Data/test too')
    parser.add_argument('--detach', action='store_true', help='start in the background and return at once')
    parser.add_argument('--workers', type=int, default=6, help='mirror_aoi.py workers')
    parser.add_argument('--gaze-only', action='store_true',
                        help='only sagat_gaze.csv and display_gaze.csv (mirror_aoi.csv from an earlier run)')
    args = parser.parse_args()
    if args.pending:
        folders = pending(args.test)
        print('%d block(s) to analyse%s' % (len(folders), ''.join('\n  ' + f for f in folders)))
        for k, folder in enumerate(folders):
            print('\n[%d/%d] %s' % (k + 1, len(folders), folder))
            subprocess.call([sys.executable, os.path.abspath(__file__), folder, '--workers', str(args.workers)]
                            + (['--gaze-only'] if args.gaze_only else []), cwd=HERE)
        print('\nall done')
        return
    if not args.folder:
        parser.error('a block folder, or --pending')
    folder = os.path.abspath(args.folder)
    if args.detach:
        detach(folder)
        return
    log(folder, 'postprocess %s' % folder)
    if not wait_for_streams(folder):
        log(folder, 'no g2_sync.json: no Glasses 2 streams in this block, nothing to do')
        return
    if not args.gaze_only:
        # the mirror glances through the bezel markers (mirror_aoi.py), when the block has both files
        if all(os.path.exists(os.path.join(folder, n)) for n in ('mirrors.json', 'bezel_screen.json')):
            run_step(folder, [os.path.join(HERE, 'mirror_aoi.py'), folder, '--workers', str(args.workers)])
        else:
            log(folder, 'mirror_aoi.py skipped: no mirrors.json / bezel_screen.json in the block folder')
    try:
        gaze = BlockGaze(folder)
    except Exception as error:  # pylint: disable=broad-except
        log(folder, 'reading the gaze failed: %s' % error)
        gaze = None
    for step in (sagat_gaze, display_gaze, display_position, screen_gaze) if gaze else ():
        try:
            step(folder, gaze)
        except Exception as error:  # pylint: disable=broad-except
            log(folder, '%s failed: %s' % (step.__name__, error))
    if args.gaze_only:
        log(folder, 'done')
        return
    run_step(folder, [os.path.join(HERE, 'gaze_video.py'), folder])
    log(folder, 'done')


if __name__ == '__main__':
    main()
