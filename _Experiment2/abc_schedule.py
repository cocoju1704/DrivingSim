#!/usr/bin/env python

"""
Scenario ABC: the timeline of every car around the ego car, made before the experiment.

Every car other than the ego car (background traffic and the event cars of S, SD, R and F) follows a
fixed course of dx(t): metres ahead of the ego car along the road (< 0 behind), in a fixed lane, as a
function of the block's simulation time (SAGAT freezes excluded). The experiment only makes the cars
drive those courses (abc_traffic.py), so a set runs the same way every time, and the layout at each
SAGAT question is known in advance. It is still scored from the real positions at the freeze.

    python _Experiment2/abc_schedule.py            builds schedules/A.json, B.json, C.json, P.json
    python _Experiment2/abc_schedule.py --set A    only one set
    python _Experiment2/abc_schedule.py --check    prints the report of the saved schedules

How the background traffic is made (make_schedule):
  1. the event cars, from the templates (S, SD, R: one car each)
  2. for each SAGAT question Q, one car per target cell at the question time ("anchors"): lanes 1 and 3
     drive past at a constant speed (an approaching car behind: faster than the ego car, else slower),
     lane 2 ahead a slower car that comes back to the ego car and holds a gap, lane 2 behind a car
     that creeps up to -48 .. -42 m and holds
  3. for each F, a lead car holding +36 .. +45 m in lane 2 that brakes at F (brake light 3 s)
  4. random cars in lanes 1 and 3 (and now and then lane 2) until 4-6 cars are within 50 m; with
     background fast_lane (1 or 3, --fast-lane) the cars of that lane are mostly faster than the ego
     car (fast_lane_share), of the other lane mostly slower: a passing lane, as on a real highway
  4b. lane 0 (the road's lane 1, next to the median, two lanes left of the ego car): a few cars as
     scenery (lane0_n_within_80m), at the speeds of lane 1. Not in the SAGAT grid: not in the answers,
     not asked about
  5. the TOR at the end (its cars are not courses: abc_traffic.TorScene drives them): no background
     car from TOR-15 s on, every event car gone by then (one in lane 2 behind: by the TOR); the
     block ends 30 s after the TOR
Every car is checked against the rules of the Notion page (section 1), and a car that breaks one is
drawn again: same lane gaps of 15 m or more, the event lane clear during an event, nothing near the
grid boundaries at a question, the exact target layout (cells, approaching cars, safe lane) at each
question; no event after last_event_s (9:40) but the TOR. The seed of each set is in abc_config.json.

The TOR's time: its target (the set's "t") moved at most move_max_s (practice: practice_move_max_s)
so that straight_rel_s around it is on a straight, after_window_s or more after the last gaze window
ends, and tor_apart_s or more from the TORs of the other sets (A, B, C). Town04's longest straight is
31.6 s at 95 km/h: TOR-10 .. TOR+15 (the approaching car, the alert, the lane change past the stopped
car) fits it with the margins; TOR-15 .. TOR+30 would not.
"""

from __future__ import print_function

import argparse
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, 'abc_config.json')
SCHEDULE_DIR = os.path.join(HERE, 'schedules')
DT = 0.1                 # s between the samples of a course
KMH = 1.0 / 3.6
ZONES = ('front', 'side', 'rear')
CELLS = ['%d_%s' % (lane, zone) for lane in (1, 2, 3) for zone in ZONES if (lane, zone) != (2, 'side')]
GRID_LANES = (1, 2, 3)   # lane 0 (scenery, two lanes left) is outside the SAGAT grid
PROPOSALS = 50000        # random background cars tried per set
ANCHOR_TRIES = 400
QUESTION_TRIES = 250


def load_config(path=CONFIG_FILE):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def schedule_path(name):
    return os.path.join(SCHEDULE_DIR, '%s.json' % name)


def load_schedule(name):
    with open(schedule_path(name), encoding='utf-8') as handle:
        return json.load(handle)


# -- courses -----------------------------------------------------------------------------------


def _outside(x, exit_dx):
    if isinstance(exit_dx, (tuple, list)):
        return x < -exit_dx[0] or x > exit_dx[1]
    return abs(x) > exit_dx


FAR_AHEAD_M = 120.0        # m: farther ahead than this a car closes in or pulls away at FAR_DV at least,
FAR_DV = 25.0 / 3.6        # m/s (a 70 km/h car, or a 120 km/h one): cars appear and leave 300 m ahead
FAR_ACCEL = 0.5            # m/s^2 between that and its own speed (out of sight), not minutes on the way


def _far(x, target):
    """The target speed with the far rule: FAR_DV at least (its own direction) beyond FAR_AHEAD_M."""
    if x > FAR_AHEAD_M and target != 0.0:
        return math.copysign(max(abs(target), FAR_DV), target)
    return target


def simulate(t0, x0, v0, commands, t_end, exit_dx=None, min_t=None):
    """dx samples every DT from t0: the speed (m/s, relative) moves towards the target of the latest
    command [(time, target m/s, accel m/s^2 or None = at once)] at that acceleration (FAR_ACCEL when
    the far rule changes it, _far). Stops at t_end, or once |dx| > exit_dx after min_t (leaving the
    area); exit_dx (behind, ahead): out behind or ahead."""
    xs = []
    t, x, v = t0, x0, v0
    commands = sorted(commands, key=lambda c: c[0])
    k = 0
    target, accel = v0, None
    while t <= t_end + 1e-9:
        while k < len(commands) and commands[k][0] <= t + 1e-9:
            _, target, accel = commands[k]
            if accel is None:
                v = _far(x, target)
            k += 1
        xs.append(round(x, 3))
        if exit_dx is not None and _outside(x, exit_dx) and (min_t is None or t >= min_t):
            break
        goal = _far(x, target)
        step = (accel if accel is not None and goal == target else FAR_ACCEL) * DT
        v += max(-step, min(goal - v, step))
        x += v * DT
        t += DT
    return xs


def _steps_to(x0, v0, target, accel, x_goal):
    """Steps from x0 (moving back towards the ego car from ahead) until x <= x_goal, as simulate()."""
    x, v, n = x0, v0, 0
    while x > x_goal and n < 100000:
        goal = _far(x, target)
        step = (accel if goal == target else FAR_ACCEL) * DT
        v += max(-step, min(goal - v, step))
        x += v * DT
        n += 1
    return n


class Car(object):
    """A course: lane, first sample time t0, dx samples every DT, lights [(on, off, kind)]."""

    def __init__(self, cid, kind, lane, t0, xs, lights=None, **extra):
        self.id, self.kind, self.lane = cid, kind, lane
        self.i0 = int(round(t0 / DT))
        self.xs = xs
        self.lights = lights or []
        self.extra = extra

    @property
    def t0(self):
        return self.i0 * DT

    @property
    def i1(self):
        return self.i0 + len(self.xs) - 1

    def at(self, t):
        """dx at time t, None while the car does not exist."""
        i = int(round(t / DT)) - self.i0
        return self.xs[i] if 0 <= i < len(self.xs) else None

    def to_json(self):
        data = {'id': self.id, 'kind': self.kind, 'lane': self.lane, 't0': round(self.t0, 3),
                'dx': self.xs, 'lights': self.lights}
        data.update(self.extra)
        return data

    @staticmethod
    def from_json(data):
        extra = {k: v for k, v in data.items() if k not in ('id', 'kind', 'lane', 't0', 'dx', 'lights')}
        return Car(data['id'], data['kind'], data['lane'], data['t0'], data['dx'], data['lights'], **extra)


