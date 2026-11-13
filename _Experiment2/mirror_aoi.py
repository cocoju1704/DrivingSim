#!/usr/bin/env python

"""
Mirror glances from the Glasses 2 gaze through the bezel markers: the gaze put in the experiment
window's pixels, where the mirrors are drawn. The mirror need not be in the scene video's picture
(with the eyes only turned to it, it is at or past the frame's edge), only markers of its monitor.

    python _Experiment2/mirror_aoi.py <block folder>
    python _Experiment2/mirror_aoi.py <block folder> --from-csv     the glances again from mirror_aoi.csv

Needs in the block folder: g2_scene.ts, g2_data.jsonl, g2_sync.json, frames.csv (abc_experiment --g2),
mirrors.json (each mirror's glass in window px, abc_experiment) and bezel_screen.json (the bezel
markers in window px, mirror_register.py; abc_experiment copies it in).

Each looked-at frame (every STEP-th):
  1. the gaze point in the scene camera (px, 960 x 540; Glasses 2's gp, also off the frame)
  2. the bezel markers (mirror_markers.Detector); per side monitor, a marker counts when its corners
     agree with the others' (a RANSAC homography over all of them, RANSAC_PX) - the loose detector
     finds ids in clutter too
  3. per monitor with MIN_MARKERS markers: a homography from the NEAREST markers to the gaze (the
     monitors are curved), the gaze into window px, the glass outlines back into the scene camera,
     and the gaze's distance from each glass in degrees (negative: inside; SCENE_PX_PER_DEG)
  4. the mirror: within ENTER_DEG of its glass; a glance, once started, goes on within STAY_DEG
     (the gaze jitters at the edge); gaps up to g2_block.GAP_S bridged

Unsure: with the eyes turned UNSURE_DEG or more to a side in the head, Glasses 2 mostly has no gaze
point (past about 42 degrees none at all), only the eyes' angles, which do not tell the mirror from
the window next to it (mirror_check 1112173906: a position from them was 8 degrees off). Those
frames are 'left?' / 'right?' (looking that far to that side, mirror or not unknown), not judged.
Looking at a side mirror Glasses 2 also often loses both pupils (no gaze point, no eye angles) for
0.1-0.6 s (1112193334: 20 such dropouts with the eyes to the left, 4.4 s, against 1.2 s of left
glances): a dropout of DROPOUT_MIN_S..DROPOUT_MAX_S with the eyes DROPOUT_SIDE_DEG or more to the
same side at both ends is unsure too (rows with dropout 1, no frame). An unsure run within JOIN_S of
a glance at that side's mirror is part of the glance (its unsure_s); the rest stay 'left?' / 'right?'.
mirror_check 1112173906 (glances marked by the driver): with the gaze point, the eyes up to 25
degrees in the head 72-78 % of the marked frames on the mirror, 25-35: 45 %, 35-42: 25 %; unmarked
frames on a mirror 0.1-0.3 %.

Out, into the folder:
    mirror_aoi.csv          per frame looked at: sim time, gaze (scene px) or none, the eyes' angles,
                            the markers per monitor, the gaze in window px and its monitor, each
                            mirror's distance (deg), the mirror of this frame alone and with the
                            hysteresis (glance), unsure
    mirror_aoi_glances.csv  the glances (mirror, start, end, s, frames, closest deg, of it unsure s),
                            and the unsure runs not joined to one as mirror 'left?' / 'right?'
    mirror_aoi_rates.csv    the main measure (TODO 4): per segment (block, auto = to the TOR alert,
                            sagat_pre <id>, tor_pre, tor_post) and mirror the glances, per minute,
                            dwell s and share; again with the unsure runs left over (_with_unsure)
    mirror_aoi_windows.csv  per event window and the TOR: the AOI mirror glanced or not, first glance,
                            dwell, the other mirrors' dwell (secondary)
"""

from __future__ import print_function

import argparse
import csv
import json
import math
import multiprocessing
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import g2_block  # noqa: E402
import mirror_markers as mm  # noqa: E402

