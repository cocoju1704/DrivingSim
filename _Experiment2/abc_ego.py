#!/usr/bin/env python

"""
Where the ego car is in a curve, as a function of the block's time: Town04's figure-8 is about half
curves, and the events of a set should happen on the straights.

The ego car drives the same loop at the same speed profile every run (the autonomous driving of
carla_base.LoopFollower: 95 km/h, slower in the curves; it reacts to nothing). So one recorded run
gives the speed and the curvature at each point of the loop (make_profile, from a frames.csv), and
from that, for any start point along the loop, the time line of curves (predict).

    python _Experiment2/abc_ego.py --log _Experiment2/Data/test/<run>/frames.csv
        -> schedules/ego_profile.json, and how well it predicts that run's own curves
    python _Experiment2/abc_ego.py --start 1200      the curve intervals starting 1200 m along the loop

The run for the profile may start anywhere: --log-start gives where (its schedule's ego_start_m).
"""

from __future__ import print_function

import argparse
import csv
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_FILE = os.path.join(HERE, 'schedules', 'ego_profile.json')
BIN = 2.0                 # m per profile point
CURVE_RADIUS = 800.0      # m: tighter than this is a curve
STEP = 0.05               # s, prediction
START_SPEED = 95.0 / 3.6  # m/s at the block start
CURVE_DECEL = 0.8         # m/s^2, carla_base.CURVE_DECEL
AUTO_ACCEL = 2.0          # m/s^2, carla_base.AUTO_ACCEL


def make_profile(path, start_m=0.0):
    """start_m: where along the loop that run started (its schedule's ego_start_m)."""
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    ts = [float(r['t_sim']) for r in rows]
    xs = [float(r['ego_x']) for r in rows]
    ys = [float(r['ego_y']) for r in rows]
    vs = [float(r['speed_kmh']) / 3.6 for r in rows]
    dist = [0.0]
    for k in range(1, len(rows)):
        dist.append(dist[-1] + math.hypot(xs[k] - xs[k - 1], ys[k] - ys[k - 1]))
    # loop length: the first return to the start point, once well away from it
    length = None
    for k in range(len(rows)):
        if dist[k] > 1000.0 and math.hypot(xs[k] - xs[0], ys[k] - ys[0]) < 3.0:
            # refine: closest point of this pass
            best = min(range(k, min(k + 200, len(rows))), key=lambda j: math.hypot(xs[j] - xs[0], ys[j] - ys[0]))
            length = dist[best] + math.hypot(xs[best] - xs[0], ys[best] - ys[0])
            break
    if length is None:
        raise RuntimeError('%s does not go once round the loop' % path)
    bins = int(math.ceil(length / BIN))
    moved, spent = [0.0] * bins, [0.0] * bins  # per bin: metres driven and seconds spent in it
    where = [None] * bins
    for k in range(1, len(rows)):
        b = int(((dist[k] + start_m) % length) / BIN) % bins
        if ts[k] > 40.0 and rows[k]['mode'] == 'AUTO':  # past the start's speed-up, before any TOR
            moved[b] += dist[k] - dist[k - 1]
            spent[b] += ts[k] - ts[k - 1]
        if where[b] is None:
            where[b] = (xs[k], ys[k])
    speed = [moved[b] / spent[b] if spent[b] > 0 else None for b in range(bins)]
    _fill(speed)
    _fill(where)
    half = 10  # bins on each side: the turn between the 20 m before and the 20 m after (as log_intervals)
    curvature = []
    for b in range(bins):
        (x0, y0), (x1, y1), (x2, y2) = where[(b - half) % bins], where[b], where[(b + half) % bins]
        turn = (math.atan2(y2 - y1, x2 - x1) - math.atan2(y1 - y0, x1 - x0) + math.pi) % (2 * math.pi) - math.pi
        curvature.append(abs(turn) / (2 * half * BIN))
    return {'length_m': round(length, 2), 'bin_m': BIN, 'speed_mps': [round(v, 3) for v in speed],
            'curvature': [round(c, 6) for c in curvature], 'source': os.path.relpath(path, HERE),
            'source_start_m': start_m}


def _fill(values):
    known = [i for i, v in enumerate(values) if v is not None]
    for i, v in enumerate(values):
        if v is None:
            j = min(known, key=lambda k: abs(k - i))
            values[i] = values[j]


def load_profile(path=PROFILE_FILE):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def predict(profile, start_m, t_end, radius=CURVE_RADIUS):
    """[(t, in a curve)] every STEP from 0 to t_end, starting start_m along the loop. The times are
    corrected by the profile's fit to its own run (lag_s + time_scale * t, see fit())."""
    lag, scale = profile.get('lag_s', 0.0), profile.get('time_scale', 1.0)
    return [(round(lag + scale * t, 3), curved) for t, curved in _predict(profile, start_m, (t_end - lag) / scale, radius)]


def fit(real, guess):
    """(lag, scale) so that lag + scale * t of the predicted curve starts and ends matches the run's:
    least squares over the curves paired by order (the curves must pair up one to one)."""
    pairs = [(g, r) for (gs, ge), (rs, re) in zip(guess, real) for g, r in ((gs, rs), (ge, re))]
    n = float(len(pairs))
    mx = sum(g for g, _ in pairs) / n
    my = sum(r for _, r in pairs) / n
    sxx = sum((g - mx) ** 2 for g, _ in pairs)
    scale = sum((g - mx) * (r - my) for g, r in pairs) / sxx
    return my - scale * mx, scale