def side_event_car(event, template, spawn_dx, t_end):
    """S / SD: from behind at +approach km/h, holds hold_dx from T (blinker T .. T+hold_s), falls back."""
    v_app = template['approach_dv_kmh'] * KMH
    a = template['decel_mps2']
    hold = template['hold_dx_m']
    t_decel = v_app / a
    x_decel = hold - v_app * t_decel / 2.0
    t_start = event['t'] - t_decel - (x_decel - spawn_dx) / v_app
    t_start = math.floor(t_start / DT) * DT
    x_start = x_decel - v_app * (event['t'] - t_decel - t_start)
    release = event['t'] + template['hold_s']
    commands = [(t_start, v_app, None), (event['t'] - t_decel, 0.0, a),
                (release, template['retreat_dv_kmh'] * KMH, a)]
    xs = simulate(t_start, x_start, v_app, commands, t_end, exit_dx=abs(template['despawn_dx_m']), min_t=release)
    lights = []
    if event['type'] == 'S':  # towards lane 2: the lane 1 car signals right, the lane 3 car left
        lights.append([event['t'], release, 'right' if event['lane'] == 1 else 'left'])
    return Car(event['id'], 'event', event['lane'], t_start, xs, lights, event=event['type'])


def rear_event_car(event, template, spawn_dx, t_end):
    """R: from behind in lane 2, closer than 10 m bumper to bumper at T, holds, falls back at T+5."""
    v_app = template['approach_dv_kmh'] * KMH
    a = template['decel_mps2']
    hold = template['hold_dx_m']
    onset = template['onset_dx_m']
    # decelerating to the hold point: dx = hold - a/2 (t_hold - t)^2, onset_dx is passed at T
    before_hold = math.sqrt(2.0 * (hold - onset) / a)
    t_hold = event['t'] + before_hold
    t_decel = t_hold - v_app / a
    x_decel = hold - v_app * v_app / (2.0 * a)
    t_start = math.floor((t_decel - (x_decel - spawn_dx) / v_app) / DT) * DT
    x_start = x_decel - v_app * (t_decel - t_start)
    release = event['t'] + template['release_rel_s']
    commands = [(t_start, v_app, None), (t_decel, 0.0, a), (release, template['retreat_dv_kmh'] * KMH, a)]
    xs = simulate(t_start, x_start, v_app, commands, t_end, exit_dx=abs(template['despawn_dx_m']), min_t=release)
    return Car(event['id'], 'event', 2, t_start, xs, [], event='R')


def rear_window(car, event, template):
    """R response window: from the onset (T) to 2 s after it falls back past onset_dx."""
    onset = template['onset_dx_m']
    release = event['t'] + template['release_rel_s']
    t_exit = None
    for i, x in enumerate(car.xs):
        t = (car.i0 + i) * DT
        if t > release and x < onset:
            t_exit = t
            break
    if t_exit is None:
        t_exit = release + 1.0
    return [event['t'], round(t_exit + template['window_after_exit_s'], 2)], round(t_exit, 2)


def pass_car(cid, lane, dv, t_at, x_at, spawn_dx, t_end, kind='bg', follow=None, hold=None):
    """Lanes 1 and 3: a constant dv (m/s) car that is at x_at at t_at; it enters behind (faster than
    the ego car) or ahead (slower) and leaves at the other end; spawn_dx (behind, ahead), m. follow (time, dv, accel):
    from then on it slows down to the speed of the car ahead of it (an approaching car that has
    caught up with the cars in its lane): follow may be a list of such commands. hold (from, to, dv):
    at that relative speed from `from` to `to` (alongside the ego car for a question), ramping at
    HOLD_ACCEL, then back at dv."""
    follows = (follow if isinstance(follow, list) else [follow]) if follow else []
    if hold is not None:
        return _held_car(cid, lane, dv, t_at, x_at, spawn_dx, t_end, kind, follows, hold)
    commands = list(follows)
    if dv > 0:  # from behind, at dv all the way in
        entry = -spawn_dx[0]
        t_start = t_at - (x_at - entry) / dv
        t_start = math.ceil(t_start / DT) * DT
        x_start, v_start = x_at - dv * (t_at - t_start), dv
    else:  # from far ahead: FAR_DV, then dv from FAR_AHEAD_M on (_far)
        x_start, v_start = spawn_dx[1], _far(spawn_dx[1], dv)
        t_start = math.floor((t_at - _steps_to(x_start, v_start, dv, FAR_ACCEL, x_at) * DT) / DT) * DT
        commands.append((t_start, dv, FAR_ACCEL))
    xs = simulate(t_start, x_start, v_start, commands, t_end, exit_dx=spawn_dx,
                  min_t=follows[-1][0] if follows else None)
    return Car(cid, kind, lane, t_start, xs, [], dv_kmh=round(dv / KMH, 1))


HOLD_ACCEL = 1.0   # m/s^2 a car slows to (or leaves) the ego car's speed at for a question's hold


def _held_car(cid, lane, dv, t_at, x_at, spawn_dx, t_end, kind, follows, hold):
    """pass_car with a hold: its start time found so that it is at x_at at t_at."""
    t_from, t_to, dv_hold = hold
    ramp = abs(dv - dv_hold) / HOLD_ACCEL
    commands = [(t_from - ramp, dv_hold, HOLD_ACCEL), (t_to, dv, HOLD_ACCEL)] + list(follows)
    if dv > 0:
        x_start, v_start = -spawn_dx[0], dv
        t_start = t_at - (x_at - x_start) / dv
    else:
        x_start, v_start = spawn_dx[1], _far(spawn_dx[1], dv)
        t_start = t_at - _steps_to(x_start, v_start, dv, FAR_ACCEL, x_at) * DT
    for _ in range(8):
        t_start = round(t_start / DT) * DT
        if t_start > t_from - ramp:
            t_start = math.floor((t_from - ramp) / DT) * DT
        xs = simulate(t_start, x_start, v_start, [(t_start, dv, FAR_ACCEL if dv < 0 else None)] + commands,
                      t_at + DT, exit_dx=None)
        k = int(round((t_at - t_start) / DT))
        if k >= len(xs):
            break
        error = xs[k] - x_at
        if abs(error) < 0.3:
            break
        t_start += error / dv
    xs = simulate(t_start, x_start, v_start, [(t_start, dv, FAR_ACCEL if dv < 0 else None)] + commands,
                  t_end, exit_dx=spawn_dx, min_t=t_to)
    return Car(cid, kind, lane, t_start, xs, [], dv_kmh=round(dv / KMH, 1))


def lead_car(cid, hold_from, hold_to, x_hold, v_in, v_out, spawn_dx, t_end, brakes=(), kind='lead',
             brake_template=None):
    """Lane 2 ahead: comes back from spawn_dx[1] ahead at -v_in (a slower car), holds x_hold from hold_from,
    brakes at each time in `brakes` (brake light, -8 km/h for 3 s), pulls away at +v_out from hold_to."""
    a = 0.5
    d_decel = v_in * v_in / (2.0 * a)
    t_decel = hold_from - v_in / a
    # from far ahead (spawn_dx[1]): at FAR_DV until FAR_AHEAD_M (_far), then v_in
    x_start, v_first = spawn_dx[1], _far(spawn_dx[1], -v_in)
    t_start = math.floor((t_decel - _steps_to(x_start, v_first, -v_in, a, x_hold + d_decel) * DT) / DT) * DT
    commands = [(t_start, -v_in, a), (t_decel, 0.0, a), (hold_to, v_out, a)]
    lights = []
    if brake_template:
        for t_brake in brakes:
            seconds = brake_template['brake_s']
            commands += [(t_brake, brake_template['decel_dv_kmh'] * KMH, 2.0), (t_brake + seconds, 0.0, 2.0)]
            lights.append([t_brake, t_brake + seconds, 'brake'])
    xs = simulate(t_start, x_start, v_first, commands, t_end, exit_dx=spawn_dx, min_t=hold_to)
    return Car(cid, kind, 2, t_start, xs, lights)