STEP = g2_block.STEP            # every 3rd frame (50 fps: 0.06 s)
MIRRORS = g2_block.MIRRORS
SCENE_PX_PER_DEG = 960 / 82.0   # the scene camera: 82 degrees across 960 px (about; more at the edges)
MIN_MARKERS = 2                 # markers of a monitor for its homography
NEAREST = 3                     # the markers nearest to the gaze in it
RANSAC_PX = 40.0                # window px: a marker's corners this far from the others' homography: dropped
MAX_FIT_PX = 25.0               # window px: the local homography's RMS on its markers' corners
ENTER_DEG = 1.0                 # the gaze within this of a glass: on that mirror
STAY_DEG = 2.5                  # a glance goes on within this
MONITOR_SLACK_PX = 300          # the gaze counts on a side monitor up to this past its pixels (its bezel)
UNSURE_DEG = 35.0               # eye yaw in the head (deg) from which a frame without a gaze point is unsure
DROPOUT_MIN_S = 0.1             # no eye data at all (both pupils lost) for this long or longer ...
DROPOUT_MAX_S = 1.0             # ... and at most this long ...
DROPOUT_SIDE_DEG = 25.0         # ... with the eyes this far to one side just before and just after: unsure
JOIN_S = g2_block.GAP_S         # an unsure run this close to a glance at its side's mirror: part of the glance
SIDE_MIRROR = {'left?': 'left', 'right?': 'right'}
RATE_PRE_S = 10.0               # mirror_aoi_rates.csv: s before each SAGAT freeze and before the TOR alert
RATE_POST_S = 10.0              # s after the TOR alert
G2_HZ = 50.0                    # Glasses 2 gaze samples per s (eye data share)
FREEZE_GAP_S = 0.5              # frames.csv rows further apart: a SAGAT freeze (left out of the real time)


def load(folder):
    with open(os.path.join(folder, 'mirrors.json'), encoding='utf-8') as handle:
        mirrors = json.load(handle)['mirrors']
    with open(os.path.join(folder, 'bezel_screen.json'), encoding='utf-8') as handle:
        bezel = json.load(handle)['markers']
    return mirrors, bezel


def monitor_of_px(x):
    k = int(math.floor(x / mm.MONITOR_PX[0]))
    return {0: 'left', 1: 'middle', 2: 'right'}.get(k, '')


def consistent(cv2, found, bezel, monitor):
    """{name: scene corners} of the monitor's markers that agree with each other (RANSAC over all
    their corners when 3 or more; 2: kept, the local fit's RMS decides)."""
    mine = {n: c for n, c in found.items() if bezel[n]['monitor'] == monitor}
    if len(mine) < 3:
        return mine
    names = sorted(mine)
    src = np.float32([p for n in names for p in mine[n]])
    dst = np.float32([p for n in names for p in bezel[n]['corners_px']])
    h, inliers = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_PX)
    if h is None:
        return {}
    inliers = inliers.reshape(-1)
    return {n: mine[n] for k, n in enumerate(names) if inliers[4 * k:4 * k + 4].sum() >= 3}


def gaze_on(cv2, markers, bezel, gx, gy):
    """Homography (scene -> window px) from the markers nearest to the gaze, and its RMS (window px);
    (None, None) without MIN_MARKERS."""
    if len(markers) < MIN_MARKERS:
        return None, None
    near = sorted(markers, key=lambda n: math.hypot(markers[n][:, 0].mean() - gx, markers[n][:, 1].mean() - gy))
    near = near[:NEAREST]
    src = np.float32([p for n in near for p in markers[n]])
    dst = np.float32([p for n in near for p in bezel[n]['corners_px']])
    h, _ = cv2.findHomography(src, dst, 0)
    if h is None:
        return None, None
    back = cv2.perspectiveTransform(src.reshape(-1, 1, 2), h).reshape(-1, 2)
    return h, float(np.sqrt(np.mean(np.sum((back - dst) ** 2, axis=1))))


