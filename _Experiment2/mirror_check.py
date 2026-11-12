#!/usr/bin/env python

"""
How well mirror_aoi.py finds the mirror glances: a test drive where the driver marks each look at a
mirror, against mirror_aoi.csv.

    python _Experiment2/mirror_check.py <block folder>

The marks (abc_experiment logs them; the car drives itself, so they change nothing - end the drive
before the TOR, e.g. --duration 170):
    left side mirror    the left paddle held while looking   (events.csv: paddle left down / up)
    right side mirror   the right paddle held                (paddle right down / up)
    rear-view mirror    the accelerator pressed              (frames.csv: pedal_throttle > PEDAL_ON)
Looks elsewhere (the road, the window next to a mirror) are left unmarked: the frames judged on a
mirror there are the false ones.

Each marked look: TRIM_S off both ends (the hand / foot lags the eyes), then the share of its frames
judged on that mirror, on another mirror, unsure (no gaze point, the eyes far to a side: mirror_aoi's
'left?' / 'right?'), or on none, and whether the look was found at all; the median eye yaw in the
head. The marked frames by eye yaw (the gaze's accuracy falls with it; past about 42 degrees Glasses 2
has no gaze point). Unmarked frames (MARGIN_S away from any mark): the share judged on each mirror.
"""

from __future__ import print_function

import argparse
import csv
import os
import statistics

PEDAL_ON = 0.3
TRIM_S = 0.3
MARGIN_S = 1.0
YAW_BINS = ((0, 15), (15, 25), (25, 35), (35, 42), (42, 90))
MIRRORS = ('left', 'rear', 'right')


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def marks(folder):
    """[(mirror, start, end)] in sim s."""
    out = []
    held = {}
    for r in read(os.path.join(folder, 'events.csv')):
        what = r['what'].split()
        if len(what) == 3 and what[0] == 'paddle':
            side, state, t = what[1], what[2], float(r['t_sim'])
            if state == 'down':
                held[side] = t
            elif side in held:
                out.append((side, held.pop(side), t))
    start = None
    last = None
    for r in read(os.path.join(folder, 'frames.csv')):
        t = float(r['t_sim'])
        on = float(r.get('pedal_throttle') or 0) > PEDAL_ON
        if on and start is None:
            start = t
        elif not on and start is not None:
            out.append(('rear', start, t))
            start = None
        last = t
    if start is not None:
        out.append(('rear', start, last))
    return sorted(out, key=lambda m: m[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder')
    args = parser.parse_args()
    folder = os.path.abspath(args.folder)
    looks = marks(folder)
    if not looks:
        raise SystemExit('No marks (paddle held / accelerator pressed) in %s' % folder)
    aoi = read(os.path.join(folder, 'mirror_aoi.csv'))
    if not aoi:
        raise SystemExit('No mirror_aoi.csv in %s: run mirror_aoi.py first' % folder)
    # (t, glance, unsure, |eye yaw| or None)
    rows = [(float(r['t_sim']), r['glance'], r['unsure'], abs(float(r['eye_yaw'])) if r['eye_yaw'] else None)
            for r in aoi]
    print('%d marked looks: %s' % (len(looks), ', '.join('%s %d' % (m, sum(1 for l in looks if l[0] == m))
                                                         for m in MIRRORS)))
    print('%-6s %-11s %7s %6s %7s %7s %7s %7s  %s' % ('mirror', 'when', 'eye yaw', 'frames', 'on it', 'other',
                                                       'unsure', 'none', 'found'))
    found_by = {}
    for mirror, t0, t1 in looks:
        inside = [r for r in rows if t0 + TRIM_S <= r[0] <= t1 - TRIM_S]
        n = len(inside)
        on = sum(1 for r in inside if r[1] == mirror)
        other = sum(1 for r in inside if r[1] and r[1] != mirror)
        unsure = sum(1 for r in inside if r[2])
        ys = [r[3] for r in inside if r[3] is not None]
        found_by.setdefault(mirror, []).append(on > 0)
        pct = (lambda k: 100.0 * k / n if n else 0.0)
        print('%-6s %5.1f-%-5.1f %7s %6d %6.0f%% %6.0f%% %6.0f%% %6.0f%%  %s' % (
            mirror, t0, t1, '%.0f' % statistics.median(ys) if ys else '-', n, pct(on), pct(other), pct(unsure),
            pct(n - on - other - unsure), 'yes' if on else 'NO'))
    print('looks found: ' + '   '.join('%s %d of %d' % (m, sum(f), len(f)) for m, f in sorted(found_by.items())))
    marked = [(m, r) for m, a, b in looks for r in rows if a + TRIM_S <= r[0] <= b - TRIM_S and r[3] is not None]
    print('marked frames by |eye yaw|:  ' + '   '.join(
        '%d-%d deg: %d%% of %d (unsure %d%%)' % (lo, hi, 100.0 * sum(1 for m, r in fr if r[1] == m) / len(fr), len(fr),
                                                100.0 * sum(1 for m, r in fr if r[2]) / len(fr))
        for lo, hi, fr in [(lo, hi, [(m, r) for m, r in marked if lo <= r[3] < hi]) for lo, hi in YAW_BINS] if fr))
    free = [r for r in rows if all(r[0] < s - MARGIN_S or r[0] > e + MARGIN_S for _, s, e in looks)]
    if free:
        print('unmarked frames: %d, judged on a mirror: %s; unsure %.1f%%' % (len(free), ', '.join(
            '%s %.1f%%' % (m, 100.0 * sum(1 for r in free if r[1] == m) / len(free)) for m in MIRRORS),
            100.0 * sum(1 for r in free if r[2]) / len(free)))


if __name__ == '__main__':
    main()