def rear2_car(cid, hold_from, hold_to, x_hold, v_in, spawn_dx, t_end, kind='rear2'):
    """Lane 2 behind: comes up from spawn_dx[0] behind at +v_in (m/s), slowing down gently (0.4 m/s^2) to hold
    x_hold (-48 .. -42 m: never closer than -40 m, and slower than 3 km/h by the time it is in the
    grid's 50 m), falls back at -8 km/h from hold_to."""
    a = 0.4
    d_decel = v_in * v_in / (2.0 * a)
    t_decel = hold_from - v_in / a
    t_start = math.ceil((t_decel - (x_hold - d_decel + spawn_dx[0]) / v_in) / DT) * DT
    x_start = x_hold - d_decel - v_in * (t_decel - t_start)
    commands = [(t_start, v_in, None), (t_decel, 0.0, a), (hold_to, -8.0 * KMH, 0.5)]
    xs = simulate(t_start, x_start, v_in, commands, t_end, exit_dx=spawn_dx, min_t=hold_to)
    return Car(cid, kind, 2, t_start, xs, [])


# -- the layout at a question ------------------------------------------------------------------


def cell_of(lane, dx, cell_dx):
    """Grid cell '1_front' etc. of a car, None outside the grid (or the ego car's own cell)."""
    for zone in ZONES:
        low, high = cell_dx[zone]
        inside = (low < dx <= high) if zone == 'front' else (low <= dx <= high) if zone == 'side' else (low <= dx < high)
        if inside:
            return None if (lane, zone) == (2, 'side') else '%d_%s' % (lane, zone)
    return None


def layout(cars_now, history, qt):
    """The SAGAT answers for cars_now [(lane, dx)] and history {index: dx 5 s before} (same order):
    cells {cell: count}, approaching lanes, safe lane ('1', '3', 'both', 'none')."""
    cell_dx = qt['cell_dx_m']
    cells = {}
    approach = set()
    unsafe = set()
    low, high = qt['unsafe_dx_m']
    for k, (lane, dx) in enumerate(cars_now):
        if lane not in GRID_LANES:
            continue
        cell = cell_of(lane, dx, cell_dx)
        if cell:
            cells[cell] = cells.get(cell, 0) + 1
        before = history.get(k)
        rear_low, rear_high = cell_dx['rear']
        if before is not None and rear_low <= dx < rear_high:
            if (dx - before) / qt['approach_window_s'] / KMH > qt['approach_dv_kmh']:
                approach.add(lane)
        if lane in (1, 3) and low <= dx <= high:
            unsafe.add(lane)
    safe = {frozenset(): 'both', frozenset([1]): '3', frozenset([3]): '1'}.get(frozenset(unsafe), 'none')
    return cells, sorted(approach), safe


def planned_layout(cars, q, qt):
    t = q['t']
    now, history = [], {}
    for car in cars:
        x = car.at(t)
        if x is None:
            continue
        before = car.at(t - qt['approach_window_s'])
        if before is not None:
            history[len(now)] = before
        now.append((car.lane, x))
    return layout(now, history, qt)


def target_cells(q):
    counts = {}
    for cell in q['cells']:
        counts[cell] = counts.get(cell, 0) + 1
    return counts


def question_ok(cars, q, qt, partial=False):
    """The planned layout at q is its target, and no car is near a boundary there. partial: the
    question's cars are not all placed yet: no cell beyond the target, no other approaching lane."""
    cells, approach, safe = planned_layout(cars, q, qt)
    if partial:
        target = target_cells(q)
        if any(n > target.get(cell, 0) for cell, n in cells.items()) or not set(approach) <= set(q['approach']):
            return False
    elif cells != target_cells(q) or approach != sorted(q['approach']) or safe != q['safe']:
        return False
    margin = qt['margin_m']
    edges = [-50.0, -5.0, 5.0, 50.0] + list(qt['unsafe_dx_m'])
    window = qt['approach_window_s']
    for car in cars:
        x = car.at(q['t'])
        if x is None or abs(x) > 50.0 + margin or car.lane not in GRID_LANES:
            continue
        lane_edges = edges if car.lane != 2 else [-50.0, -5.0, 5.0, 50.0]
        if any(abs(x - e) < margin for e in lane_edges):
            return False
        before = car.at(q['t'] - window)
        if before is not None and -50.0 <= x < -5.0:
            dv = (x - before) / window / KMH
            if abs(dv - qt['approach_dv_kmh']) < 1.5:
                return False
    return all(_holds(car, q['t'], qt) for car in cars if car.lane in GRID_LANES)


def _holds(car, t, qt):
    """From hold_s before the question to it, the car neither enters nor leaves the grid (+-50 m)
    nor changes cell: the layout asked about has been there to be seen, not just appeared."""
    hold = qt.get('hold_s', 0.0)
    if not hold:
        return True
    cell_dx = qt['cell_dx_m']

    def where(time):
        x = car.at(time)
        if x is None or abs(x) > 50.0:
            return None
        return cell_of(car.lane, x, cell_dx) or 'own'
    now = where(t)
    k = 1
    while k * 0.5 <= hold + 1e-9:
        if where(t - k * 0.5) != now:
            return False
        k += 1
    return True


# -- rules -------------------------------------------------------------------------------------


class Rules(object):
    """The checks of a new car against the cars already placed (section 1 of the Notion page)."""

    def __init__(self, config, block, events, event_cars):
        bg = config['background']
        self.min_gap = bg['min_gap_m']
        self.lane2_rear = bg['lane2_rear_max_dx_m']
        self.lane2_front = bg['lane2_front_min_dx_m']
        self.qt = config['templates']['Q']
        self.questions = [e for e in events if e['type'] == 'Q']
        self.built = set()  # ids of the questions whose cars are all placed: checked in full
        self.events_end = block['last_event_s']   # no event after this (9:40) but the TOR
        tors = [e for e in events if e['type'] == 'TOR']
        # the TOR: no background car at all from its clearing on (its own cars only, then manual driving:
        # courses relative to the ego car would make no sense)
        self.tor_clear = (int(round((tors[0]['t'] + config['templates']['TOR']['clear_rel_s']) / DT))
                          if tors else None)
        self.clear = []  # (lane, i0, i1, low, high): no background car there
        for car, event in event_cars:  # as in the document: e.g. S lane 1, -75 .. +10 m, T-10 .. T+14
            template = config['templates']['S' if event['type'] in ('S', 'SD') else 'R']
            low, high = template['clear_dx_m']
            before, after = template['clear_rel_s']
            self.clear.append((car.lane, int(round((event['t'] + before) / DT)), int(round((event['t'] + after) / DT)),
                               low, high))

    def ok(self, new, cars):
        if self.tor_clear is not None and new.kind != 'event' and new.i1 >= self.tor_clear:
            return False
        for i, x in enumerate(new.xs):
            t = (new.i0 + i) * DT
            index = new.i0 + i
            if new.lane == 2 and new.kind != 'event':
                if (x < 0 and x > self.lane2_rear + 1e-6) or (x > 0 and x < self.lane2_front - 1e-6):
                    return False
            for lane, i0, i1, low, high in self.clear:
                if new.kind != 'event' and lane == new.lane and i0 <= index <= i1 and low <= x <= high:
                    return False
        for car in cars:
            if car.lane != new.lane:
                continue
            start, end = max(car.i0, new.i0), min(car.i1, new.i1)
            for index in range(start, end + 1):
                if abs(car.xs[index - car.i0] - new.xs[index - new.i0]) < self.min_gap:
                    return False
        if new.lane not in GRID_LANES:
            return True   # scenery: the questions do not see it
        everything = cars + [new]
        return all(question_ok(everything, q, self.qt, partial=q['id'] not in self.built) for q in self.questions
                   if new.at(q['t']) is not None or new.at(q['t'] - self.qt['approach_window_s']) is not None)


