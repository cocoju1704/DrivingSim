#!/usr/bin/env python

"""
The video questions' real timing: how many seconds before the SAGAT freeze each scene of a question
really was on the NDRT video. Until 2026-11-14 the simulation ran 1.1-1.4 % faster than real time (a
frame cap of 34.5 fps), so the video (real time) was behind the drive at the freezes (2-7 s by the
third), and the 'shown' scenes planned 5 s before a stop were 1-4 s before it; a device's own
playback can be off too (the phone app played on from a former run). ndrt_items.json's before_stop_s
assumes the video at stop_t at the freeze; here the video's position at the freeze is what the
device reported (events.csv: 'video freeze: <glasses|phone|hud> at <t> s').

    python _Experiment2/ndrt_timing.py <block folder> [<block folder> ...] [--out all.csv]

Out, per folder: ndrt_timing.csv, one row per video question item (ndrt.csv, else the set's items
in ndrt_items.json): the stop, the video's position at the freeze (freeze_video_t; '' when the device
did not report it), sim_per_real (the drive to the freeze, frames.csv), video_lag_s = stop_t - freeze_video_t (+: the video behind the drive),
planned_before_s, real_before_s = freeze_video_t - video_t (the scene that long before the freeze;
negative: it had not been played yet, the 'shown' item was not shown), the answer and whether right.
With --out also all rows of all folders in one file.
"""

from __future__ import print_function

import argparse
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = os.path.join(HERE, 'ndrt_items', 'ndrt_items.json')
FREEZE = re.compile(r'video freeze: (\w+) at ([-\d.]+|None) s')


def freezes(folder):
    """{stop id: (device, video s at the freeze or None)} from events.csv (the first freeze per stop)."""
    out = {}
    with open(os.path.join(folder, 'events.csv'), encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            m = FREEZE.search(row.get('what') or '')
            if m and row.get('id') and row['id'] != '-' and row['id'] not in out:
                out[row['id']] = (m.group(1), None if m.group(2) == 'None' else float(m.group(2)))
    return out


def sim_per_real(folder, until):
    """Sim s per real s of the drive up to sim time until (frames.csv; the SAGAT freezes, frames more
    than 0.5 s apart, left out): above 1 the drive ran fast (the video, at real time, falls behind)."""
    sim = real = 0.0
    prev = None
    with open(os.path.join(folder, 'frames.csv'), encoding='utf-8') as handle:
        for r in csv.DictReader(handle):
            t, w = float(r['t_sim']), float(r['wall_time'])
            if t > until:
                break
            if prev and w - prev[1] <= 0.5:
                sim += t - prev[0]
                real += w - prev[1]
            prev = (t, w)
    return round(sim / real, 4) if real else ''


def real_times(folder):
    """[row dict] per video question item of the block (see the module's doc)."""
    with open(os.path.join(folder, 'run.json'), encoding='utf-8') as handle:
        args = json.load(handle).get('args') or {}
    with open(ITEMS, encoding='utf-8') as handle:
        sets = json.load(handle)
    stops = (sets.get(args.get('set')) or {}).get('stops') or {}
    answers = {}
    path = os.path.join(folder, 'ndrt.csv')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as handle:
            for r in csv.DictReader(handle):
                answers[(r['qid'], r['image'])] = r
    frozen = freezes(folder)
    rows = []
    for qid, stop in sorted(stops.items(), key=lambda s: s[1]['stop_t']):
        device, at = frozen.get(qid, ('', None))
        rate = sim_per_real(folder, stop['stop_t'])
        for k, item in enumerate(stop['items'], 1):
            a = answers.get((qid, item['image']), {})
            vt = item.get('video_t')
            row = {'block': os.path.basename(folder), 'participant': args.get('participant'), 'set': args.get('set'),
                   'condition': args.get('condition'), 'qid': qid, 'k': k, 'image': item['image'],
                   'in_video': int(bool(item.get('shown'))), 'stop_t': stop['stop_t'], 'sim_per_real': rate, 'device': device,
                   'freeze_video_t': '' if at is None else at,
                   'video_lag_s': '' if at is None else round(stop['stop_t'] - at, 2),
                   'video_t': '' if vt is None else vt,
                   'planned_before_s': item.get('before_stop_s', ''),
                   'real_before_s': '' if at is None or vt is None else round(at - vt, 2),
                   'answer': a.get('answer', ''), 'confidence': a.get('confidence', ''), 'correct': a.get('correct', '')}
            if vt is not None and at is not None:
                row['shown_before_freeze'] = int(at - vt >= 0)
            rows.append(row)
    return rows


KEYS = ['block', 'participant', 'set', 'condition', 'qid', 'k', 'image', 'in_video', 'stop_t', 'sim_per_real', 'device',
        'freeze_video_t', 'video_lag_s', 'video_t', 'planned_before_s', 'real_before_s', 'shown_before_freeze',
        'answer', 'confidence', 'correct']


def write(path, rows):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=KEYS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folders', nargs='+')
    parser.add_argument('--out', help='all rows in one CSV too')
    args = parser.parse_args()
    everything = []
    for folder in args.folders:
        folder = os.path.abspath(folder)
        try:
            rows = real_times(folder)
        except (OSError, ValueError) as error:
            print('%s: %s' % (os.path.basename(folder), error))
            continue
        write(os.path.join(folder, 'ndrt_timing.csv'), rows)
        everything.extend(rows)
        print('%s (set %s, %s):' % (os.path.basename(folder), rows[0]['set'] if rows else '?',
                                    rows[0]['condition'] if rows else '?'))
        for qid in sorted({r['qid'] for r in rows}):
            mine = [r for r in rows if r['qid'] == qid]
            shown = ', '.join('%s %s -> %s s%s' % (r['image'].split('/')[-1], r['planned_before_s'], r['real_before_s'],
                                                  '' if r['answer'] == '' else ' (%s)' % ('right' if r['correct'] == 'True'
                                                                                          else 'wrong'))
                              for r in mine if r['in_video'])
            print('  %s stop %s (sim/real %s): video at %s (%s, lag %s s); shown scenes planned -> real s before: %s' % (
                qid, mine[0]['stop_t'], mine[0]['sim_per_real'], mine[0]['freeze_video_t'] or '-', mine[0]['device'] or '-',
                mine[0]['video_lag_s'] if mine[0]['video_lag_s'] != '' else '-', shown))
    if args.out and everything:
        write(args.out, everything)
        print('written: %s' % args.out)


if __name__ == '__main__':
    main()
