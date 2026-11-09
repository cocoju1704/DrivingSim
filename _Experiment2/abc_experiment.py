#!/usr/bin/env python

"""
Scenario ABC: one block of the glasses / phone / HUD experiment (Notion: 주행 시나리오 (HCIK 오럴용),
시나리오 ABC). Started by launcher.py (start_experiment.bat), or by hand:

    python _Experiment2\\abc_experiment.py --set A --block 1 --condition glasses --participant 3
    python _Experiment2\\abc_experiment.py --set P --test      practice drive, data to Data/test/

The ego car drives itself in lane 2 (Town04's real lane 3) at 95 km/h from start to end and reacts to
nothing. The cars around it follow the set's schedule (schedules/<set>.json, abc_schedule.py):

    S   a car comes up in lane 1 or 3 behind the car and signals towards lane 2 for 5 s
        -> the paddle on that side (left mirror: left paddle, right mirror: right paddle)
    SD  the same without the turn signal (distractor)                -> no response
    R   a car comes up close behind in lane 2 (rear-view mirror)    -> the wheel's rear button
    F   the car ahead in lane 2 brakes (brake light 3 s, -8 km/h)    -> nothing (gaze only)
    Q   SAGAT: the simulation stops, the monitors go black, the questions are on the tablet;
        after the answer (or 60 s) 3-2-1 on the monitors and the tablet, then the drive goes on

Responses: wheel buttons in wheel_buttons.json ("responses": paddle_left, paddle_right, rear), or the
keys Z, X, C. The turn signals are off: the paddles only answer. A response within an event's window
(S, SD: T .. T+7 s; R: T .. 2 s after it falls back past 10 m) is scored for that event; outside
any window it is a false alarm. At the end the feedback line is on the monitors (and feedback.txt).

Keys (experimenter): ESC ends the run, TAB the next camera view, F1 the info panel, N during a
question skips it (no answer).

Data (--out, else Data/P<nn>_B<block>_<set>_<condition>/, --test: Data/test/<MMDDHHMMSS>/):
    run.json        the options, the set, versions
    frames.csv      every frame: times, the ego car, its controls
    vehicles.csv    every frame: every car around it: course id, kind, lane, planned and real dx,
                    relative speed, lights
    events.csv      appearances, turn signals, brake lights, windows, freezes, video commands
    responses.csv   every button press and what it was scored as
    sagat.json      each question: the real layout at the freeze, the answer, the scores
    summary.json, feedback.txt
    gaze_*.csv      with --gaze (Tobii Pro Nano, gaze_bridge.py)
"""

from __future__ import print_function

import argparse
import csv
import datetime
import json
import logging
import math
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import carla  # noqa: E402

import carla_base as base  # noqa: E402  (pygame, manual_control, the wheel, the mirrors)
from carla_base import pygame  # noqa: E402
import abc_schedule  # noqa: E402
import abc_traffic  # noqa: E402

DATA_DIR = os.path.join(HERE, 'Data')
RESPONSE_FILE = os.path.join(HERE, 'wheel_buttons.json')
CONDITIONS = ('glasses', 'phone', 'hud')
CONDITION_NAMES = {'glasses': '글래스', 'phone': '휴대폰', 'hud': '앞유리 화면'}
AUTO = 'AUTO'  # the whole block: L3 driving, no takeover (the TOR is not part of the scenario)
AUDIO_MUTE_PORT = 5006     # carla-audio-engine fmain.py: "mute" / "unmute" (the car sound during a question)
RESUME_FIXED_FRAMES = 3     # frames with a fixed step after a freeze (a variable one would be the freeze)
FRONT_CELLS = ('1_front', '2_front', '3_front')
APPROACH_ANSWER = {'left': 1, 'behind': 2, 'right': 3}
SAFE_ANSWER = {'left': '1', 'right': '3', 'both': 'both', 'none': 'none'}
KEY_RESPONSES = {pygame.K_z: 'paddle_left', pygame.K_x: 'paddle_right', pygame.K_c: 'rear'}
RESPONSE_NAMES = {'paddle_left': '왼쪽 패들', 'paddle_right': '오른쪽 패들', 'rear': '상단 버튼'}
BADGE = {AUTO: ('L3 자율주행 작동 중', (40, 160, 70))}


# ==============================================================================
# -- data ----------------------------------------------------------------------
# ==============================================================================