# -- event times on the straights --------------------------------------------------------------

# s around an event's T in which the ego car should be on a straight (the turn signal, the car
# close behind and the response windows; the brake light; the freeze), plus CURVE_MARGIN on each
# side for the error of the prediction (abc_ego.py: 1-2 s). Town04's loop does not have straights
# for all of them (two places for a car event per 137 s lap, ten car events 30 s apart): the
# seconds in a curve are kept as few as can be (CURVE_WEIGHT), then the moving.
CRITICAL = {'S': (-2.0, 7.0), 'SD': (-2.0, 7.0), 'R': (-2.0, 7.0), 'F': (-1.0, 4.0), 'Q': (-2.0, 1.0),
            'TOR': (-10.0, 15.0)}   # TOR: config TOR straight_rel_s, all of it on a straight (not just few s)
CURVE_MARGIN = 1.0
CURVE_WEIGHT = 20.0           # cost of a second in a curve, in seconds moved
MOVE_MAX = 25                 # s an event may move from its time in the document
START_STEP = 10.0             # m between the start points tried along the loop
START_BELOW_KMH = 5.0         # only start points where the profile is at most this much below the cruise speed: a start in a curve's slow part
                              # leaves the autonomous driving out of step with the profile for a minute (its
                              # controller starts from rest there), 6.5 s behind the predicted curves after
PLAN_TRIES = 20               # start points tried, best first, until the questions' cars can be placed
CAR_LEAD = {'S': 14.1, 'SD': 14.1, 'R': 15.9}   # s from a car's appearance to its T
CAR_TAIL = {'S': 15.4, 'SD': 15.4, 'R': 15.3}   # s from its T to its removal
WINDOW_END = {'S': 7.0, 'SD': 7.0, 'R': 8.5}
# s from an event to the TOR at least: S, SD its car gone (CAR_TAIL) before the TOR's clearing (15 s
# before it); R its window over 15 s before (its car is in lane 2 behind, gone by the TOR); a question's
# cars gone before the clearing; F its lead car gone (lane 2 ahead) before the clearing
TOR_AFTER = {'S': 31.0, 'SD': 31.0, 'R': 24.0, 'Q': 45.0, 'F': 45.0}


def in_curve(curves, kind, t):
    """s of an event's critical part (with the margins) in a curve."""
    low, high = CRITICAL[kind]
    return curves.overlap(t + low - CURVE_MARGIN, t + high + CURVE_MARGIN)


def tor_candidates(e, tor, practice, curves, avoid=()):
    """[(time, cost)] of a TOR: straight (hard), tor_apart_s from the times in `avoid`, moved
    as little as can be."""
    move = int(tor['practice_move_max_s'] if practice else tor['move_max_s'])
    low, high = tor['straight_rel_s']
    out = []
    for d in range(-move, move + 1):
        t = e['t'] + d
        if curves is not None and curves.overlap(t + low - CURVE_MARGIN, t + high + CURVE_MARGIN) > 0.0:
            continue
        if any(abs(t - other) < tor['tor_apart_s'] for other in avoid):
            continue
        out.append((t, abs(d)))
    return out


def plan_times(events, block, curves, tor=None, avoid=()):
    """Moves the events (in their order, at most MOVE_MAX s) so that their critical parts are in
    the curves as little as can be, then moved as little as can be. The document's rules stay:
    30 s or more between the events (S, SD, R, Q; 32 s before an R that follows a car: one event car
    at a time), no car event before the adaptation phase is over, none after last_event_s; an F 15 s from the events around it (after a car's window, before the next car
    appears). The TOR (last, tor: its template) all on a straight (tor_candidates), TOR_AFTER from
    the event before it. Dynamic programming over the events but F, the Fs placed in each step's gap.
    Returns (cost, {id: time}) or None."""
    last = block['last_event_s']
    adapt = block['adaptation_end_s']
    main = [e for e in events if e['type'] != 'F']
    # the Fs that lie between main[i-1] and main[i] in the document (index 0: before the first)
    between = [[] for _ in range(len(main) + 1)]
    for e in events:
        if e['type'] == 'F':
            between[sum(1 for m in main if m['t'] < e['t'])].append(e)
    f_costs = {}
    for group in between:
        for e in group:
            f_costs[e['id']] = [(e['t'] + d * 0.5, CURVE_WEIGHT * in_curve(curves, 'F', e['t'] + d * 0.5) + abs(d * 0.5))
                                for d in range(-2 * MOVE_MAX, 2 * MOVE_MAX + 1)
                                if adapt <= e['t'] + d * 0.5 <= last]

    def after(prev, t_prev):   # earliest F after main event `prev` at t_prev
        if prev is None:
            return adapt
        return t_prev + (15.0 if prev['type'] == 'Q' else WINDOW_END[prev['type']] + 15.0)

    def before(cur, t_cur):    # latest F before it
        if cur is None:
            return last
        if cur['type'] == 'TOR':
            return min(last, t_cur - TOR_AFTER['F'])
        return t_cur - (15.0 if cur['type'] == 'Q' else CAR_LEAD[cur['type']] + 15.0)

    def place_fs(i, prev, t_prev, cur, t_cur):
        """(cost, {id: time}) of the Fs between main[i-1] and main[i] (15 s apart if two), or None."""
        group = between[i]
        if not group:
            return 0.0, {}
        low, high = after(prev, t_prev), before(cur, t_cur)
        total, placed, last = 0.0, {}, None
        for e in group:
            options = [(c, t) for t, c in f_costs[e['id']] if low <= t <= high and (last is None or t >= last + 15.0)]
            if not options:
                return None
            c, t = min(options)
            total += c
            placed[e['id']] = t
            last = t
        return total, placed

    def candidates(e):
        if e['type'] == 'TOR':
            return tor_candidates(e, tor, block.get('practice'), curves, avoid)
        out = []
        for d in range(-MOVE_MAX, MOVE_MAX + 1):
            t = e['t'] + d
            if e['type'] == 'Q':
                ok = adapt + 5.0 <= t <= last
            else:
                ok = adapt + 12.0 <= t <= last
            if ok:
                out.append((t, CURVE_WEIGHT * in_curve(curves, e['type'], t) + abs(d)))
        return out

    def gap_ok(prev, t_prev, cur, t_cur):
        gap = t_cur - t_prev
        if cur['type'] == 'TOR':
            return gap >= TOR_AFTER[prev['type']]
        need = 32.0 if cur['type'] == 'R' and prev['type'] in CAR_LEAD else 30.0
        return need <= gap <= 75.0

    best = [{} for _ in main]   # index -> {time: (cost, previous time, Fs placed before it)}
    for i, e in enumerate(main):
        for t, cost in candidates(e):
            if i == 0:
                fs = place_fs(0, None, None, e, t)
                if fs is not None:
                    best[i][t] = (cost + fs[0], None, fs[1])
                continue
            choice = None
            for tp, (c, _, _) in best[i - 1].items():
                if not gap_ok(main[i - 1], tp, e, t):
                    continue
                fs = place_fs(i, main[i - 1], tp, e, t)
                if fs is not None and (choice is None or c + cost + fs[0] < choice[0]):
                    choice = (c + cost + fs[0], tp, fs[1])
            if choice is not None:
                best[i][t] = choice
        if not best[i]:
            return None
    # the Fs after the last event
    ends = []
    for t, (c, _, _) in best[-1].items():
        fs = place_fs(len(main), main[-1], t, None, None)
        if fs is not None:
            ends.append((c + fs[0], t, fs[1]))
    if not ends:
        return None
    total, t, tail = min(ends, key=lambda x: x[0])
    times = dict(tail)
    for i in range(len(main) - 1, -1, -1):
        _, previous, fs = best[i][t]
        times[main[i]['id']] = t
        times.update(fs)
        t = previous
    return total, times