def _work(args):
    """Frames [first, last), every STEP-th: [(frame index, msec, row dict)]."""
    folder, first, last = args
    import cv2  # pylint: disable=import-outside-toplevel
    cv2.setNumThreads(1)
    run = g2_block.Run(folder)
    mirrors, bezel = load(folder)
    ids = {m['id']: n for n, m in bezel.items()}
    detector = mm.Detector(set(ids))
    side_of = {name: monitor_of_px(np.mean([p[0] for p in m['glass']])) for name, m in mirrors.items()}
    capture = cv2.VideoCapture(run.video)
    capture.set(cv2.CAP_PROP_POS_FRAMES, first)
    out = []
    index = first
    while index < last:
        if not capture.grab():
            break
        if (index - first) % STEP:
            index += 1
            continue
        msec = capture.get(cv2.CAP_PROP_POS_MSEC)
        ts = run.ts_of_msec(msec)
        if not run.in_block(run.pc_of_ts(ts)):
            index += 1
            continue
        gaze, eye = run.gaze_at(ts), run.eye_at(ts)
        row = {'eye_yaw': '' if eye is None else round(eye[0], 1), 'eye_pitch': '' if eye is None else round(eye[1], 1),
               'mirror': '', 'unsure': ''}
        if gaze is None:
            # no gaze point: the eyes far to a side (unsure), else nothing to say
            if eye is not None and abs(eye[0]) >= UNSURE_DEG:
                row['unsure'] = 'left?' if eye[0] > 0 else 'right?'
                out.append((index, msec, row))
            index += 1
            continue
        gx, gy = gaze
        row.update({'gaze_x_px': round(gx, 1), 'gaze_y_px': round(gy, 1)})
        _, frame = capture.retrieve()
        found = {ids[i]: c for i, c in detector(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)).items()}
        best = None   # (monitor, window px) of the gaze, on the side monitor it falls on
        for monitor in ('left', 'right'):
            markers = consistent(cv2, found, bezel, monitor)
            row['markers_%s' % monitor] = ' '.join(sorted(markers))
            h, rms = gaze_on(cv2, markers, bezel, gx, gy)
            if h is None or rms > MAX_FIT_PX:
                continue
            row['fit_%s_px' % monitor] = round(rms, 1)
            wx, wy = cv2.perspectiveTransform(np.float32([[[gx, gy]]]), h)[0, 0]
            x0 = mm.MONITOR_INDEX[monitor] * mm.MONITOR_PX[0]
            if x0 - MONITOR_SLACK_PX <= wx < x0 + mm.MONITOR_PX[0] + MONITOR_SLACK_PX:
                best = (monitor, wx, wy)
            inverse = np.linalg.inv(h)
            for name, m in mirrors.items():
                if side_of[name] != monitor:
                    continue
                glass = cv2.perspectiveTransform(np.float32(m['glass']).reshape(-1, 1, 2), inverse)
                # pointPolygonTest: + inside, - outside (px); here distance: - inside, + outside (deg)
                d = -cv2.pointPolygonTest(glass.astype(np.float32), (float(gx), float(gy)), True) / SCENE_PX_PER_DEG
                row['%s_deg' % name] = round(d, 2)
        if best:
            row['window_monitor'], row['window_x_px'], row['window_y_px'] = best[0], round(float(best[1])), round(float(best[2]))
        dists = [(row['%s_deg' % m], m) for m in MIRRORS if '%s_deg' % m in row]
        near = min(dists) if dists else None
        row['mirror'] = near[1] if near and near[0] <= ENTER_DEG else ''
        out.append((index, msec, row))
        index += 1
    return out


def classify(rows):
    """The glance's mirror per frame: entered within ENTER_DEG (row['mirror']), kept within STAY_DEG."""
    out = []
    current = None
    for row in rows:
        if row['unsure']:       # no gaze point: not judged, the glance (if any) not ended by it (join)
            out.append(None)
            continue
        if current:
            d = row.get('%s_deg' % current)
            if d is None or d > STAY_DEG or (row['mirror'] and row['mirror'] != current):
                current = row['mirror'] or None
        else:
            current = row['mirror'] or None
        out.append(current)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder', help='a block data folder')
    parser.add_argument('--workers', type=int, default=max(1, multiprocessing.cpu_count() - 2))
    parser.add_argument('--from-csv', action='store_true',
                        help='the frames from mirror_aoi.csv (an earlier run): only the glances again')
    args = parser.parse_args()
    import cv2  # pylint: disable=import-outside-toplevel
    folder = os.path.abspath(args.folder)
    for name in ('mirrors.json', 'bezel_screen.json'):
        if not os.path.exists(os.path.join(folder, name)):
            raise SystemExit('%s missing in %s (%s)' % (name, folder, 'abc_experiment writes it' if name == 'mirrors.json'
                                                         else 'mirror_register.py, copied in by abc_experiment'))
    run = g2_block.Run(folder)
    if args.from_csv:
        finish(folder, run, read_rows(folder), STEP / 50.0)
        return
    capture = cv2.VideoCapture(run.video)
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = capture.get(cv2.CAP_PROP_FPS) or 50.0
    capture.release()
    frame_s = STEP / fps
    chunk = int(math.ceil(frames / float(args.workers * 4) / STEP)) * STEP
    jobs = [(folder, k, min(frames, k + chunk)) for k in range(0, frames, chunk)]
    print('%d frames, %d jobs on %d workers...' % (frames, len(jobs), args.workers))
    results = []
    with multiprocessing.Pool(args.workers) as pool:
        for k, part in enumerate(pool.imap(_work, jobs)):
            results.extend(part)
            print('\r  %d of %d' % (k + 1, len(jobs)), end='')
    print()
    results.sort(key=lambda r: r[0])
    rows = []
    for index, msec, row in results:
        row['t_sim'] = round(run.sim_of_pc(run.pc_of_ts(run.ts_of_msec(msec))), 3)
        row['frame'] = index
        rows.append(row)
    finish(folder, run, rows, frame_s)


