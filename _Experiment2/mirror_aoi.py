#!/usr/bin/env python

"""
Mirror glances from the Glasses 2 gaze through the bezel markers: the gaze put in the experiment
window's pixels, where the mirrors are drawn. The mirror need not be in the scene video's picture
(with the eyes only turned to it, it is at or past the frame's edge), only markers of its monitor.

    python _Experiment2/mirror_aoi.py <block folder>

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
mirror_check 1112173906 (glances marked by the driver): with the gaze point, the eyes up to 25
degrees in the head 72-78 % of the marked frames on the mirror, 25-35: 45 %, 35-42: 25 %; unmarked
frames on a mirror 0.1-0.3 %.

Out, into the folder:
    mirror_aoi.csv          per frame looked at: sim time, gaze (scene px) or none, the eyes' angles,
                            the markers per monitor, the gaze in window px and its monitor, each
                            mirror's distance (deg), the mirror of this frame alone and with the
                            hysteresis (glance), unsure
    mirror_aoi_glances.csv  the glances (mirror, start, end, s, frames, closest deg), and the unsure
                            runs as mirror 'left?' / 'right?'
    mirror_aoi_windows.csv  per event window and the TOR: the AOI mirror glanced or not, first glance,
                            dwell, the other mirrors' dwell
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
    args = parser.parse_args()
    import cv2  # pylint: disable=import-outside-toplevel
    folder = os.path.abspath(args.folder)
    for name in ('mirrors.json', 'bezel_screen.json'):
        if not os.path.exists(os.path.join(folder, name)):
            raise SystemExit('%s missing in %s (%s)' % (name, folder, 'abc_experiment writes it' if name == 'mirrors.json'
                                                         else 'mirror_register.py, copied in by abc_experiment'))
    run = g2_block.Run(folder)
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
    states = classify(rows)
    for row, state in zip(rows, states):
        row['glance'] = state or ''
    keys = ['t_sim', 'frame', 'gaze_x_px', 'gaze_y_px', 'eye_yaw', 'eye_pitch', 'markers_left', 'markers_right',
            'fit_left_px', 'fit_right_px', 'window_monitor', 'window_x_px', 'window_y_px'] + \
           ['%s_deg' % m for m in MIRRORS] + ['mirror', 'glance', 'unsure']
    with open(os.path.join(folder, 'mirror_aoi.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    runs = g2_block.glances([(row['t_sim'], state) for row, state in zip(rows, states)])
    unsure = g2_block.glances([(row['t_sim'], row['unsure'] or None) for row in rows])
    with open(os.path.join(folder, 'mirror_aoi_glances.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['mirror', 'start', 'end', 'duration_s', 'frames', 'min_deg'])
        for mirror, start, end in sorted(runs + unsure, key=lambda g: g[1]):
            if mirror.endswith('?'):
                n = sum(1 for r in rows if start <= r['t_sim'] <= end and r['unsure'] == mirror)
                writer.writerow([mirror, round(start, 2), round(end, 2), round(end - start + frame_s, 2), n, ''])
                continue
            inside = [r for r, s in zip(rows, states) if start <= r['t_sim'] <= end and s == mirror]
            writer.writerow([mirror, round(start, 2), round(end, 2), round(end - start + frame_s, 2), len(inside),
                             min(r['%s_deg' % mirror] for r in inside)])
    g2_block.write_windows(folder, 'mirror_aoi_windows.csv', [r['t_sim'] for r in rows if not r['unsure']], runs,
                           frame_s)
    total = {m: sum(e - s + frame_s for mm_, s, e in runs if mm_ == m) for m in MIRRORS}
    print('\nglances in the block: ' + ', '.join('%s %d (%.1f s)' % (m, sum(1 for r in runs if r[0] == m), total[m])
                                               for m in MIRRORS))
    print('unsure (no gaze point, the eyes %d deg or more to a side): %s' % (UNSURE_DEG, ', '.join(
        '%s %d (%.1f s)' % (u, sum(1 for g in unsure if g[0] == u), sum(e - s + frame_s for g_, s, e in unsure if g_ == u))
        for u in ('left?', 'right?'))))
    judged = [r for r in rows if not r['unsure']]
    n = float(len(judged)) or 1.0
    for monitor in ('left', 'right'):
        print('%s monitor: >= %d markers in %.0f %% of the frames with a gaze point' % (
            monitor, MIN_MARKERS, 100 * sum(1 for r in judged if len(r.get('markers_%s' % monitor, '').split()) >= MIN_MARKERS) / n))


if __name__ == '__main__':
    main()