def rank_starts(events, block, profile, name, tor=None, avoid=(), cruise_kmh=0.0):
    """The start points along the loop with their event times, best first: the events in the
    curves as little as can be (plan_times). [(cost, start m, {id: time}, CurveTimes)]"""
    import abc_ego  # next to this script
    plans = []
    start = 0.0
    speeds, size = profile['speed_mps'], profile['bin_m']
    while start < profile['length_m']:
        if speeds[int(start / size) % len(speeds)] * 3.6 < cruise_kmh - START_BELOW_KMH:
            start += START_STEP
            continue
        curves = abc_ego.CurveTimes(profile, start, block['block_end_s'])
        plan = plan_times(events, block, curves, tor, avoid)
        if plan is not None:
            plans.append((plan[0], start, plan[1], curves))
        start += START_STEP
    if not plans:
        raise RuntimeError('%s: the events do not fit the rules from any start point' % name)
    plans.sort(key=lambda p: (p[0], p[1]))
    return plans


def choose_start(events, block, profile, name, tor=None, avoid=(), cruise_kmh=0.0):
    return rank_starts(events, block, profile, name, tor, avoid, cruise_kmh)[0]


# -- making a schedule -------------------------------------------------------------------------


def make_schedule(config, name, plan=None):
    """plan: (cost, start m, {event id: time}, CurveTimes) of rank_starts (None: start at the loop
    start, events at the document's times)."""
    block = config['blocks'][name]
    events = sorted([dict(e) for e in config['sets'][name]], key=lambda e: e['t'])
    rng = random.Random(block['seed'])
    templates = config['templates']
    bg = config['background']
    # (behind, ahead): ahead far beyond 80 m, where a car would pop up in plain view (55 px wide at
    # 80 m on a 1920 px, 43 degree monitor; 15 px at 300 m)
    spawn = (bg['spawn_dx_m'], bg.get('spawn_ahead_dx_m', bg['spawn_dx_m']))
    t_end = block['block_end_s']
    t_first = -200.0  # cars on the road at the start were placed before it
    tor_template = templates.get('TOR')
    # 0. where on the loop the block starts, and the event times on the straights
    curves = None
    start_m = 0.0
    if plan is not None:
        _, start_m, times, curves = plan
        for e in events:
            e['doc_t'] = e['t']
            e['t'] = times[e['id']]
        events.sort(key=lambda e: e['t'])
    tor = next((e for e in events if e['type'] == 'TOR'), None)
    if tor is not None:
        t_end = tor['t'] + tor_template['end_rel_s']  # the block ends 30 s after the TOR
        tor_clear = tor['t'] + tor_template['clear_rel_s']
    # 1. event cars
    event_cars = []
    windows = {}
    for event in events:
        if event['type'] in ('S', 'SD'):
            car = side_event_car(event, templates['S'], templates['S']['spawn_dx_m'], t_end)
            windows[event['id']] = [event['t'] + w for w in templates['S']['window_rel_s']]
            event_cars.append((car, event))
        elif event['type'] == 'R':
            car = rear_event_car(event, templates['R'], templates['R']['spawn_dx_m'], t_end)
            windows[event['id']], exit_t = rear_window(car, event, templates['R'])
            car.extra['t_exit'] = exit_t
            event_cars.append((car, event))
    for car, event in event_cars:
        if car.t0 < block['adaptation_end_s'] - 1e-6:
            # none in the adaptation phase: it appears at its place at the end of it, still 65 m+ behind
            cut = int(round(block['adaptation_end_s'] / DT)) - car.i0
            car.xs, car.i0 = car.xs[cut:], car.i0 + cut
            if abs(car.xs[0]) < 65.0:
                raise RuntimeError('%s: its car would appear %.0f m behind, in view' % (event['id'], -car.xs[0]))
    cars = [car for car, _ in event_cars]
    for car, event in event_cars:
        # the TOR: the event cars are gone (S, SD: before its clearing; R, lane 2 behind: by the TOR)
        if tor is not None and car.i1 * DT >= (tor['t'] if car.lane == 2 else tor_clear) - 1e-6:
            raise RuntimeError('%s: its car is still there at %.1f s, the TOR at %.0f s' % (event['id'], car.i1 * DT,
                                                                                            tor['t']))
    for k, (car, _) in enumerate(event_cars):
        same = [c for c, _ in event_cars[:k]]
        for other in same:
            if other.i1 >= car.i0:
                raise RuntimeError('%s starts before %s is gone' % (car.id, other.id))
    rules = Rules(config, block, events, event_cars)
    count = [0]

    def new_id(prefix):
        count[0] += 1
        return '%s-%s%02d' % (name, prefix, count[0])

    qt = templates['Q']
    targets = qt['target_dx_m']
    v_low, v_high = bg['dv_kmh']
    v_anchor = bg.get('anchor_dv_kmh_max', v_high)
    fast_lane = bg.get('fast_lane')

    def faster_share(lane):
        """Share of the cars in `lane` (0, 1, 3) faster than the ego car."""
        if not fast_lane:
            return bg.get('faster_share', 0.5)
        share = bg.get('fast_lane_share', 0.85)
        return share if (1 if lane == 0 else lane) == fast_lane else 1.0 - share

    def faster_sign(lane):
        """+1 (faster) or -1: the side that brings the lane's background cars so far closer to
        faster_share. A random sign per proposal does not: the rules turn down more of one side
        (in set A lane 1 ended 53 % faster with 85 % asked). Not in the practice drive: steered it
        gets few cars (5-7 within 50 m 6 % of the time instead of 55 %), random its share is close."""
        if block.get('practice'):
            return 1 if rng.random() < faster_share(lane) else -1
        mine = [c for c in cars if c.kind == 'bg' and c.lane == lane and 'dv_kmh' in c.extra]
        n_fast = sum(c.extra['dv_kmh'] > 0 for c in mine)
        if not mine:
            return 1 if rng.random() < faster_share(lane) else -1
        return 1 if n_fast / float(len(mine)) < faster_share(lane) else -1

    # 2. anchors of each question, 3. lead cars of each F (in time order: each sees the cars before it)
    spawns = {event['id']: car.t0 for car, event in event_cars}

    def q_time_ok(event, t):
        """A question time: 30 s from the other events, 20 s after a target's window, 15 s from F,
        TOR_AFTER before the TOR."""
        if t < block['adaptation_end_s'] or t > rules.events_end:
            return False
        if tor is not None and t > tor['t'] - TOR_AFTER['Q']:
            return False
        for other in events:
            if other is event:
                continue
            if other['type'] in ('F', 'TOR'):
                continue  # F moves itself (up to shift_s) to keep 15 s from the questions; TOR above
            if abs(t - other['t']) < 30.0:
                return False
            if other['type'] in ('S', 'R') and other['t'] < t and t < windows[other['id']][1] + 20.0:
                return False
        # a nearby F must still find a time 15 s from this one
        saved, event['t'] = event['t'], t
        try:
            for other in events:
                if other['type'] == 'F' and abs(other.get('t_doc', other['t']) - t) < 30.0:
                    base = other.get('t_doc', other['t'])
                    steps = [d * 0.5 for d in range(-int(2 * templates['F']['shift_s']), int(2 * templates['F']['shift_s']) + 1)]
                    if not any(f_time_ok(other, base + d) for d in steps):
                        return False
        finally:
            event['t'] = saved
        return True

    def f_time_ok(event, t):
        """An F time: 15 s from the questions, after a window ends and before the next car appears,
        TOR_AFTER before the TOR."""
        if tor is not None and t > tor['t'] - TOR_AFTER['F']:
            return False
        for other in events:
            if other is event or other['type'] == 'F':
                continue
            if other['type'] == 'Q' and abs(t - other['t']) < 15.0:
                return False
            if other['id'] in windows and windows[other['id']][0] - 15.0 < t < windows[other['id']][1] + 15.0:
                return False
            if other['id'] in spawns and spawns[other['id']] - 15.0 < t < other['t']:
                return False
        return block['adaptation_end_s'] <= t <= rules.events_end

    # the questions first: an F near one is braked by the question's lead car
    for event in sorted(events, key=lambda e: (e['type'] != 'Q', e['t'])):
        if event['type'] == 'Q':
            event['t_doc'] = event['t']
            shifts = [0] + [d * sign for d in range(1, 16) for sign in (1, -1)]
            done = False
            for shift in shifts:
                if not q_time_ok(event, event['t_doc'] + shift):
                    continue
                event['t'] = event['t_doc'] + shift
                for attempt in range(QUESTION_TRIES):
                    mark = count[0]
                    placed = []
                    nearby_f = [f for f in events if f['type'] == 'F' and abs(f['t'] - event['t']) <= 45.0
                                and not any(c.extra.get('f_event') == f['id'] for c in cars)
                                and f_time_ok(f, f['t'])]
                    for car in anchor_cars(new_id, event, rng, targets, v_low, v_anchor, spawn, t_end,
                                           nearby_f[:1], templates['F'], qt.get('hold_s', 0.0),
                                           share=None if block.get('practice') else faster_share):
                        if car.t0 < t_first or not rules.ok(car, cars + placed):
                            break
                        placed.append(car)
                    if len(placed) == len(event['cells']) and question_ok(cars + placed, event, qt):
                        cars = cars + placed
                        rules.built.add(event['id'])
                        done = True
                        break
                    count[0] = mark
                if done:
                    break
            if not done:
                allowed = [event['t_doc'] + d for d in shifts if q_time_ok(event, event['t_doc'] + d)]
                raise RuntimeError('%s: its target layout could not be placed (times tried: %s)' % (event['id'], allowed))
        elif event['type'] == 'F':
            ft = templates['F']
            event.setdefault('t_doc', event['t'])
            if any(car.extra.get('f_event') == event['id'] for car in cars):
                continue  # the lead car of a question nearby brakes for it
            shifts = [0.0] + [d * 0.5 * sign for d in range(1, int(2 * ft['shift_s']) + 1) for sign in (1, -1)]
            done = False
            for shift in shifts:
                t_brake = event['t_doc'] + shift
                if not f_time_ok(event, t_brake):
                    continue
                for _ in range(ANCHOR_TRIES):
                    x_hold = rng.uniform(*ft['lead_dx_m'])
                    car = lead_car(new_id('F'), t_brake - rng.uniform(8, 25), t_brake + rng.uniform(8, 25), x_hold,
                                   rng.uniform(5, 12) * KMH, rng.uniform(5, 12) * KMH, spawn, t_end,
                                   brakes=[t_brake], brake_template=ft)
                    if car.t0 < t_first or min(car.xs) < ft['min_gap_m'] + 4.8 or not rules.ok(car, cars):
                        count[0] -= 1
                        continue
                    car.extra['f_event'] = event['id']
                    event['t'] = t_brake
                    cars.append(car)
                    done = True
                    break
                if done:
                    break
            if not done:
                allowed = [event['t_doc'] + d for d in shifts if f_time_ok(event, event['t_doc'] + d)]
                raise RuntimeError('%s: no lead car found (allowed times: %s; questions at %s)' % (
                    event['id'], allowed, [e['t'] for e in events if e['type'] == 'Q']))

    # 4. background cars until 4-6 are within 50 m
    low, high = bg['n_within_50m']
    n_steps = int(round(t_end / DT)) + 1

    def density(cars_):
        counts = [0] * n_steps
        for car in cars_:
            for i, x in enumerate(car.xs):
                index = car.i0 + i
                if 0 <= index < n_steps and abs(x) <= 50.0:
                    counts[index] += 1
        return counts

    counts = density(cars)
    # density all the way to the block end (with a TOR: to its clearing, the road is empty after it)
    fill_end = n_steps if tor is None else int(round(tor_clear / DT))
    for _ in range(PROPOSALS):
        deficit = [i for i in range(n_steps) if counts[i] < low and i < fill_end]
        if not deficit:
            break
        i = rng.choice(deficit)
        t_at = i * DT
        lane = rng.choice((1, 3, 1, 3, 2, 2))  # lane 2 more often: it is free while lanes 1 or 3 are cleared for an event
        if lane == 2:
            if rng.random() < 0.5:
                car = lead_car(new_id('B'), t_at - rng.uniform(5, 30), t_at + rng.uniform(5, 40),
                               rng.uniform(30, 48), rng.uniform(5, 12) * KMH, rng.uniform(5, 12) * KMH,
                               spawn, t_end, kind='bg')
            else:
                car = rear2_car(new_id('B'), t_at - rng.uniform(5, 30), t_at + rng.uniform(5, 40),
                                rng.uniform(-49, -41), rng.uniform(6, 15) * KMH, spawn, t_end, kind='bg')
        else:
            # the side towards faster_share (faster_sign); the random numbers in the order the saved
            # schedules were made with (P: before faster_sign)
            speed = rng.uniform(v_low, v_high) * KMH
            if block.get('practice'):
                sign = faster_sign(lane)
                x_at = rng.uniform(-48, 48)
            else:
                x_at = rng.uniform(-48, 48)
                sign = faster_sign(lane)
            car = pass_car(new_id('B'), lane, speed * sign, t_at, x_at, spawn, t_end)
        if car.t0 < t_first:
            count[0] -= 1
            continue
        extra = density([car])
        if any(counts[k] + extra[k] > high for k in range(n_steps) if extra[k]):
            count[0] -= 1
            continue
        if not rules.ok(car, cars):
            count[0] -= 1
            continue
        cars.append(car)
        counts = [a + b for a, b in zip(counts, extra)]

    # 4b. lane 0: scenery, lane0_n_within_80m cars within 80 m (none from the TOR's clearing on)
    zero = bg.get('lane0_n_within_80m')
    if zero:
        low0, high0 = zero
        counts0 = [0] * n_steps

        def density0(car):
            out = {}
            for i, x in enumerate(car.xs):
                index = car.i0 + i
                if 0 <= index < n_steps and abs(x) <= 80.0:
                    out[index] = 1
            return out
        start0 = int(round(block['adaptation_end_s'] / DT)) if bg.get('lane0_after_adaptation') else 0
        for _ in range(PROPOSALS // 5):
            deficit = [i for i in range(start0, fill_end) if counts0[i] < low0]
            if not deficit:
                break
            t_at = rng.choice(deficit) * DT
            # lane 0 at random by faster_share: steered (faster_sign), its slow proposals are mostly turned
            # down and fewer cars fit (set A: 70 % of the time 1-2 cars instead of 95 %)
            speed = rng.uniform(v_low, v_high) * KMH
            if block.get('practice'):
                sign = 1 if rng.random() < faster_share(0) else -1
                x_at = rng.uniform(-75, 75)
            else:
                x_at = rng.uniform(-75, 75)
                sign = 1 if rng.random() < faster_share(0) else -1
            car = pass_car(new_id('Z'), 0, speed * sign, t_at, x_at, spawn, t_end)
            extra = density0(car)
            if car.t0 < t_first or any(counts0[k] + 1 > high0 for k in extra) or not rules.ok(car, cars):
                count[0] -= 1
                continue
            cars.append(car)
            for k in extra:
                counts0[k] += 1
        analysed0 = counts0[int(block['adaptation_end_s'] / DT):fill_end]

    # the answers, from the courses
    report = {}
    questions = []
    for event in events:
        if event['type'] != 'Q':
            continue
        cells, approach, safe = planned_layout(cars, event, qt)
        questions.append({'id': event['id'], 't': event['t'], 'cells': cells, 'approach': approach, 'safe': safe,
                          'matches_target': question_ok(cars, event, qt)})
    analysed = counts[int(block["adaptation_end_s"] / DT):fill_end]
    report['density_within_50m'] = {
        'mean': round(sum(analysed) / float(len(analysed)), 2),
        'target': [low, high],
        'share_in_target': round(sum(1 for c in analysed if low <= c <= high) / float(len(analysed)), 3),
        'share_below_target': round(sum(1 for c in analysed if c < low) / float(len(analysed)), 3),
        'share_below_4': round(sum(1 for c in analysed if c < 4) / float(len(analysed)), 3),
        'max': max(analysed)}
    report['questions'] = questions
    report['background_cars'] = sum(1 for c in cars if c.kind != 'event')
    lanes = {}
    for car in cars:
        if car.kind == 'bg' and 'dv_kmh' in car.extra:
            item = lanes.setdefault(str(car.lane), {'cars': 0, 'faster': 0})
            item['cars'] += 1
            item['faster'] += car.extra['dv_kmh'] > 0
    report['lanes'] = {'fast_lane': fast_lane, 'pass_cars': lanes}
    if zero:
        report['lane0_within_80m'] = {'target': [low0, high0], 'mean': round(sum(analysed0) / float(len(analysed0)), 2),
                                      'share_in_target': round(sum(1 for c in analysed0 if low0 <= c <= high0)
                                                               / float(len(analysed0)), 3)}
    out_events = []
    for event in events:
        item = dict(event)
        if event['id'] in windows:
            item['window'] = [round(w, 2) for w in windows[event['id']]]
        for car in cars:
            if car.id == event['id'] and 't_exit' in car.extra:
                item['t_exit'] = car.extra['t_exit']
        if event['type'] == 'F':
            item['t'] = event.get('t_planned', event['t'])
            item['t_doc'] = event['t']
            item.pop('t_planned', None)
        out_events.append(item)
    # colors of the event cars: the same spread over S, SD and R
    colors = config['event_colors']
    by_type = {}
    for car in cars:
        if car.kind == 'event':
            k = by_type.get(car.extra['event'], 0)
            by_type[car.extra['event']] = k + 1
            car.extra['color'] = colors[k % len(colors)]
    if tor is not None:
        last_window = max([w[1] for w in windows.values()] + [e['t'] + 5.0 for e in events if e['type'] == 'F'] +
                          [e['t'] for e in events if e['type'] == 'Q'])
        low_s, high_s = tor_template['straight_rel_s']
        report['tor'] = {'t': tor['t'], 'target': tor.get('doc_t', tor['t']),
                         'after_last_window_s': round(tor['t'] - last_window, 1),
                         'straight': None if curves is None else curves.straight(tor['t'] + low_s, tor['t'] + high_s),
                         'straight_rel_s': [low_s, high_s], 'safe_lane': tor['safe_lane'],
                         'unsafe_lane': tor['unsafe_lane']}
    report['ego_start_m'] = start_m
    report['moved'] = {e['id']: round(e['t'] - e['doc_t'], 1) for e in events
                       if 'doc_t' in e and abs(e['t'] - e['doc_t']) > 1e-6}
    if curves is not None:
        report['curves'] = [(round(a, 1), round(b, 1)) for a, b in curves.curves if a < t_end]
    return {'set': name, 'dt': DT, 'ego_start_m': start_m,
            'adaptation_end_s': block['adaptation_end_s'], 'block_end_s': t_end,
            'last_event_s': block['last_event_s'], 'practice': bool(block.get('practice')), 'seed': block['seed'],
            'events': out_events, 'cars': [car.to_json() for car in sorted(cars, key=lambda c: c.t0)],
            'report': report}


def anchor_cars(new_id, q, rng, targets, v_low, v_high, spawn, t_end, f_events=(), f_template=None, hold_s=0.0,
                share=None):
    """The cars of question q's target cells. The cars of one cell lane (1 or 3) drive at the same
    speed, a group: at different speeds one would overtake the other in the same lane. A lane with
    an approaching car behind is faster than the ego car, a lane with a car behind that is not
    approaching is slower, else either: faster with the lane's share(lane) (the passing lane mostly
    faster), 1:1 without it."""

    def side(lane):
        if share is None:
            return rng.choice((-1, 1))
        return 1 if rng.random() < share(lane) else -1
    t = q['t']
    cars = []
    by_lane = {}
    for cell in q['cells']:
        by_lane.setdefault(int(cell[0]), []).append(cell[2:])
    for lane in sorted(by_lane, key=lambda l: l != 2):
        zones = by_lane[lane]
        if lane == 2:
            for zone in zones:
                if zone == 'front' and f_events:
                    # an F close by: this car stays, 31 .. 40 m ahead, and brakes at the F
                    f = f_events[0]
                    car = lead_car(new_id('Q'), min(t, f['t']) - rng.uniform(6, 20), max(t, f['t']) + rng.uniform(8, 20),
                                   rng.uniform(31, targets['front'][1]), rng.uniform(5, 12) * KMH,
                                   rng.uniform(5, 12) * KMH, spawn, t_end, brakes=[f['t']], brake_template=f_template)
                    car.extra['f_event'] = f['id']
                    cars.append(car)
                elif zone == 'front':
                    cars.append(lead_car(new_id('Q'), t - rng.uniform(6, 30), t + rng.uniform(4, 30),
                                         rng.uniform(*targets['front']), rng.uniform(5, 12) * KMH,
                                         rng.uniform(5, 12) * KMH, spawn, t_end, kind='bg'))
                else:
                    cars.append(rear2_car(new_id('Q'), t - rng.uniform(7, 30), t + rng.uniform(3, 30),
                                          rng.uniform(*targets['rear_lane2']), rng.uniform(6, 15) * KMH,
                                          spawn, t_end, kind='bg'))
            continue
        follow = None
        if lane in q['approach'] and len(zones) > 1:
            # the cars ahead in the lane at any speed; the approaching one catches up with them by
            # the question and then slows down to their speed
            dv = rng.uniform(v_low, (v_low + v_high) / 2.0) * KMH * side(lane)
            fast = rng.uniform(max(v_low, 6.0, dv / KMH + 6.0), max(v_high, dv / KMH + 8.0)) * KMH
            follow = (t + 0.5, dv, 2.0)
        # hold_s: the lane's cars that do not approach stay alongside (about the ego car's speed) from
        # before the hold to just after the question (_holds), then drive on at dv
        hold = None
        if hold_s:
            dv_hold = rng.uniform(-1.2, 1.2) * KMH
            hold = (t - hold_s - 0.5, t + 2.0, dv_hold)
        if follow and hold:  # the approaching car follows them at their hold, then on at dv
            follow = [(t + 0.5, hold[2], 2.0), (hold[1], dv, HOLD_ACCEL)]
        elif lane in q['approach']:
            dv = rng.uniform(max(v_low, 6.0), v_high) * KMH
        elif 'rear' in zones:
            dv = -rng.uniform(max(v_low, 6.0), v_high) * KMH
        else:
            dv = rng.uniform(v_low, v_high) * KMH * side(lane)
        for zone in zones:
            key = 'rear_lane1_3' if zone == 'rear' else zone
            if follow and zone == 'rear':  # well behind the others: room to slow down
                low, high = targets[key]
                cars.append(pass_car(new_id('Q'), lane, fast, t, rng.uniform(low, (low + high) / 2.0), spawn, t_end,
                                     follow=follow))
            elif lane in q['approach'] and zone == 'rear':  # the approaching car: on at its speed
                cars.append(pass_car(new_id('Q'), lane, dv, t, rng.uniform(*targets[key]), spawn, t_end))
            else:
                cars.append(pass_car(new_id('Q'), lane, dv, t, rng.uniform(*targets[key]), spawn, t_end,
                                     hold=hold))
    return cars


# -- report ------------------------------------------------------------------------------------


def print_report(schedule):
    report = schedule['report']
    print('Set %s: %d background cars, %d events, block %.0f s, start %.0f m along the loop' % (
        schedule['set'], report['background_cars'], len(schedule['events']), schedule['block_end_s'],
        schedule.get('ego_start_m', 0.0)))
    if report.get('moved'):
        print('  moved onto straights: ' + ', '.join('%s %+.0f s' % item for item in sorted(report['moved'].items())))
    d = report['density_within_50m']
    low, high = d.get('target', (4, 6))
    print('  cars within 50 m (adaptation end .. block end): mean %.2f, %d-%d %.0f %% of the time, '
          'fewer than %d %.0f %%, fewer than 4 %.0f %%, max %d' % (
              d['mean'], low, high, 100 * d.get('share_in_target', d.get('share_4_to_6', 0)), low,
              100 * d.get('share_below_target', d['share_below_4']), 100 * d['share_below_4'], d['max']))
    lanes = report.get('lanes')
    if lanes:
        print('  passing cars (lanes 0, 1, 3), faster than the ego car: ' + ', '.join(
            'lane %s %d of %d' % (lane, v['faster'], v['cars']) for lane, v in sorted(lanes['pass_cars'].items())) +
              ('; passing lane %s' % lanes['fast_lane'] if lanes['fast_lane'] else ''))
    if report.get('lane0_within_80m'):
        z = report['lane0_within_80m']
        print('  lane 0 (scenery) cars within 80 m: mean %.2f, %d-%d %.0f %% of the time' % (
            z['mean'], z['target'][0], z['target'][1], 100 * z['share_in_target']))
    for q in report['questions']:
        cells = ', '.join('%s%s' % (c, ' x%d' % n if n > 1 else '') for c, n in sorted(q['cells'].items()))
        print('  %-6s %5.0f s  cells: %-40s approach: %-6s safe: %-5s %s' % (
            q['id'], q['t'], cells, ','.join(map(str, q['approach'])) or 'none', q['safe'],
            'ok' if q['matches_target'] else 'NOT THE TARGET'))
    tor = report.get('tor')
    if tor:
        print('  TOR    %5.0f s  (target %.0f), %.0f s after the last gaze window, T%+.0f .. T%+.0f s %s; '
              'safe lane %d, approaching car in lane %d; block end %.0f s' % (
                  tor['t'], tor['target'], tor['after_last_window_s'], tor['straight_rel_s'][0], tor['straight_rel_s'][1],
                  'on a straight' if tor['straight'] else 'NOT ALL ON A STRAIGHT' if tor['straight'] is False else
                  '(curves not known)', tor['safe_lane'], tor['unsafe_lane'], schedule['block_end_s']))
    for event in schedule['events']:
        if event['type'] == 'F' and abs(event['t'] - event['t_doc']) > 1e-6:
            print('  %-6s moved %+.1f s to %.1f s (lead car)' % (event['id'], event['t'] - event['t_doc'], event['t']))
        if event['type'] == 'R':
            print('  %-6s window %.1f-%.1f s (falls back past 10 m at %.1f s)' % (
                event['id'], event['window'][0], event['window'][1], event['t_exit']))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--set', action='append', help='A, B, C or P (practice); default: all')
    parser.add_argument('--check', action='store_true', help='print the report of the saved schedules')
    parser.add_argument('--config', default=CONFIG_FILE)
    parser.add_argument('--fast-lane', type=int, choices=(0, 1, 3),
                        help="the passing lane: 1 (left) or 3 (right, the reverse); 0: none, faster_share in "
                             "both lanes; default: background fast_lane in the config")
    parser.add_argument('--ignore-curves', action='store_true',
                        help="the document's times, from the loop start (no ego profile)")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.fast_lane is not None:
        config['background']['fast_lane'] = args.fast_lane or None
    names = args.set or list(config['blocks'])
    os.makedirs(SCHEDULE_DIR, exist_ok=True)
    profile = None
    if not args.check:
        import abc_ego  # next to this script
        if os.path.isfile(abc_ego.PROFILE_FILE) and not args.ignore_curves:
            profile = abc_ego.load_profile()
        else:
            print("No ego profile (abc_ego.py --log): the document's times, curves or not")
    taken = {}  # set -> its TOR time (A, B, C: tor_apart_s apart)
    if not args.check:
        for other in config['blocks']:
            if other not in names and not config['blocks'][other].get('practice') and os.path.isfile(schedule_path(other)):
                tor = next((e for e in load_schedule(other)['events'] if e['type'] == 'TOR'), None)
                if tor is not None:
                    taken[other] = tor['t']
    for name in names:
        practice = config['blocks'][name].get('practice')
        avoid = [] if practice else list(taken.values())
        if args.check:
            schedule = load_schedule(name)
        elif profile is None:
            schedule = make_schedule(config, name)
        else:  # the best start point whose questions' layouts can be placed
            schedule = None
            events = sorted([dict(e) for e in config['sets'][name]], key=lambda e: e['t'])
            for k, plan in enumerate(rank_starts(events, config['blocks'][name], profile, name,
                                                 config['templates'].get('TOR'), avoid,
                                                 config['ego']['speed_kmh'])[:PLAN_TRIES]):
                try:
                    schedule = make_schedule(config, name, plan)
                    break
                except RuntimeError as error:
                    print('  %s, start %.0f m: %s; the next start point' % (name, plan[1], error))
            if schedule is None:
                raise RuntimeError('%s: none of the %d best start points worked' % (name, PLAN_TRIES))
            with open(schedule_path(name), 'w', encoding='utf-8') as handle:
                json.dump(schedule, handle, ensure_ascii=False, separators=(',', ':'))
        tor = schedule['report'].get('tor')
        if tor and not practice:
            taken[name] = tor['t']
        print_report(schedule)
        if not all(q['matches_target'] for q in schedule['report']['questions']):
            sys.exit(1)


if __name__ == '__main__':
    main()