def _predict(profile, start_m, t_end, radius=CURVE_RADIUS):
    length, size = profile['length_m'], profile['bin_m']
    speed, curvature = profile['speed_mps'], profile['curvature']
    n = len(speed)
    out = []
    s, t = start_m % length, 0.0
    v = START_SPEED
    while t <= t_end + 1e-9:
        b = int(s / size) % n
        out.append((round(t, 3), curvature[b] > 1.0 / radius))
        # as LoopFollower: towards the speed of the profile, at most CURVE_DECEL slower or AUTO_ACCEL
        # faster per second (it starts at 95 km/h, also where the profile is slower)
        v += max(-CURVE_DECEL * STEP, min(speed[b] - v, AUTO_ACCEL * STEP))
        s = (s + v * STEP) % length
        t += STEP
    return out


def intervals(mask, join=1.0):
    """[(start, end)] of the curves in a predict() list; curves less than `join` s apart are one."""
    result, start = [], None
    for t, curved in mask:
        if curved and start is None:
            start = t
        elif not curved and start is not None:
            result.append([start, t])
            start = None
    if start is not None:
        result.append([start, mask[-1][0]])
    joined = []
    for a, b in result:
        if joined and a - joined[-1][1] < join:
            joined[-1][1] = b
        else:
            joined.append([a, b])
    return [(a, b) for a, b in joined if b - a >= 0.5]


class CurveTimes(object):
    """straight(a, b): True if the ego car is on a straight all the way from a to b."""

    def __init__(self, profile, start_m, t_end, radius=CURVE_RADIUS):
        self.start_m = start_m
        self.curves = intervals(predict(profile, start_m, t_end + 30.0, radius))

    def straight(self, a, b):
        return all(e <= a or s >= b for s, e in self.curves)

    def overlap(self, a, b):
        """s of a .. b in a curve."""
        return sum(max(0.0, min(b, e) - max(a, s)) for s, e in self.curves)


def log_intervals(path, radius=CURVE_RADIUS):
    """The curves of a recorded run, from its heading change over 40 m."""
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    pts = [(float(r['t_sim']), float(r['ego_x']), float(r['ego_y'])) for r in rows]
    mask = []
    j = k = 0
    for i, (t, x, y) in enumerate(pts):
        # the points 20 m before and after
        while j < i and math.hypot(x - pts[j][1], y - pts[j][2]) > 20.0:
            j += 1
        k = max(k, i)
        while k < len(pts) - 1 and math.hypot(pts[k][1] - x, pts[k][2] - y) < 20.0:
            k += 1
        if j == i or k == i:
            mask.append((t, False))
            continue
        a = math.atan2(y - pts[j][2], x - pts[j][1])
        b = math.atan2(pts[k][2] - y, pts[k][1] - x)
        turn = abs((b - a + math.pi) % (2 * math.pi) - math.pi)
        mask.append((t, turn / 40.0 > 1.0 / radius))
    return intervals(mask)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--log', help='frames.csv of a run from the loop start: make the profile from it')
    parser.add_argument('--start', type=float, help='print the curves for this start (m along the loop)')
    parser.add_argument('--log-start', type=float, default=0.0,
                        help='with --log: where along the loop that run started (its ego_start_m)')
    parser.add_argument('--t-end', type=float, default=630.0)
    args = parser.parse_args()
    if args.log:
        profile = make_profile(args.log, args.log_start)
        with open(PROFILE_FILE, 'w', encoding='utf-8') as handle:
            json.dump(profile, handle, separators=(',', ':'))
        print('Loop %.0f m, %.0f s a lap; profile -> %s' % (
            profile['length_m'], sum(profile['bin_m'] / v for v in profile['speed_mps']), PROFILE_FILE))
        real = log_intervals(args.log)
        guess = intervals(predict(profile, args.log_start, args.t_end))
        real = [c for c in real if c[1] <= args.t_end]
        if len(real) == len(guess):
            profile['lag_s'], profile['time_scale'] = fit(real, guess)
            with open(PROFILE_FILE, 'w', encoding='utf-8') as handle:
                json.dump(profile, handle, separators=(',', ':'))
            print('time fit: %+.2f s + %.4f x t' % (profile['lag_s'], profile['time_scale']))
            guess = intervals(predict(profile, args.log_start, args.t_end))
        else:
            print('the curves do not pair up (%d run, %d predicted): no time fit' % (len(real), len(guess)))
        print('curves in the run   :', [(round(a), round(b)) for a, b in real])
        print('curves predicted    :', [(round(a), round(b)) for a, b in guess])
        if len(real) == len(guess):
            print('start / end error   : max %.1f s' % max(max(abs(a - c), abs(b - d))
                                                         for (a, b), (c, d) in zip(real, guess)))
    if args.start is not None:
        profile = load_profile()
        print([(round(a), round(b)) for a, b in intervals(predict(profile, args.start, args.t_end))])


if __name__ == '__main__':
    main()
