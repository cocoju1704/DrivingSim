#!/usr/bin/env python

"""
After a block (abc_experiment.py starts this by itself at the end of a run with the Glasses 2
streams; or by hand): the gaze analyses of the block folder, in the background at idle priority,
so a block started meanwhile keeps its frame rate. Log: <folder>/postprocess.log.

    1. mirror_gaze.py --images      mirror glances (mirror_gaze.csv, mirror_glances.csv,
                                    mirror_windows.csv, mirror_gaze/)
    2. sagat_gaze.csv               the gaze before each SAGAT freeze (below)
    3. gaze_video.py                gaze_video.mp4: the scene video with the gaze and the drive

    python _Experiment2/postprocess.py <block folder>
    python _Experiment2/postprocess.py <block folder> --detach      (what the experiment does)

sagat_gaze.csv, one row per question, over the PRE_S seconds of driving before the freeze: the
share of the gaze on the glasses display (the glasses condition: its outline from
g2_display.json, +15 %), off it, and the time since the gaze last left it; the mirror glances in
those seconds (mirror_gaze.csv). What a driver could know at the freeze depends on whether they
looked up just before it, so the SAGAT scores are read with these.
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
        code = subprocess.call([sys.executable] + args, stdout=handle, stderr=subprocess.STDOUT, cwd=HERE)
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


def sagat_gaze(folder):
    sys.path.insert(0, HERE)
    import g2_validate  # pylint: disable=import-outside-toplevel
    with open(os.path.join(folder, 'sagat.json'), encoding='utf-8') as handle:
        questions = json.load(handle)
    with open(os.path.join(folder, 'g2_sync.json'), encoding='utf-8') as handle:
        a, b = json.load(handle)['ts_to_pc']
    f_t, f_w = [], []
    with open(os.path.join(folder, 'frames.csv'), encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            f_t.append(float(row['t_sim']))
            f_w.append(float(row['wall_time']))

    def sim_to_pc(t):
        # the last frame at or before t: the frames of a freeze share one sim time
        i = max(bisect.bisect_right(f_t, t) - 1, 0)
        return f_w[i]

    gaze = []
    with open(os.path.join(folder, 'g2_data.jsonl'), encoding='utf-8') as handle:
        for line in handle:
            _, _, text = line.partition(' ')
            try:
                p = json.loads(text)
            except ValueError:
                continue
            if 'gp' in p and p.get('s') == 0:
                gaze.append((p['ts'] / 1e6 + a * p['ts'] + b, p['gp'][0], p['gp'][1]))
    gaze.sort()
    g_w = [g[0] for g in gaze]
    outline = None
    path = os.path.join(folder, 'g2_display.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as handle:
            display = json.load(handle)
        corners = ('tl', 'tr', 'br', 'bl')
        h = g2_validate.homography([display['dots'][d]['display_px'] for d in corners],
                                   [display['dots'][d]['gp'] for d in corners])
        outline = [g2_validate.apply(h, x, y) for x, y in ((0, 0), (600, 0), (600, 600), (0, 600))]
    mirrors = []
    path = os.path.join(folder, 'mirror_gaze.csv')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as handle:
            mirrors = [(float(r['t_sim']), r.get('glance') or r['mirror']) for r in csv.DictReader(handle)
                       if r.get('glance') or r['mirror']]

    rows = []
    for q in questions:
        t = float(q['t'])
        w1 = sim_to_pc(t - 0.05)
        w0 = sim_to_pc(t - PRE_S)
        samples = gaze[bisect.bisect_left(g_w, w0):bisect.bisect_right(g_w, w1)]
        score = q.get('score') or {}
        row = {'id': q['id'], 't': t, 'pre_s': PRE_S, 'valid_samples': len(samples), 'score': score.get('score'),
               'mirrors': score.get('mirrors'), 'beside': score.get('beside'), 'ahead': score.get('ahead')}
        if outline and samples:
            on = [inside(outline, x, y, DISPLAY_MARGIN) for _, x, y in samples]
            row['on_display_share'] = round(sum(on) / float(len(on)), 3)
            last_off = next((samples[i][0] for i in range(len(samples) - 1, -1, -1) if not on[i]), None)
            row['since_last_off_display_s'] = round(w1 - last_off, 2) if last_off else ''
            # the longest stretch off the display
            longest = run = 0.0
            for i in range(1, len(samples)):
                if not on[i] and not on[i - 1]:
                    run += samples[i][0] - samples[i - 1][0]
                    longest = max(longest, run)
                else:
                    run = 0.0
            row['longest_off_display_s'] = round(longest, 2)
        for name in ('left', 'rear', 'right'):
            row['%s_mirror_frames' % name] = sum(1 for mt, m in mirrors if t - PRE_S <= mt < t and m == name)
        rows.append(row)
    keys = ['id', 't', 'pre_s', 'valid_samples', 'on_display_share', 'since_last_off_display_s',
            'longest_off_display_s', 'left_mirror_frames', 'rear_mirror_frames', 'right_mirror_frames', 'score',
            'mirrors', 'beside', 'ahead']
    with open(os.path.join(folder, 'sagat_gaze.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    for row in rows:
        log(folder, '  %s: on the display %s, since the gaze last left it %s s, mirror frames L%d R%d Rt%d, score %s' % (
            row['id'], row.get('on_display_share', '-'), row.get('since_last_off_display_s', '-'),
            row['left_mirror_frames'], row['rear_mirror_frames'], row['right_mirror_frames'], row['score']))


def detach(folder):
    """Starts this script on its own, idle priority, no window: the experiment does not wait."""
    flags = 0
    if os.name == 'nt':
        flags = 0x00000008 | 0x00000200 | 0x00000040 | 0x08000000  # DETACHED, NEW_GROUP, IDLE, NO_WINDOW
    subprocess.Popen([sys.executable, os.path.abspath(__file__), folder], cwd=HERE, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder')
    parser.add_argument('--detach', action='store_true', help='start in the background and return at once')
    parser.add_argument('--workers', type=int, default=6, help='mirror_gaze.py workers')
    args = parser.parse_args()
    folder = os.path.abspath(args.folder)
    if args.detach:
        detach(folder)
        return
    log(folder, 'postprocess %s' % folder)
    if not wait_for_streams(folder):
        log(folder, 'no g2_sync.json: no Glasses 2 streams in this block, nothing to do')
        return
    run_step(folder, [os.path.join(HERE, 'mirror_gaze.py'), folder, '--images', '--workers', str(args.workers)])
    try:
        sagat_gaze(folder)
    except Exception as error:  # pylint: disable=broad-except
        log(folder, 'sagat_gaze failed: %s' % error)
    run_step(folder, [os.path.join(HERE, 'gaze_video.py'), folder])
    log(folder, 'done')


if __name__ == '__main__':
    main()