def read_rows(folder):
    """mirror_aoi.csv's frames (not its dropout rows: made again), numbers as numbers."""
    rows = []
    with open(os.path.join(folder, 'mirror_aoi.csv'), encoding='utf-8') as handle:
        for r in csv.DictReader(handle):
            if r.get('dropout'):
                continue
            row = {k: v for k, v in r.items() if v not in ('', None)}
            for k in ['t_sim', 'eye_yaw', 'eye_pitch'] + ['%s_deg' % m for m in MIRRORS]:
                if k in row:
                    row[k] = float(row[k])
            row.setdefault('mirror', '')
            row.setdefault('unsure', '')
            row.pop('glance', None)
            rows.append(row)
    return rows


def dropouts(run, frame_s):
    """Rows for the eye-data dropouts at a side (DROPOUT_*): every frame_s, unsure, dropout 1."""
    eye = [e for e in run.eye if run.in_block(run.pc_of_ts(e[0]))]
    out = []
    for (t0, y0, _, _), (t1, y1, _, _) in zip(eye, eye[1:]):
        if not DROPOUT_MIN_S <= (t1 - t0) / 1e6 <= DROPOUT_MAX_S:
            continue
        if min(y0, y1) >= DROPOUT_SIDE_DEG:
            side = 'left?'
        elif max(y0, y1) <= -DROPOUT_SIDE_DEG:
            side = 'right?'
        else:
            continue
        s0, s1 = run.sim_of_pc(run.pc_of_ts(t0)), run.sim_of_pc(run.pc_of_ts(t1))
        t = s0 + frame_s / 2
        while t < s1:
            out.append({'t_sim': round(t, 3), 'mirror': '', 'unsure': side, 'dropout': 1})
            t += frame_s
    return out


def join(runs, unsure, frame_s):
    """The glances with the unsure runs of their side within JOIN_S joined in (chained), then two
    glances at one mirror within JOIN_S as one: ([(mirror, start, end, unsure s)], the unsure runs
    left over)."""
    glances = [[m, s, e, 0.0] for m, s, e in sorted(runs, key=lambda g: g[1])]
    rest = sorted(unsure, key=lambda g: g[1])
    changed = True
    while changed:
        changed = False
        for u in list(rest):
            for g in glances:
                if SIDE_MIRROR[u[0]] == g[0] and u[1] - g[2] <= JOIN_S + 1e-6 and g[1] - u[2] <= JOIN_S + 1e-6:
                    g[1], g[2] = min(g[1], u[1]), max(g[2], u[2])
                    g[3] += u[2] - u[1] + frame_s
                    rest.remove(u)
                    changed = True
                    break
    merged = []
    for g in sorted(glances, key=lambda g: g[1]):
        if merged and merged[-1][0] == g[0] and g[1] - merged[-1][2] <= JOIN_S + 1e-6:
            merged[-1][2] = max(merged[-1][2], g[2])
            merged[-1][3] += g[3]
        else:
            merged.append(g)
    return [tuple(g) for g in merged], rest


