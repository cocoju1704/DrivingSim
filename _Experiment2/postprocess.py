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
    4. gaze_video.py                gaze_video.mp4: the scene video with the gaze and the drive

    python _Experiment2/postprocess.py <block folder>
    python _Experiment2/postprocess.py <block folder> --detach      (what the experiment does)
    python _Experiment2/postprocess.py <block folder> --gaze-only   (only 2 and 3, in the foreground)

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
SAGAT scores are read with these.

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
            return json.load(handle).get('condition', '')
    except (OSError, ValueError):
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


def ndrt_band(folder):
    """(top, bottom) display px of the NDRT video on the glasses display: at its top from glasses app
    NDRT_TOP_FROM_APP on (glasses_app.json, written at the block start), in the middle before."""
    try:
        with open(os.path.join(folder, 'glasses_app.json'), encoding='utf-8') as handle:
            version = int(json.load(handle).get('v') or 0)
    except (OSError, ValueError):
        version = 0
    height = DISPLAY_PX / NDRT_ASPECT
    top = 0.0 if version >= NDRT_TOP_FROM_APP else (DISPLAY_PX - height) / 2.0
    return top, top + height


def display_outline(folder, margin=0.0):
    """The NDRT video's outline on the glasses display (its band, ndrt_band: the rest of the display is
    black, i.e. see-through) in the Glasses 2 scene camera (gaze point units, 0..1: tl, tr, br, bl),
    widened by margin (0.15: DISPLAY_MARGIN); None outside the glasses condition or without
    g2_display.json."""
    to_gp = display_map(folder)
    if to_gp is None:
        return None
    top, bottom = ndrt_band(folder)
    poly = [to_gp(x, y) for x, y in ((0, top), (DISPLAY_PX, top), (DISPLAY_PX, bottom), (0, bottom))]
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
            'rear_mirror_frames', 'right_mirror_frames', 'score', 'behind', 'beside', 'ahead']
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


def detach(folder):
    """Starts this script on its own, idle priority, no window: the experiment does not wait."""
    flags = 0
    if os.name == 'nt':
        # NEW_GROUP, IDLE, NO_WINDOW: a hidden console of its own (its multiprocessing workers share it:
        # no windows). Not DETACHED_PROCESS: the workers then failed (PermissionError, DuplicateHandle)
        flags = 0x00000200 | 0x00000040 | 0x08000000
    subprocess.Popen([sys.executable, os.path.abspath(__file__), folder], cwd=HERE, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder')
    parser.add_argument('--detach', action='store_true', help='start in the background and return at once')
    parser.add_argument('--workers', type=int, default=6, help='mirror_aoi.py workers')
    parser.add_argument('--gaze-only', action='store_true',
                        help='only sagat_gaze.csv and display_gaze.csv (mirror_aoi.csv from an earlier run)')
    args = parser.parse_args()
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
    for step in (sagat_gaze, display_gaze) if gaze else ():
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