class DataLog(object):
    """The run's files (none with --no-log)."""

    COLUMNS = {
        'frames.csv': ('t_sim', 'wall_time', 'frame', 'mode', 'ego_x', 'ego_y', 'ego_z', 'ego_yaw', 'speed_kmh',
                       'steer', 'throttle', 'brake', 'fps'),
        'vehicles.csv': ('t_sim', 'id', 'kind', 'event', 'lane', 'dx_plan', 'dx', 'dv_kmh', 'lights'),
        'events.csv': ('t_sim', 'wall_time', 'id', 'what'),
        'responses.csv': ('t_sim', 'wall_time', 'button', 'source', 'event', 'scored_as', 'rt_s'),
    }

    def __init__(self, directory):
        self.dir = directory
        self._files = {}
        self._gaze_columns = None
        if directory:
            os.makedirs(directory, exist_ok=True)

    def row(self, name, values, extra=None):
        if not self.dir:
            return
        if name not in self._files:
            stream = open(os.path.join(self.dir, name), 'w', newline='', encoding='utf-8')
            writer = csv.writer(stream)
            columns = list(self.COLUMNS[name]) + (sorted(extra) if extra else [])
            if extra:
                self._gaze_columns = sorted(extra)
            writer.writerow(columns)
            self._files[name] = (stream, writer)
        values = list(values)
        if extra and self._gaze_columns:
            values += [extra.get(k, '') for k in self._gaze_columns]
        self._files[name][1].writerow(values)

    def event(self, t, what, eid='-'):
        logging.info('%7.2f s  %-8s %s', t, eid, what)
        self.row('events.csv', (round(t, 3), round(time.time(), 3), eid, what))

    def json(self, name, data):
        if self.dir:
            with open(os.path.join(self.dir, name), 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)

    def text(self, name, text):
        if self.dir:
            with open(os.path.join(self.dir, name), 'w', encoding='utf-8') as handle:
                handle.write(text)

    def flush(self):
        for stream, _ in self._files.values():
            stream.flush()

    def close(self):
        for stream, _ in self._files.values():
            stream.close()
        self._files = {}


def output_dir(args):
    if args.no_log:
        return None
    if args.out:
        return args.out
    if args.test:
        return os.path.join(DATA_DIR, 'test', datetime.datetime.now().strftime('%m%d%H%M%S'))
    name = 'P%02d_B%s_%s_%s' % (args.participant or 0, 'P' if args.set == 'P' else args.block, args.set, args.condition)
    path, k = os.path.join(DATA_DIR, name), 2
    while os.path.exists(path):  # a block run again keeps the earlier one
        path, k = os.path.join(DATA_DIR, '%s_%d' % (name, k)), k + 1
    return path


# ==============================================================================
# -- responses -----------------------------------------------------------------
# ==============================================================================