def segments(folder, run):
    """[(name, start, end)] in sim s: the whole drive, the automated drive (to the TOR alert), the
    RATE_PRE_S before each SAGAT freeze, RATE_PRE_S before and RATE_POST_S after the TOR alert."""
    end = run.ft[-1] if run.ft else 0.0
    out = [('block', 0.0, end)]
    events = []
    try:
        with open(os.path.join(folder, 'run.json'), encoding='utf-8') as handle:
            events = json.load(handle).get('events', [])
    except (OSError, ValueError):
        pass
    alert = None
    try:
        with open(os.path.join(folder, 'tor_events.csv'), encoding='utf-8') as handle:
            alert = next((float(r['t_tor']) for r in csv.DictReader(handle) if r.get('t_tor')), None)
    except OSError:
        pass
    out.append(('auto', 0.0, alert if alert is not None else end))
    for e in events:
        if e.get('type') == 'Q':
            out.append(('sagat_pre %s' % e['id'], max(0.0, e['t'] - RATE_PRE_S), float(e['t'])))
    if alert is not None:
        out.append(('tor_pre', max(0.0, alert - RATE_PRE_S), alert))
        out.append(('tor_post', alert, min(end, alert + RATE_POST_S)))
    return out


def write_rates(folder, run, rows, joined, unsure, frame_s):
    """mirror_aoi_rates.csv: per segment (start, end: sim s; real_s: its real time) and mirror, the
    glances (count by their start, per minute of real time: the main measure; dwell sim s and its share
    of the segment: secondary - always short, see TODO 4) as judged (the glances, unsure runs next to
    them joined in) and with the unsure runs left over counted as glances at that side's mirror too
    (_with_unsure, sensitivity); eye_data_share: Glasses 2 samples with the eyes' data over G2_HZ."""
    import bisect  # pylint: disable=import-outside-toplevel
    sure = [(m, s, e) for m, s, e, _ in joined]
    loose = sure + [(SIDE_MIRROR[m], s, e) for m, s, e in unsure]
    eye_pc = sorted(run.pc_of_ts(e[0]) for e in run.eye)
    # the drive's stretches between SAGAT freezes [(sim, sim, pc, pc)] (frames.csv: no frames while
    # frozen; the sim also runs slower than real time when the server cannot keep up)
    stretches = []
    for k, (t, w) in enumerate(zip(run.ft, run.fw)):
        if stretches and w - stretches[-1][3] <= FREEZE_GAP_S:
            stretches[-1][1], stretches[-1][3] = t, w
        else:
            stretches.append([t, t, w, w])

    def real_parts(a, b):
        """[(pc, pc)] of sim a..b, the freezes left out."""
        parts = []
        for s0, s1, w0, w1 in stretches:
            lo, hi = max(a, s0), min(b, s1)
            if hi <= lo:
                continue
            at = (lambda t: w0 + (w1 - w0) * (t - s0) / (s1 - s0)) if s1 > s0 else (lambda t: w0)
            parts.append((at(lo), at(hi)))
        return parts

    out = []
    for name, a, b in segments(folder, run):
        parts = real_parts(a, b)
        real = max(sum(q - p for p, q in parts), 1e-6)
        minutes = real / 60.0         # glances per minute of real time: the eyes go at real time
        samples = sum(bisect.bisect_left(eye_pc, q) - bisect.bisect_left(eye_pc, p) for p, q in parts)
        data = min(1.0, samples / (real * G2_HZ))
        row = {'segment': name, 'start': round(a, 2), 'end': round(b, 2), 'real_s': round(real, 1),
               'eye_data_share': round(data, 3)}
        for label, glances in (('', sure), ('_with_unsure', loose)):
            for m in MIRRORS:
                mine = [(s, e) for g, s, e in glances if g == m]
                n = sum(1 for s, e in mine if a <= s < b)
                dwell = sum(max(0.0, min(e + frame_s, b) - max(s, a)) for s, e in mine if e + frame_s > a and s < b)
                row.update({'%s_n%s' % (m, label): n, '%s_per_min%s' % (m, label): round(n / minutes, 2),
                            '%s_dwell_s%s' % (m, label): round(dwell, 2),
                            '%s_dwell_share%s' % (m, label): round(dwell / max(b - a, 1e-6), 4)})
        out.append(row)
    with open(os.path.join(folder, 'mirror_aoi_rates.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    print('\nglances per minute (with the unsure runs too):')
    for r in out:
        print('  %-16s %6.1f-%-6.1f eye data %3.0f %%   ' % (r['segment'], r['start'], r['end'], 100 * r['eye_data_share']) +
              '   '.join('%s %.1f (%.1f)' % (m, r['%s_per_min' % m], r['%s_per_min_with_unsure' % m]) for m in MIRRORS))


def finish(folder, run, rows, frame_s):
    """The glances from the frames (and the dropouts), the files out, the summary printed."""
    rows = sorted(rows + dropouts(run, frame_s), key=lambda r: r['t_sim'])
    states = classify(rows)
    for row, state in zip(rows, states):
        row['glance'] = state or ''
    sure = g2_block.glances([(row['t_sim'], state) for row, state in zip(rows, states)])
    joined, unsure = join(sure, g2_block.glances([(row['t_sim'], row['unsure'] or None) for row in rows]), frame_s)
    # the frames of a joined unsure run: that glance's mirror (sagat_gaze and the like read the glance column)
    for row in rows:
        if row['unsure'] and not row['glance']:
            row['glance'] = next((m for m, s, e, _ in joined
                                  if s <= row['t_sim'] <= e and m == SIDE_MIRROR[row['unsure']]), '')
    keys = ['t_sim', 'frame', 'gaze_x_px', 'gaze_y_px', 'eye_yaw', 'eye_pitch', 'markers_left', 'markers_right',
            'fit_left_px', 'fit_right_px', 'window_monitor', 'window_x_px', 'window_y_px'] + \
           ['%s_deg' % m for m in MIRRORS] + ['mirror', 'glance', 'unsure', 'dropout']
    with open(os.path.join(folder, 'mirror_aoi.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    runs = [(m, s, e) for m, s, e, _ in joined]
    with open(os.path.join(folder, 'mirror_aoi_glances.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['mirror', 'start', 'end', 'duration_s', 'frames', 'min_deg', 'unsure_s'])
        for mirror, start, end, unsure_s in sorted(joined + [(m, s, e, None) for m, s, e in unsure],
                                                   key=lambda g: g[1]):
            if unsure_s is None:
                n = sum(1 for r in rows if start <= r['t_sim'] <= end and r['unsure'] == mirror)
                writer.writerow([mirror, round(start, 2), round(end, 2), round(end - start + frame_s, 2), n, '', ''])
                continue
            inside = [r for r, s in zip(rows, states) if start <= r['t_sim'] <= end and s == mirror]
            writer.writerow([mirror, round(start, 2), round(end, 2), round(end - start + frame_s, 2), len(inside),
                             min(r['%s_deg' % mirror] for r in inside), round(unsure_s, 2)])
    g2_block.write_windows(folder, 'mirror_aoi_windows.csv', [r['t_sim'] for r in rows if not r['unsure']], runs,
                           frame_s)
    write_rates(folder, run, rows, joined, unsure, frame_s)
    total ={m: sum(e - s + frame_s for mm_, s, e in runs if mm_ == m) for m in MIRRORS}
    print('\nglances in the block: ' + ', '.join('%s %d (%.1f s, of it unsure %.1f s)' % (
        m, sum(1 for r in runs if r[0] == m), total[m], sum(u for g, _, _, u in joined if g == m)) for m in MIRRORS))
    print('  only the frames with a gaze point: ' + ', '.join('%s %d (%.1f s)' % (
        m, sum(1 for r in sure if r[0] == m), sum(e - s + frame_s for g, s, e in sure if g == m)) for m in MIRRORS))
    print('dropouts at a side (no eye data, DROPOUT_*): ' + ', '.join('%s %.1f s' % (
        u, frame_s * sum(1 for r in rows if r.get('dropout') and r['unsure'] == u)) for u in ('left?', 'right?')))
    print('unsure, not part of a glance (no gaze point, eyes %d deg or more to a side, or a dropout there): %s' % (
        UNSURE_DEG, ', '.join(
        '%s %d (%.1f s)' % (u, sum(1 for g in unsure if g[0] == u), sum(e - s + frame_s for g_, s, e in unsure if g_ == u))
        for u in ('left?', 'right?'))))
    judged = [r for r in rows if not r['unsure']]
    n = float(len(judged)) or 1.0
    for monitor in ('left', 'right'):
        print('%s monitor: >= %d markers in %.0f %% of the frames with a gaze point' % (
            monitor, MIN_MARKERS, 100 * sum(1 for r in judged if len(r.get('markers_%s' % monitor, '').split()) >= MIN_MARKERS) / n))


if __name__ == '__main__':
    main()