def response_buttons():
    """{wheel button number: response} from wheel_buttons.json ("responses")."""
    try:
        with open(RESPONSE_FILE, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        logging.warning('%s missing: wheel responses off (keys Z, X, C work)', RESPONSE_FILE)
        return {}
    buttons = {number: name for name, number in data.get('responses', {}).items() if number is not None and number >= 0}
    logging.info('Response buttons: %s', ', '.join('%s %d' % (name, n) for n, name in sorted(buttons.items())))
    return buttons


def score_responses(events, presses):
    """Scores every press, then every target. events: the schedule's S, SD, R with 'window'.
    Returns (presses with 'event', 'scored_as', 'rt_s'; per-target outcomes)."""
    windowed = [e for e in events if e['type'] in ('S', 'SD', 'R')]
    outcome = {e['id']: {'id': e['id'], 'type': e['type'], 'lane': e.get('lane'), 't': e['t'],
                         'window': e['window'], 'outcome': 'miss' if e['type'] != 'SD' else 'correct_rejection',
                         'rt_s': None} for e in windowed}
    for press in presses:
        press['event'], press['scored_as'], press['rt_s'] = '', 'false_alarm_outside', None
        if press.get('frozen'):
            press['scored_as'] = 'during_question'
            continue
        for e in windowed:
            low, high = e['window']
            if not low <= press['t'] <= high:
                continue
            press['event'] = e['id']
            target = outcome[e['id']]
            if e['type'] == 'SD':
                press['scored_as'] = 'false_alarm'
                target['outcome'] = 'false_alarm'
            else:
                right = 'rear' if e['type'] == 'R' else ('paddle_left' if e['lane'] == 1 else 'paddle_right')
                if press['button'] == right:
                    if target['outcome'] == 'hit':
                        press['scored_as'] = 'repeat'
                    else:
                        press['scored_as'] = 'hit'
                        press['rt_s'] = round(press['t'] - e['t'], 3)
                        target['outcome'], target['rt_s'] = 'hit', press['rt_s']
                else:
                    press['scored_as'] = 'wrong_button'
                    if target['outcome'] == 'miss':
                        target['outcome'] = 'wrong_button'
            break
    return presses, [outcome[e['id']] for e in windowed]


# ==============================================================================
# -- SAGAT ---------------------------------------------------------------------
# ==============================================================================


def sagat_truth(snapshot, qt):
    """The answers from the cars as they are at the freeze: [(id, lane, dx, dx 5 s before)]."""
    now = [(lane, dx) for _, lane, dx, _ in snapshot]
    history = {k: before for k, (_, _, _, before) in enumerate(snapshot) if before is not None}
    cells, approach, safe = abc_schedule.layout(now, history, qt)
    return {'cells': cells, 'approach': approach, 'safe': safe,
            'cars': [{'id': cid, 'lane': lane, 'dx': round(dx, 2), 'dx_5s_before': None if b is None else round(b, 2)}
                     for cid, lane, dx, b in snapshot]}


def sagat_score(truth, answer):
    if answer is None:
        return {'answered': False}
    marked = set(answer.get('cells', []))
    present = set(truth['cells'])
    cells = {cell: (cell in marked) == (cell in present) for cell in abc_schedule.CELLS}
    front = [cells[c] for c in FRONT_CELLS]
    around = [cells[c] for c in abc_schedule.CELLS if c not in FRONT_CELLS]
    approach = sorted(APPROACH_ANSWER[a] for a in answer.get('approach', []) if a in APPROACH_ANSWER)
    approach_ok = approach == sorted(truth['approach'])
    safe_ok = SAFE_ANSWER.get(answer.get('safe')) == truth['safe']
    grid = sum(cells.values()) / float(len(cells))
    return {'answered': True, 'cells_correct': cells, 'grid': round(grid, 3),
            'grid_front': round(sum(front) / float(len(front)), 3),
            'grid_around': round(sum(around) / float(len(around)), 3),
            'approach_correct': approach_ok, 'safe_correct': safe_ok,
            'score': round((grid + approach_ok + safe_ok) / 3.0, 3)}


# ==============================================================================
# -- screen --------------------------------------------------------------------
# ==============================================================================


class Overlay(object):
    """The instrument cluster of carla_base (the gauges tablet), the L3 badge above it, and the
    black screens of a question and of the end.

    Layout at the bottom of the middle monitor: the cluster on the left and the HUD's video area
    right next to it (where the glasses' display appears: lower right of the view), the two
    together centred. The HUD area is square, HUD_DEG wide (as the glasses' display); hud_rect is
    where the HUD condition's video goes (--hud-preview draws its outline)."""

    _draw_cluster = base.TakeoverExperiment._draw_cluster
    HUD_DEG = 8.0     # degrees across, as the glasses' display
    HUD_GAP = 24      # px between the cluster and the HUD area

    def _cluster_face(self, size):
        face = base.TakeoverExperiment._cluster_face(size)
        width, height = size
        panel_w = face['face'].get_width()
        hud = self.hud_size(size)
        left = (width - (panel_w + self.HUD_GAP + hud)) // 2  # the pair centred on the monitor
        face['origin'] = (left, face['origin'][1])
        self.hud_rect = pygame.Rect(left + panel_w + self.HUD_GAP, height - hud, hud, hud)
        return face

    def hud_size(self, size):
        """px across HUD_DEG at the middle monitor's field of view."""
        fov = self._world.camera_manager.screen_fov if hasattr(self._world.camera_manager, 'screen_fov') else 43.0
        return int(size[0] * math.tan(math.radians(self.HUD_DEG / 2.0)) / math.tan(math.radians(fov / 2.0)))

    def __init__(self, world, hud_preview=False):
        self._world = world
        self.hud_rect = None
        self._hud_preview = hud_preview
        self._phone_cluster = None
        self._cluster = None
        self._needles = [0.0, 0.0]
        self._pedal = 0.0
        self._speed_kmh = 0.0
        self._lights = 0  # no turn signals: the paddles only answer
        name = pygame.font.match_font('malgungothic,applesdgothicneo,notosanscjkkr') or pygame.font.get_default_font()
        self._font_name = name
        self.big = pygame.font.Font(name, 40)
        self.big.set_bold(True)
        self.small = pygame.font.Font(name, 24)
        self.badge = pygame.font.Font(name, 22)
        self.badge.set_bold(True)
        self.count = pygame.font.Font(name, 220)
        self.count.set_bold(True)
        self.text = pygame.font.Font(name, 34)

    def middle(self):
        manager = self._world.camera_manager
        width, height = manager.screen_size
        return manager.screens // 2 * width, width, height

    def render(self, display, mode, speed_kmh, pedal):
        self._speed_kmh, self._pedal = speed_kmh, pedal
        self._draw_cluster(display)
        if self._world.camera_manager.transform_index == 0 and self._cluster is not None:
            x0, width, height = self.middle()
            label, color = BADGE[mode]
            text = self.badge.render(label, True, (255, 255, 255))
            middle = x0 + self._cluster['origin'][0] + self._cluster['face'].get_width() // 2  # above the cluster
            box = text.get_rect(midbottom=(middle, self._cluster['origin'][1] - 10)).inflate(28, 12)
            pygame.draw.rect(display, color, box, border_radius=8)
            display.blit(text, text.get_rect(center=box.center))
            if self._hud_preview and self.hud_rect is not None:
                rect = self.hud_rect.move(x0, 0)
                pygame.draw.rect(display, (90, 200, 255), rect, 3)
                label = self.badge.render('HUD 영상 영역 (%.0f°)' % self.HUD_DEG, True, (90, 200, 255))
                display.blit(label, label.get_rect(center=rect.center))

    def black(self, display, lines=(), count=None):
        display.fill((0, 0, 0))
        x0, width, height = self.middle()
        if count is not None:
            text = self.count.render(str(count), True, (235, 235, 235))
            display.blit(text, text.get_rect(center=(x0 + width // 2, height // 2)))
        y = height // 2 - 30 * len(lines)
        for line in lines:
            text = self.text.render(line, True, (150, 150, 150))
            display.blit(text, text.get_rect(center=(x0 + width // 2, y)))
            y += 60


# ==============================================================================
# -- the block -----------------------------------------------------------------
# ==============================================================================


class Block(object):
    def __init__(self, args):
        self.args = args
        self.config = abc_schedule.load_config()
        self.schedule = abc_schedule.load_schedule(args.set)
        self.qt = self.config['templates']['Q']
        self.log = DataLog(output_dir(args))
        self.presses = []
        self.questions = []
        self.mode = AUTO
        self.frozen = False
        self.exit_times = {}    # R id -> time it fell back past 10 m (measured)
        self._r_release = {e['id']: e['t'] + self.config['templates']['R']['release_rel_s']
                           for e in self.schedule['events'] if e['type'] == 'R'}
        self._marks_done = set()
        self.g2 = None
        self.media = []         # NDRT video players: pause() / resume() at the questions (later)

    # -- marks ---------------------------------------------------------------------------------

    def mark(self, t, what, eid='-', **fields):
        self.log.event(t, what, eid)
        if self.g2 is not None:
            self.g2.mark(what.split(' ')[0], id=eid, t_sim=round(t, 3), **fields)

    def timed_marks(self, t):
        """The schedule's moments (event T, window ends) as they pass."""
        for e in self.schedule['events']:
            if e['type'] in ('S', 'SD', 'R', 'F') and e['id'] not in self._marks_done and t >= e['t']:
                self._marks_done.add(e['id'])
                what = {'S': 'onset (turn signal on)', 'SD': 'onset (no signal)', 'R': 'onset (closer than 10 m)',
                        'F': 'onset (brake light)'}[e['type']]
                self.mark(t, what, e['id'], type=e['type'])
            if 'window' in e and e['id'] + '/end' not in self._marks_done and t >= self.window(e)[1]:
                self._marks_done.add(e['id'] + '/end')
                self.mark(t, 'window end', e['id'])

    def window(self, e):
        if e['type'] == 'R' and e['id'] in self.exit_times:
            return [e['t'], round(self.exit_times[e['id']] + self.config['templates']['R']['window_after_exit_s'], 3)]
        return e['window']

    def track_rear(self, t, state):
        """R: the time it really falls back past 10 m bumper to bumper (onset_dx_m), for its window."""
        onset = self.config['templates']['R']['onset_dx_m']
        for rid, release in self._r_release.items():
            if rid in self.exit_times or rid not in state or t < release:
                continue
            if state[rid][1] < onset:
                self.exit_times[rid] = t
                self.mark(t, 'falls back past 10 m', rid)

    # -- presses -------------------------------------------------------------------------------

    def media_results(self, t):
        """What the video players did (their own reports), into the event log."""
        for player in self.media:
            while not player.results.empty():
                wall, action, delivered, state = player.results.get()
                what = 'video %s: %s' % (action, 'not sent' if delivered is None else
                                         'no glasses connected' if not delivered else
                                         'glasses at %s s%s%s' % (state.get('t'), ', paused' if state.get('paused') else '',
                                                                  ', covered' if state.get('frozen') else ''))
                self.log.event(t, what, state.get('id') or '-')

    def press(self, t, button, source):
        self.presses.append({'t': t, 'wall': time.time(), 'button': button, 'source': source, 'frozen': self.frozen})
        logging.info('%7.2f s  response  %s (%s)%s', t, button, source, ' during a question' if self.frozen else '')
        if self.g2 is not None:
            self.g2.mark('response', button=button, t_sim=round(t, 3))

    # -- the end -------------------------------------------------------------------------------

    def finish(self, t_end, aborted):
        events = [dict(e, window=self.window(e)) for e in self.schedule['events'] if e['type'] in ('S', 'SD', 'R')]
        presses, targets = score_responses(events, self.presses)
        for p in presses:
            self.log.row('responses.csv', (round(p['t'], 3), round(p['wall'], 3), p['button'], p['source'],
                                           p['event'], p['scored_as'], '' if p['rt_s'] is None else p['rt_s']))
        real = [x for x in targets if x['type'] in ('S', 'R')]
        hits = sum(1 for x in real if x['outcome'] == 'hit')
        rts = [x['rt_s'] for x in real if x['rt_s'] is not None]
        answered = [q['score'] for q in self.questions if q['score'].get('answered')]
        sagat = round(100.0 * sum(s['score'] for s in answered) / len(answered)) if answered else None
        due = [x for x in real if x['window'][1] <= t_end]  # aborted runs: only those it got to
        feedback = ('수고하셨습니다. 이번 주행 결과입니다. 영상 시험 ○○점, 미러 차량 발견 %d개 중 %d개, '
                    '주변 차량 질문 %s점입니다.' % (len(due), hits, '-' if sagat is None else sagat))
        summary = {
            'set': self.args.set, 'block': self.args.block, 'condition': self.args.condition,
            'participant': self.args.participant, 'test': self.args.test, 'aborted': aborted, 't_end': round(t_end, 2),
            'mirror_targets': {'hits': hits, 'of': len(due), 'mean_rt_s': round(sum(rts) / len(rts), 3) if rts else None,
                               'side_hits': sum(1 for x in real if x['type'] == 'S' and x['outcome'] == 'hit'),
                               'rear_hits': sum(1 for x in real if x['type'] == 'R' and x['outcome'] == 'hit'),
                               'wrong_button': sum(1 for x in real if x['outcome'] == 'wrong_button')},
            'false_alarms': {'distractor': sum(1 for x in targets if x['outcome'] == 'false_alarm'),
                             'outside_windows': sum(1 for p in presses if p['scored_as'] == 'false_alarm_outside')},
            'targets': targets,
            'sagat': {'score_percent': sagat, 'questions': [{'id': q['id'], **q['score']} for q in self.questions]},
            'feedback': feedback}
        self.log.json('summary.json', summary)
        self.log.json('sagat.json', self.questions)
        self.log.text('feedback.txt', feedback + '\n')
        print()
        print('=' * 78)
        print(feedback)
        print('  mirror targets %d/%d (side %d, rear %d), false alarms %d + %d outside, SAGAT %s' % (
            hits, len(due), summary['mirror_targets']['side_hits'], summary['mirror_targets']['rear_hits'],
            summary['false_alarms']['distractor'], summary['false_alarms']['outside_windows'],
            '-' if sagat is None else '%d %%' % sagat))
        if self.log.dir:
            print('  data: %s' % self.log.dir)
        print('=' * 78)
        return feedback


def build_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--set', choices=('A', 'B', 'C', 'P'), required=True, help='A, B, C or P (practice)')
    parser.add_argument('--block', default='1', help='block 1, 2, 3 (P: practice)')
    parser.add_argument('--condition', choices=CONDITIONS, default='phone')
    parser.add_argument('--participant', type=int, default=0)
    parser.add_argument('--test', action='store_true', help='data to Data/test/<MMDDHHMMSS>')
    parser.add_argument('--out', help='data folder (default: see above)')
    parser.add_argument('--no-log', action='store_true')
    parser.add_argument('--start-at', type=float, default=0.0,
                        help='checking: start the block this many s in (events before it are skipped)')
    parser.add_argument('--duration', type=float, default=None, help='checking: quit after this many s of the block')
    parser.add_argument('--feedback-seconds', type=float, default=600.0,
                        help='the feedback screen at the end stays this long at most (a key closes it)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('-p', '--port', type=int, default=2000)
    parser.add_argument('--res', default='7680x1440')
    parser.add_argument('--window-pos', default='-2560,0')
    parser.add_argument('--screens', type=int, default=3)
    parser.add_argument('--screen-fov', type=float, default=43.0)
    parser.add_argument('--no-mirrors', action='store_true')
    parser.add_argument('--render-scale', type=float, default=1.0)
    parser.add_argument('--fps', type=float, default=60.0)
    parser.add_argument('--filter', default=base.DEFAULT_VEHICLE)
    parser.add_argument('--view', choices=['driver', 'windshield', 'chase'], default='driver')
    parser.add_argument('--gamma', type=float, default=2.2)
    parser.add_argument('--trees', action='store_true')
    parser.add_argument('--no-sound', action='store_true')
    parser.add_argument('--no-audio-engine', action='store_true')
    parser.add_argument('--input', choices=['auto', 'keyboard', 'wheel'], default='auto')
    parser.add_argument('--wheel-force', type=float, default=80.0)
    parser.add_argument('--joystick', type=int, default=0)
    parser.add_argument('--steer-axis', type=int, default=0)
    parser.add_argument('--throttle-axis', type=int, default=2)
    parser.add_argument('--brake-axis', type=int, default=1)
    parser.add_argument('--pedal-rest', type=int, default=1, choices=[1, -1])
    parser.add_argument('--sagat-port', type=int, default=5011)
    parser.add_argument('--hud-preview', action='store_true',
                        help="the outline of the HUD's video area right of the cluster (for setting up)")
    parser.add_argument('--gaze', action='store_true', help='Tobii Pro Nano: gaze_bridge.py sends the gaze (UDP)')
    parser.add_argument('--gaze-port', type=int, default=5010)
    parser.add_argument('--gaze-tolerance', type=float, default=45.0)
    parser.add_argument('--g2', metavar='HOST', help='Tobii Pro Glasses 2 recording unit: event markers')
    parser.add_argument('--g2-record', action='store_true', help='with --g2: start and stop a recording too')
    parser.add_argument('--video', metavar='HOST[:PORT]',
                        help='the NDRT video player on the glasses / phone (mrbd_video): paused at the questions')
    parser.add_argument('--video-file', default=None, help='the video the player plays (its name on the device)')
    parser.add_argument('--video-start', type=float, default=0.0, help='s into the video at the block start')
    # the wheel options carla_base's WheelInput reads (buttons: wheel_buttons.json)
    parser.set_defaults(gaze_query=False, **{option: None for _, option, _, _ in base.WHEEL_ACTIONS})
    args = parser.parse_args()
    args.width, args.height = [int(x) for x in args.res.split('x')]
    args.sync = True
    args.generation = 'All'
    args.rolename = 'hero'
    args.scenario = 1          # carla_base: not the practice drive's bright camera exposure
    args.no_glasses = True
    if args.set == 'P':
        args.block = 'P'
    return args


def main():
    args = build_args()
    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
    if args.input == 'auto':
        pygame.joystick.init()
        args.input = 'wheel' if pygame.joystick.get_count() > 0 else 'keyboard'
    try:
        completed = run(args) is False  # False: not aborted (None: ended with ESC)
    except KeyboardInterrupt:
        print('\nCancelled.')
        completed = False
    sys.exit(0 if completed else 2)  # the launcher goes on to the next block only after a whole one


def run(args):
    block = Block(args)
    schedule = block.schedule
    logging.info('Set %s, block %s, condition %s, participant %s, data: %s', args.set, args.block, args.condition,
                 args.participant, block.log.dir or '(none)')
    block.log.json('run.json', {'args': {k: v for k, v in vars(args).items() if not callable(v)},
                                'started': datetime.datetime.now().isoformat(timespec='seconds'),
                                'schedule_seed': schedule['seed'], 'events': schedule['events'],
                                'real_lane': block.config['real_lane']})
    pygame.init()
    pygame.font.init()
    world = client = sim_world = ticker = traffic = sagat = gaze = audio = driver_input = None
    async_settings = None
    collision_sensor = None
    green_lights = []
    t = 0.0
    aborted = True
    try:
        from sagat_server import SagatServer
        sagat = SagatServer(args.sagat_port)
        if args.g2:
            from g2_link import G2Link
            block.g2 = G2Link(args.g2, os.path.basename(block.log.dir or 'abc'), record=args.g2_record)
        if args.video:
            from video_link import VideoLink
            block.media.append(VideoLink(args.video, args.video_file, args.video_start))
        driver_input = base.WheelInput(args) if args.input == 'wheel' else base.KeyboardInput()
        responses = response_buttons() if args.input == 'wheel' else {}
        client = base.connect_server(args.host, args.port)
        sim_world = client.get_world()
        if not sim_world.get_map().name.endswith(base.MAP_NAME):
            logging.info('Loading %s...', base.MAP_NAME)
            sim_world = client.load_world(base.MAP_NAME)
        trees = {tree.id for tree in sim_world.get_environment_objects(carla.CityObjectLabel.Vegetation)}
        sim_world.enable_environment_objects(trees, args.trees)
        traffic_manager = client.get_trafficmanager(base._free_port())  # pylint: disable=protected-access
        async_settings = sim_world.get_settings()
        async_settings.synchronous_mode = False
        async_settings.fixed_delta_seconds = None
        settings = sim_world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = None   # each step as long as the frame: real time
        sim_world.apply_settings(settings)
        traffic_manager.set_synchronous_mode(True)
        ticker = base.SimTicker(sim_world)
        audio = base.AudioEngine(not args.no_audio_engine)
        base.remove_stale_actors(client, sim_world)

        flags = pygame.HWSURFACE | pygame.DOUBLEBUF
        if args.window_pos:
            os.environ['SDL_VIDEO_WINDOW_POS'] = args.window_pos
            flags |= pygame.NOFRAME
        display = pygame.display.set_mode((args.width, args.height), flags)
        display.fill((0, 0, 0))
        pygame.display.flip()
        hud = base.HUD(args.width, args.height)
        world = base.World(sim_world, hud, args)
        hud._show_info = False  # pylint: disable=protected-access
        base.add_driver_view(world, args)
        base.soften_engine_braking(world.player)
        green_lights = base.hold_lights_green(sim_world)

        carla_map = world.map
        anchor = carla_map.get_waypoint(carla_map.get_spawn_points()[base.START_SPAWN_INDEX].location)
        routes = {lane: base.build_loop_route(carla_map, base.lane_waypoint(anchor, lane)) for lane in (2, 3)}
        route = routes[3]
        traffic = abc_traffic.ScriptedTraffic(client, sim_world, carla_map, routes, schedule, block.config)
        # the set's start point along the loop: its events on the straights (abc_schedule, abc_ego)
        start_index = traffic.ego_route.index_at(schedule.get('ego_start_m', 0.0))
        traffic.start(start_index)
        logging.info('Start %.0f m along the loop (route point %d)', schedule.get('ego_start_m', 0.0), start_index)
        start = route[start_index].transform
        start.location.z += 0.5
        world.player.set_transform(start)
        sim_world.tick()
        speed = block.config['ego']['speed_kmh']
        forward = start.get_forward_vector()
        world.player.set_target_velocity(carla.Vector3D(forward.x * speed / 3.6, forward.y * speed / 3.6, 0.0))
        sim_world.tick()
        planner = base.GlobalRoutePlanner(carla_map, base.ROUTE_RESOLUTION)
        follower = base.LoopFollower(world.player, route, speed, carla_map, planner)
        follower._agent.ignore_vehicles(True)  # pylint: disable=protected-access  (it reacts to nothing)
        sim_clock = [sim_world.get_snapshot().timestamp.elapsed_seconds]
        follower.clock = lambda: sim_clock[0]  # its speed changes with the simulation's time: the same every run
        overlay = Overlay(world, hud_preview=args.hud_preview)
        if args.gaze:
            from gaze_tracking import GazeTracker
            gaze = GazeTracker(sim_world, world, args.gaze_port, args.gaze_tolerance)
            gaze.log_to(block.log.dir)
        collision_sensor, collisions = base.log_collisions(sim_world, world.player)
        logged_collisions = 0
        control = carla.VehicleControl()
        if not sagat.connected(0.1):
            logging.info('SAGAT tablet: %s (not connected yet)', sagat.url)

        sim_world.tick()
        t_zero = sim_world.get_snapshot().timestamp.elapsed_seconds - args.start_at
        questions = [e for e in schedule['events'] if e['type'] == 'Q' and e['t'] >= args.start_at]
        q_number = sum(1 for e in schedule['events'] if e['type'] == 'Q' and e['t'] < args.start_at)
        block._marks_done.update(k for e in schedule['events'] if e['t'] < args.start_at for k in (e['id'], e['id'] + '/end'))
        fixed_frames = 0
        clock = pygame.time.Clock()
        block.mark(args.start_at, 'block start', set=args.set, condition=args.condition)
        for player in block.media:
            player.start()
        while True:
            clock.tick_busy_loop(args.fps)
            ticker.wait()
            snapshot = sim_world.get_snapshot()
            t = snapshot.timestamp.elapsed_seconds - t_zero
            sim_clock[0] = snapshot.timestamp.elapsed_seconds
            dt = snapshot.timestamp.delta_seconds
            if fixed_frames:
                fixed_frames -= 1
                if not fixed_frames:  # back to real-time steps
                    settings.fixed_delta_seconds = None
                    sim_world.apply_settings(settings)
            keys = pygame.key.get_pressed()
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYUP and event.key == pygame.K_ESCAPE):
                    return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                    base.next_view(world)
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
                    world.hud.toggle_info()
                elif event.type == pygame.KEYDOWN and event.key in KEY_RESPONSES:
                    block.press(t, KEY_RESPONSES[event.key], 'key')
                elif event.type == pygame.JOYBUTTONDOWN and event.button in responses:
                    block.press(t, responses[event.button], 'wheel %d' % event.button)
            if t >= schedule['block_end_s'] or (args.duration and t - args.start_at >= args.duration):
                aborted = t < schedule['block_end_s']
                break

            # a question: everything stops until it is answered
            if questions and t >= questions[0]['t']:
                q = questions.pop(0)
                q_number += 1
                if not ask_question(block, q, q_number, t, traffic, sagat, overlay, display, responses, clock):
                    return
                settings.fixed_delta_seconds = 1.0 / args.fps  # the next step is one frame, not the freeze
                sim_world.apply_settings(settings)
                fixed_frames = RESUME_FIXED_FRAMES
                ticker.start()
                continue

            state = traffic.tick(t, world.player, dt)
            for t_log, cid, what in traffic.log:
                block.log.event(t_log, what, cid)
            del traffic.log[:]
            block.timed_marks(t)
            block.track_rear(t, state)
            block.media_results(t)

            # the ego car
            transform = world.player.get_transform()
            velocity = world.player.get_velocity()
            speed_kmh = velocity.length() * 3.6
            control = follower.run_step()  # it drives itself from start to end
            pedal = control.throttle
            world.player.apply_control(control)
            driver_input.force_feedback(speed_kmh)
            lights = base.BRAKE_LIGHT if control.brake > 0.0 else 0
            world.player.set_light_state(carla.VehicleLightState(lights))
            while logged_collisions < len(collisions):
                block.mark(t, 'collision: %s' % collisions[logged_collisions])
                logged_collisions += 1

            now = time.monotonic()
            gaze_fields = None
            if gaze is not None:
                gaze.tick(now, world.camera_manager.transform_index in base.DRIVER_VIEWS)
                gaze_fields = gaze.log_fields()
            location = transform.location
            block.log.row('frames.csv', (round(t, 3), round(time.time(), 3), snapshot.frame, block.mode,
                                         round(location.x, 2), round(location.y, 2), round(location.z, 2),
                                         round(transform.rotation.yaw, 2), round(speed_kmh, 2), round(control.steer, 3),
                                         round(control.throttle, 3), round(control.brake, 3),
                                         round(clock.get_fps(), 1)), gaze_fields)
            for cid, (lane, dx, dv) in state.items():
                car = traffic.cars.get(cid)
                course = car['course'] if car else None
                planned = course.at(t) if course else None
                block.log.row('vehicles.csv', (round(t, 3), cid, course.kind if course else '',
                                               (course.event or ('F' if course.f_event else '')) if course else '',
                                               lane, '' if planned is None else round(planned[0], 2), round(dx, 2),
                                               round(dv, 2), abc_traffic._light_names(car['lights']) if car else ''))

            ticker.start()
            world.tick(clock)
            world.render(display)
            overlay.render(display, block.mode, speed_kmh, pedal)
            pygame.display.flip()
        # the end of the block
        block.mark(t, 'block end')
    finally:
        if ticker is not None:
            try:
                ticker.wait()
            except RuntimeError:
                pass
        for player in block.media:
            player.stop()
            player.close()
        block.media_results(t)
        feedback = block.finish(t, aborted)
        if block.g2 is not None:
            block.mark(t, 'run end')
            block.g2.close()
        block.log.close()
        if async_settings is not None:
            try:
                sim_world.apply_settings(async_settings)
            except RuntimeError:
                pass
        if sagat is not None:
            sagat.close()
        if gaze is not None:
            gaze.close()
        if driver_input is not None:
            driver_input.close()
        if audio is not None:
            audio.stop()
        if collision_sensor is not None:
            collision_sensor.stop()
            collision_sensor.destroy()
        if traffic is not None:
            traffic.destroy()
        base.release_lights(green_lights)
        if world is not None:
            if getattr(world.camera_manager, 'side_views', None):
                base.destroy_side_views(world.camera_manager)
            world.destroy()
            # last, with the server already free: the feedback on the monitors until a key
            try:
                show_feedback(display, Overlay(world), feedback, args.feedback_seconds)
            except Exception:  # pylint: disable=broad-except
                logging.exception('Feedback screen')
        pygame.quit()
    return aborted


def car_sound(on):
    """The car sound of carla-audio-engine on or off (it plays on while the simulation stands still)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.sendto(b'unmute' if on else b'mute', ('127.0.0.1', AUDIO_MUTE_PORT))
    except OSError:
        pass


def ask_question(block, q, number, t, traffic, sagat, overlay, display, responses, clock):
    """SAGAT: the simulation is not stepped, the monitors are black, the tablet asks. Returns False
    if the run was ended (ESC)."""
    truth = sagat_truth(traffic.snapshot(t, block.qt['approach_window_s']), block.qt)
    block.frozen = True
    car_sound(False)
    for player in block.media:
        player.pause(q['id'])
    block.mark(t, 'freeze (SAGAT %d)' % number, q['id'])
    seconds = block.qt['max_answer_s']
    sagat.ask(q['id'], number, seconds)
    started = time.monotonic()
    if not sagat.connected():
        logging.warning('SAGAT tablet not connected: open %s on the iPad', sagat.url)
    answer = None
    skipped = False
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYUP and event.key == pygame.K_ESCAPE):
                sagat.idle()
                car_sound(True)
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_n:
                skipped = True
            elif event.type == pygame.KEYDOWN and event.key in KEY_RESPONSES:
                block.press(t, KEY_RESPONSES[event.key], 'key')
            elif event.type == pygame.JOYBUTTONDOWN and event.button in responses:
                block.press(t, responses[event.button], 'wheel %d' % event.button)
        answer = sagat.answer()
        waited = time.monotonic() - started
        if answer is not None or skipped or waited >= seconds:
            break
        overlay.black(display, ['화면이 멈췄습니다', '태블릿의 질문에 답해 주세요'])
        pygame.display.flip()
        clock.tick(30)
    answer_s = round(time.monotonic() - started, 2)
    score = sagat_score(truth, answer)
    block.questions.append({'id': q['id'], 'number': number, 't': round(t, 3), 't_planned': q['t'],
                            'planned': {'cells': q['cells'], 'approach': q['approach'], 'safe': q['safe']},
                            'truth': truth, 'answer': answer, 'answer_s': answer_s,
                            'ended_by': 'answer' if answer is not None else 'skipped' if skipped else 'timeout',
                            'score': score})
    block.mark(t, 'answer after %.1f s (%s)' % (answer_s, 'answered' if answer else 'skipped' if skipped else 'timeout'),
               q['id'])
    if score.get('answered'):
        logging.info('   grid %.0f %%, approach %s, safe %s', 100 * score['grid'], score['approach_correct'],
                     score['safe_correct'])
    for count in range(block.qt['countdown_s'], 0, -1):
        sagat.countdown(count)
        until = time.monotonic() + 1.0
        while time.monotonic() < until:
            pygame.event.pump()
            overlay.black(display, count=count)
            pygame.display.flip()
            clock.tick(30)
    sagat.idle()
    block.frozen = False
    car_sound(True)
    for player in block.media:
        player.resume(q['id'])
    block.mark(t, 'resume', q['id'])
    return True


def show_feedback(display, overlay, feedback, seconds):
    """The feedback on the monitors until a key or the wheel's button (or `seconds`)."""
    first, _, rest = feedback.partition('이번 주행 결과입니다. ')
    lines = [first.strip(), '이번 주행 결과입니다.'] + [part.strip() + ('' if part.strip().endswith('.') else ',')
                                                      for part in rest.split(', ')]
    lines[-1] = lines[-1].rstrip(',')
    until = time.monotonic() + seconds
    pygame.event.clear()
    while time.monotonic() < until:
        for event in pygame.event.get():
            if event.type in (pygame.KEYDOWN, pygame.QUIT, pygame.JOYBUTTONDOWN):
                return
        overlay.black(display, lines + ['', '(아무 키나 누르면 닫힙니다)'])
        pygame.display.flip()
        time.sleep(0.05)


if __name__ == '__main__':
    main()
