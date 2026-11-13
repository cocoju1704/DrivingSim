#!/usr/bin/env python

"""
Scenario ABC: one block of the glasses / phone / HUD experiment (Notion: 주행 시나리오 (HCIK 오럴용),
시나리오 ABC). Started by launcher.py (menu.py: 실험 시작), or by hand:

    python _Experiment2\\abc_experiment.py --set A --block 1 --condition glasses --participant 3
    python _Experiment2\\abc_experiment.py --set P --test      practice drive, data to Data/test/

The ego car drives itself in lane 2 (Town04's real lane 3) at 70 km/h (abc_config ego) until the TOR and reacts to
nothing but the F's lead car (abc_follow). The cars around it follow the set's schedule (schedules/<set>.json, abc_schedule.py):

    S   a car comes up fast in lane 1 or 3 from behind (left or right side mirror), passes the car (T:
        alongside), signals and moves over 30 m ahead (lane 1 -> lane 0, lane 3 -> lane 2, in front
        of the car) and leaves ahead (since 2026-11-13; before: it held 12 m behind for 5 s and fell
        back, before 2026-11-12 also SD, and S with a turn signal towards lane 2)
    R   a car comes up close behind in lane 2 at +22.5 km/h (rear-view mirror)
    F   the car ahead in lane 2 (20-22.5 m) brakes hard (brake light 3 s, -25 km/h at 5 m/s^2) and then
        leaves ahead; the ego car brakes after it (abc_follow: 1 s later, down to about 40 km/h) and
        makes the distance up; the other cars keep their speeds (since 2026-11-13; before 30 m, -20
        km/h at 3.5 m/s^2, back to its place after)
    Q   SAGAT: the simulation stops, the monitors go black, the questions are on the tablet (was there a
        car in the own lane ahead, and in each lane behind: left / rear-view / right mirror; at most
        Q.max_answer_s, 30 s); then the NDRT video questions (ndrt_items/: 4 frames, was this scene in
        the video, yes / no + confidence) at the freeze + Q.ndrt_at_s (35 s) for everyone, the same
        recall delay; after them (or Q.ndrt_max_answer_s) 3-2-1 on the monitors and the tablet, then the
        drive goes on
    TOR at the end of every block (and of the practice drive), T = the schedule's time:
        T-15  no other car from here on (the schedule's background traffic is gone)
        T-9   the approaching car: 80 m behind in the unsafe lane, +20 km/h, no turn signal
        T-3   a stopped car 270 m ahead in lane 2, hazard lights (~190 m, TTC ~7 s at T)
        T     the alert: beeps, "지금 직접 운전하세요" blinking above the cluster (and in the HUD
              area in the HUD condition), the video paused with the same text on the glasses / phone
        a move of the wheel or a pedal (carla_base's STEER_TAKEOVER, PEDAL_TAKEOVER from where they
        were at T) takes over: manual driving, the alert off. No takeover: at TTC 1.5 s to the
        stopped car an automatic emergency stop (no_takeover). The approaching car keeps its speed;
        if the ego car comes into its lane less than 10 m ahead of it, it brakes (conflict).
        The block ends at T+30, or 5 s after the car stands still.

The participant answers nothing but the SAGAT and video questions: the events are measured by the gaze only
(Tobii Pro Glasses 2 with its event markers; analysed afterwards). For that, every frame logs in
which mirror inset each car is visible (its bounding box inside the mirror camera's field of view),
and each event gets its gaze window (gaze_windows.csv):
    S, SD   its side mirror, from the first frame the car is big enough there to make out (RECOGNIZE_PX
            tall) to T+7
    R       the rear-view mirror, from the first frame it is big enough there to 2 s after it falls
            back past 10 m
    F       the car ahead, T .. T+5
tor_events.csv has the TOR's measures (one row). At the end the monitors only say that the drive
is over; the experimenter gives the video score (the video questions' share correct; feedback.txt
has the line). SAGAT scores are kept in the data, not told.

Keys (experimenter): ESC ends the run, TAB the next camera view, F1 the info panel, N during a
question skips it (no answer; during the SAGAT questions: on to the video questions).

Data (--out, else Data/P<nn>_B<block>_<set>_<condition>/, --test: Data/test/<MMDDHHMMSS>/):
    run.json        the options, the set, versions
    frames.csv      every frame: times, mode (auto / manual), TOR phase, the ego car, its lane and
                    offset from the lane's middle, its controls, the wheel and pedals, TTC to the
                    stopped car
    vehicles.csv    every frame: every car around it: course id, kind, lane, planned and real dx,
                    relative speed, lights, the mirror insets it is visible in
    events.csv      appearances, turn signals, brake lights, first visible in a mirror, gaze window
                    ends, freezes, video commands
    gaze_windows.csv  each S, SD, R, F: its area of interest and gaze window
    tor_events.csv  the TOR: alert, first input, takeover, lane change, chosen lane, TTC, gaps
    sagat.json      each question: the real layout at the freeze, the answer, the scores, the video
                    questions (ndrt: the frames, the answers, the score)
    ndrt.csv        each video question: the frame, in the video or not, the answer, confidence, time
    summary.json, feedback.txt
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
import abc_follow  # noqa: E402
import abc_schedule  # noqa: E402
import abc_traffic  # noqa: E402

DATA_DIR = os.path.join(HERE, 'Data')
CONDITIONS = ('glasses', 'phone', 'hud')
CONDITION_NAMES = {'glasses': '글래스', 'phone': '휴대폰', 'hud': '앞유리 화면'}
AUTO, TOR, MANUAL, STOPPED = 'AUTO', 'TOR', 'MANUAL', 'STOPPED'  # TOR: the alert, still driving itself
AUDIO_MUTE_PORT = 5006     # carla-audio-engine fmain.py: "mute" / "unmute" (the car sound during a question)
RESUME_FIXED_FRAMES = 3     # frames with a fixed step after a freeze (a variable one would be the freeze)
HUD_OFF_GLASS = (10, 12, 16, 110)       # the switched-off HUD on the windshield: a faint dark pane
HUD_OFF_RIM = (90, 95, 105, 150)
CAMERA_ISO = 250.0                     # manual exposure of the monitor cameras: brighter than automatic
FOG = (3.0, 60.0, 1.0)                 # fog_density, fog_distance m, fog_falloff: a light haze far ahead
WEATHER = 'ClearNoon'                  # carla.WeatherParameters preset for the blocks (the server's comes back after)
GAZE_AFTER = {'S': 7.0, 'SD': 7.0}    # s after T the side mirror events' gaze windows end (before 2026-11-13;
                                      # since: S template window_rel_s, the car comes onto the side monitor)
F_GAZE = (0.0, 5.0)                     # s around T: the car ahead's gaze window
VIDEO_FEEDBACK = '수고하셨습니다. 이번 영상 시험 점수는 %s점입니다.'  # said by the experimenter after the block
# the NDRT video questions per set: the clip and per SAGAT stop the frames (ndrt_items/make_items.py)
NDRT_ITEMS = os.path.join(HERE, 'ndrt_items', 'ndrt_items.json')
NDRT_COLUMNS = ('qid', 'k', 'image', 'in_video', 'answer', 'confidence', 'ms', 'correct', 'video_t',
                'before_stop_s', 'episode_t')
BADGE = {AUTO: ('L3 자율주행 작동 중', (40, 160, 70)), TOR: ('L3 해제 요청', (220, 30, 30)),
         MANUAL: ('수동 운전', (40, 110, 200)), STOPPED: ('비상 정지', (220, 30, 30))}
WHEEL_HALF_DEG = 450.0   # degrees of the wheel at full axis travel (900 lock to lock): the logged angle
FIRST_INPUT_STEER = 2.0 / WHEEL_HALF_DEG  # axis travel from the TOR's position: the first input (2 deg) ...
FIRST_INPUT_PEDAL = 0.02                  # ... a pedal 2 %; the takeover: carla_base's STEER_TAKEOVER, PEDAL_TAKEOVER
START_HOLD_S = 1.0       # s the start speed is held: a car put down at speed has wheels that stand still,
                         # which brake it hard on the road (95 -> 17 km/h, ~6 s late for the whole block)
STOPPED_KMH = 1.0        # below this the car stands still (the block ends end_after_stop_s later)
# Lane 3 is lane 3's route shifted one lane width to the right (abc_traffic): where the real lane 4 leaves
# the loop, that line goes straight over the exit's gore, through its crash cushions (water drums), a
# light pole and a sign. Its cars hit them and were thrown into lane 2 (set C, 47.8 s: into the ego car).
# Not there in the experiment. (From a scan of the three lanes' lines for objects within 1.3 m.)
GORE_OBJECTS = ('SM_SecWaterDrums',                       # all water drums (the three gores: lane 3 s 17, 121, 2752)
                'BP_HighwayLight_multiple_2_SM_', 'BP_HighwayLight_multiple3_8_SM_',
                'BP_HighwayLight_multiple16_47_SM_', 'BP_SpeedLimit95_3959_SM_')
TOR_COLUMNS = ('participant', 'block', 'set', 'condition', 't_tor', 'safe_lane', 'unsafe_lane', 't_first_input',
               't_manual', 'first_input_type', 't_lane_change_start', 't_lane_change_end', 'chosen_lane',
               'chose_safe', 'min_ttc_obstacle_s', 'min_gap_hazard_m', 'conflict', 'collision', 'no_takeover',
               't_blinker', 'blinker_side', 'blinker_before_lane_change', 'blinker_matches_lane')


# ==============================================================================
# -- data ----------------------------------------------------------------------
# ==============================================================================


class DataLog(object):
    """The run's files (none with --no-log)."""

    COLUMNS = {
        'frames.csv': ('t_sim', 'wall_time', 'frame', 'mode', 'driving', 'tor_phase', 'ego_x', 'ego_y', 'ego_z',
                       'ego_yaw', 'speed_kmh', 'ego_lane', 'lane_offset_m', 'steer', 'throttle', 'brake',
                       'wheel_axis', 'wheel_deg', 'pedal_throttle', 'pedal_brake', 'ttc_obstacle_s', 'fps'),
        'vehicles.csv': ('t_sim', 'id', 'kind', 'event', 'lane', 'dx_plan', 'dx', 'dv_kmh', 'lights', 'in_mirror',
                         'mirror_px'),
        'events.csv': ('t_sim', 'wall_time', 'id', 'what'),
        'gaze_windows.csv': ('id', 'type', 'lane', 't', 'aoi', 'first_visible', 'first_recognizable', 'window_start',
                             'window_end'),
        'tor_events.csv': TOR_COLUMNS,
        'ndrt.csv': NDRT_COLUMNS,
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
# -- mirrors -------------------------------------------------------------------
# ==============================================================================


class MirrorVisibility(object):
    """Which mirror insets show a car: its bounding box corners projected into each mirror camera
    (carla_base's mirror views: left, right side mirror, rear-view mirror), a corner inside the
    image = visible. Nothing hides anything (other cars, the car's own body): close enough for the
    mirrors. Sizes are the car's height in the inset in pixels of 1440 px monitors (scaled from the
    window): MIN_PX it is there at all (in_mirror), RECOGNIZE_PX it is big enough to make out as a
    car (about 50 m behind in a side mirror; the gaze windows start there). Only in the driver views
    (the mirrors are there)."""

    MIN_PX = 4.0
    RECOGNIZE_PX = 30.0

    def __init__(self, world, screen_height=1440):
        self._scale = 1440.0 / screen_height  # window pixels -> 1440 px monitor pixels
        self._manager = world.camera_manager
        self._ego = world.player
        self._boxes = {}     # actor id -> its bounding box (read once: a server round trip)
        self._cameras = None  # [(name, camera, tan half fov x, tan half fov y)]
        self._for = None      # the mirror_views list they were made for (respawned with the view)

    def _setup(self):
        views = getattr(self._manager, 'mirror_views', [])
        if views is self._for:
            return
        self._for = views
        self._cameras = []
        ego = self._ego.get_transform()
        right = ego.get_right_vector()
        for rect, camera, _ in views:
            offset = camera.get_transform().location - ego.location
            side = offset.x * right.x + offset.y * right.y
            name = 'left' if side < -0.5 else 'right' if side > 0.5 else 'rear'
            tan_x = math.tan(math.radians(float(camera.attributes.get('fov', 40.0)) / 2.0))
            tan_y = tan_x * rect.height / float(rect.width)
            self._cameras.append((name, camera, tan_x, tan_y, rect.height / 2.0 / tan_y))

    def of(self, actor):
        """{'left' / 'right' / 'rear': the car's height in that inset, px at 1440p} of the insets it is in."""
        self._setup()
        if not self._cameras:
            return {}
        box = self._boxes.get(actor.id)
        if box is None:
            box = self._boxes[actor.id] = actor.bounding_box
        corners = box.get_world_vertices(actor.get_transform())
        seen = {}
        for name, camera, tan_x, tan_y, focal in self._cameras:
            inverse = camera.get_transform().get_inverse_matrix()
            us, vs = [], []
            for c in corners:
                x = inverse[0][0] * c.x + inverse[0][1] * c.y + inverse[0][2] * c.z + inverse[0][3]
                if x <= 0.5:
                    continue
                us.append((inverse[1][0] * c.x + inverse[1][1] * c.y + inverse[1][2] * c.z + inverse[1][3]) / x)
                vs.append((inverse[2][0] * c.x + inverse[2][1] * c.y + inverse[2][2] * c.z + inverse[2][3]) / x)
            if not us:
                continue
            # the box's projection overlaps the image, and is tall enough there to be seen
            if max(us) < -tan_x or min(us) > tan_x or max(vs) < -tan_y or min(vs) > tan_y:
                continue
            tall = (min(max(vs), tan_y) - max(min(vs), -tan_y)) * focal * self._scale
            if tall >= self.MIN_PX:
                seen[name] = round(tall, 1)
        return seen


# ==============================================================================
# -- SAGAT ---------------------------------------------------------------------
# ==============================================================================


# the questions on the tablet (sagat_app): was there a car ... (yes / no, each with its own confidence
# 1-5), four zones since 2026-11-13 (before: eight cells, also beside and the side lanes ahead): the
# own lane ahead and the three lanes behind, each what one mirror shows. They are asked by lane (the
# rear-view mirror also shows the side lanes behind: the left lane behind is the left question). The
# schedule keeps the beside cells empty at a question (a car there is half in the side mirror) and
# puts cars in the side lanes ahead now and then (seen, not asked).
SAGAT_ITEMS = ('behind_left', 'behind', 'behind_right',   # behind (cell_dx_m rear): left / rear-view / right mirror
               'ahead')                                    # the own lane ahead (front)
ITEM_CELLS = {'behind_left': '1_rear', 'behind': '2_rear', 'behind_right': '3_rear', 'ahead': '2_front'}
LANE_ITEMS = {1: ('behind_left', None, None), 2: ('behind', None, 'ahead'), 3: ('behind_right', None, None)}


def sagat_truth(snapshot, qt, mirrors=None):
    """The answers from the cars as they are at the freeze: snapshot [(id, lane, dx, dx 5 s before)],
    mirrors {id: {mirror: px}} (MirrorVisibility, the last frame; kept for the record). A question is
    yes when a car is in its cell (cell_dx_m: behind 15-45 m, beside -4..4 m, ahead 5-35 m; the
    schedule keeps every car either in a cell or beyond gap_far_m at a question). A car that is in a
    gap anyway (its course off by a few metres) makes the questions on both sides of that gap
    ambiguous unless a car is clearly in their cell: they are not scored. So does a car beside in lane
    1 or 3 (the schedule keeps none there): it is half in that side mirror."""
    now = [(lane, dx) for _, lane, dx, _ in snapshot]
    history = {k: before for k, (_, _, _, before) in enumerate(snapshot) if before is not None}
    cells, approach, safe = abc_schedule.layout(now, history, qt)
    items = {key: bool(cells.get(cell)) for key, cell in ITEM_CELLS.items()}
    c = qt['cell_dx_m']
    ambiguous = set()
    for _, lane, dx, _ in snapshot:
        if lane not in LANE_ITEMS:
            continue
        behind, beside, ahead = LANE_ITEMS[lane]
        zone = abc_schedule.zone_of(lane, dx, qt)
        if zone in ('1_side', '3_side'):
            ambiguous.update(k for k in (behind,) if not items[k])
        if zone != 'gap':
            continue
        if dx >= c['front'][1]:
            near = (ahead,)
        elif dx <= c['rear'][0]:
            near = (behind,)
        elif lane == 2:
            near = (behind, ahead)
        elif dx < c['side'][0]:
            near = (behind, beside)
        else:
            near = (beside, ahead)
        ambiguous.update(k for k in near if k and not items[k])
    mirrors = mirrors or {}
    return {'items': items, 'ambiguous': sorted(ambiguous), 'cells': cells, 'approach': approach, 'safe': safe,
            'cars': [{'id': cid, 'lane': lane, 'dx': round(dx, 2), 'dx_5s_before': None if b is None else round(b, 2),
                      'zone': abc_schedule.zone_of(lane, dx, qt) if lane in LANE_ITEMS else 'lane 0',
                      'mirrors': mirrors.get(cid, {})}
                     for cid, lane, dx, b in snapshot]}


def load_ndrt(set_name):
    """The set's NDRT video questions ({'clip': ..., 'stops': {qid: {'items': [...]}}}), None if none."""
    try:
        with open(NDRT_ITEMS, encoding='utf-8') as handle:
            return json.load(handle).get(set_name)
    except (OSError, ValueError):
        return None


def ndrt_score(stop, answer):
    """The video questions of one stop: correct, hits (in the video, said so) and false alarms."""
    items = stop['items']
    if answer is None:
        return {'answered': False, 'asked': len(items), 'correct': 0}
    given = {a.get('image'): a for a in answer.get('answers') or []}
    said = [(i['shown'], given[i['image']].get('shown')) for i in items if i['image'] in given]
    return {'answered': True, 'asked': len(items), 'answered_items': len(said),
            'correct': sum(1 for truth, a in said if a == truth),
            'hits': sum(1 for truth, a in said if truth and a is True), 'n_in_video': sum(1 for i in items if i['shown']),
            'false_alarms': sum(1 for truth, a in said if not truth and a is True),
            'n_not_in_video': sum(1 for i in items if not i['shown'])}


def sagat_score(truth, answer):
    """Per question: correct or not (None: not answered, or ambiguous), its confidence; score = the
    share correct of the scored ones (also by group)."""
    if answer is None:
        return {'answered': False}
    given = answer.get('items') or {}
    correct, confidence = {}, {}
    for key in SAGAT_ITEMS:
        a = given.get(key) or {}
        unscored = a.get('present') is None or key in truth.get('ambiguous', ())
        correct[key] = None if unscored else bool(a['present']) == truth['items'][key]
        confidence[key] = a.get('confidence')

    def share(keys):
        marks = [correct[k] for k in keys if correct[k] is not None]
        return round(sum(marks) / float(len(marks)), 3) if marks else None
    return {'answered': True, 'correct': correct, 'confidence': confidence,
            'behind': share(('behind_left', 'behind', 'behind_right')), 'ahead': share(('ahead',)),
            'score': share(SAGAT_ITEMS),
            'unscored': [k for k in SAGAT_ITEMS if correct[k] is None]}


# ==============================================================================
# -- screen --------------------------------------------------------------------
# ==============================================================================


class Overlay(object):
    """The instrument cluster of carla_base (the gauges tablet), the L3 badge above it, the TOR
    alert (blinking above the cluster; in the HUD condition in the HUD area too), and the black
    screens of a question and of the end.

    Layout at the bottom of the middle monitor: the cluster in the middle, the HUD's video area at
    the monitor's right edge (where the glasses' display appears in the view), a plain rectangle
    HUD_DEG wide in the video's shape (HUD_ASPECT, no windshield perspective), its bottom just above the
    dashboard (the cluster's top). hud_rect is where the HUD condition's video goes (--hud-preview
    draws its outline)."""

    _draw_cluster = base.TakeoverExperiment._draw_cluster
    HUD_DEG = 10.0    # degrees across: 25 % wider than the glasses' display (8 degrees), which looked bigger
    HUD_ASPECT = 9.0 / 16.0   # height / width: the video's own shape (16:9), no empty band above or below
    # The video as light added to the view (as a HUD's projection and the glasses' display: black is
    # see-through, the dark parts let the road show), at this share of its brightness: lower, more see-through
    HUD_VIDEO_GAIN = 0.6
    HUD_RIGHT_DEG = 9.5   # the HUD's centre, degrees right of straight ahead: clear of the badge and the TOR alert above the cluster
    HUD_ABOVE_PX = 12     # px between the HUD's bottom and the cluster's top (the dashboard)
    HUD_EDGE_PX = 8       # px between the HUD and the middle monitor's right edge
    HUD_NEAR_M = 0.75     # m from the driver's eyes to the HUD's bottom edge on the windshield
    WINDSHIELD_RAKE_DEG = 62.0   # the windshield's lean back from vertical (28 degrees above horizontal)

    def _cluster_face(self, size):
        face = base.TakeoverExperiment._cluster_face(size)
        width, height = size
        panel_w = face['face'].get_width()
        hud = self.hud_size(size)
        # the cluster centred on the monitor, in front of the driver: wide enough to hide the steering wheel
        left = (width - panel_w) // 2
        face['origin'] = (left, face['origin'][1])
        # the HUD at the middle monitor's right edge (where the glasses' display is seen), as wide as
        # HUD_DEG and as high as the video (HUD_ASPECT), its bottom just above the dashboard (the cluster's top)
        bottom = face['origin'][1] - self.HUD_ABOVE_PX
        tall = int(round(hud * self.HUD_ASPECT))
        self.hud_rect = pygame.Rect(width - self.HUD_EDGE_PX - hud, bottom - tall, hud, tall)
        r = self.hud_rect
        self.hud_poly = [(r.left, r.bottom), (r.right, r.bottom), (r.right, r.top), (r.left, r.top)]
        return face

    def _hud_polygon(self, width, height, fov, bottom):
        """The HUD's corners in monitor pixels (bottom left, bottom right, top right, top left): a square
        HUD_DEG wide lying on the windshield, which leans back (WINDSHIELD_RAKE_DEG from vertical), so
        its top is farther away: a trapezoid, narrower and foreshortened at the top. Its bottom edge is
        HUD_NEAR_M ahead of the driver's eyes at the pixel row `bottom`, its centre HUD_RIGHT_DEG right."""
        focal = width / 2.0 / math.tan(math.radians(fov / 2.0))
        z0 = self.HUD_NEAR_M
        y0 = -z0 * (bottom - height / 2.0) / focal             # m below the eyes (the camera's own pitch left out)
        side = 2.0 * z0 * math.tan(math.radians(self.HUD_DEG / 2.0))  # m: HUD_DEG across at its bottom
        x_mid = z0 * math.tan(math.radians(self.HUD_RIGHT_DEG))
        rake = math.radians(self.WINDSHIELD_RAKE_DEG)
        z1, y1 = z0 + side * math.sin(rake), y0 + side * math.cos(rake)  # its top edge, up the glass

        def pixel(x, y, z):
            return int(round(width / 2.0 + focal * x / z)), int(round(height / 2.0 - focal * y / z))
        return [pixel(x_mid - side / 2.0, y0, z0), pixel(x_mid + side / 2.0, y0, z0),
                pixel(x_mid + side / 2.0, y1, z1), pixel(x_mid - side / 2.0, y1, z1)]

    def hud_size(self, size):
        """px across HUD_DEG at the middle monitor's field of view."""
        fov = self._world.camera_manager.screen_fov if hasattr(self._world.camera_manager, 'screen_fov') else 43.0
        return int(size[0] * math.tan(math.radians(self.HUD_DEG / 2.0)) / math.tan(math.radians(fov / 2.0)))

    def __init__(self, world, hud_preview=False, condition=None):
        self._world = world
        self._condition = condition
        self.hud_rect = None
        self.hud_poly = None   # the HUD's trapezoid on the windshield (monitor pixels of the middle monitor)
        self._hud_preview = hud_preview
        self.hud_video = None   # the HUD condition's video player (hud_video.HudVideo)
        self._phone_cluster = None
        self._cluster = None
        self._needles = [0.0, 0.0]
        self._pedal = 0.0
        self._speed_kmh = 0.0
        self._lights = 0  # the turn signals the driver switched on (the cluster's arrows)
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

    def render(self, display, mode, speed_kmh, pedal, alert_since=None):
        """alert_since: time.monotonic() of the TOR alert while it is on (it blinks), else None."""
        self._speed_kmh, self._pedal = speed_kmh, pedal
        self._draw_cluster(display)
        if self._world.camera_manager.transform_index == 0 and self.hud_rect is not None:
            self._draw_hud_off(display)
            if self.hud_video is not None:
                self._draw_hud_video(display)
        if alert_since is not None and self._world.camera_manager.transform_index == 0 and self._cluster is not None:
            self._draw_alert(display, alert_since)
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

    def _draw_hud_off(self, display):
        """The HUD's display, switched off, in every condition (so the cockpit looks the same in all
        three; in the HUD condition the alert and the video are drawn over it)."""
        x0, _, _ = self.middle()
        rect = self.hud_rect.move(x0, 0)
        if getattr(self, '_hud_off', None) is None or self._hud_off.get_size() != rect.size:
            panel = pygame.Surface(rect.size, pygame.SRCALPHA)
            corners = [(x - self.hud_rect.x, y - self.hud_rect.y) for x, y in self.hud_poly]
            pygame.draw.polygon(panel, HUD_OFF_GLASS, corners)
            pygame.draw.polygon(panel, HUD_OFF_RIM, corners, width=2)
            self._hud_off = panel
        display.blit(self._hud_off, rect)

    def _draw_hud_video(self, display):
        """The HUD condition's video (hud_video.HudVideo) filling the HUD (the HUD has the video's shape),
        added to the view at HUD_VIDEO_GAIN of its brightness (see-through)."""
        shown = self.hud_video.surface(self.hud_rect.width, self.hud_rect.height)
        if shown is None:
            return
        frame, (dx, dy) = shown
        if getattr(self, '_hud_frame', (None,))[0] is not frame:
            light = frame.copy()
            g = int(round(255 * self.HUD_VIDEO_GAIN))
            light.fill((g, g, g), special_flags=pygame.BLEND_RGB_MULT)
            self._hud_frame = (frame, light)
        x0, _, _ = self.middle()
        display.blit(self._hud_frame[1], (self.hud_rect.x + x0 + dx, self.hud_rect.y + dy),
                     special_flags=pygame.BLEND_RGB_ADD)

    def _draw_alert(self, display, since):
        if int((time.monotonic() - since) * 2 * base.TOR_BLINK_HZ) % 2:
            return  # the off half of the blink
        x0, width, height = self.middle()
        text = self.big.render(base.TOR_MESSAGE, True, (255, 255, 255))
        middle = x0 + self._cluster['origin'][0] + self._cluster['face'].get_width() // 2
        box = text.get_rect(midbottom=(middle, self._cluster['origin'][1] - 60)).inflate(60, 28)
        pygame.draw.rect(display, (220, 30, 30), box, border_radius=10)
        display.blit(text, text.get_rect(center=box.center))
        if self._condition == 'hud' and self.hud_rect is not None:  # the NDRT screen: the same text
            rect = self.hud_rect.move(x0, 0)
            pygame.draw.polygon(display, (220, 30, 30), [(x + x0, y) for x, y in self.hud_poly])
            for k, line in enumerate(('지금 직접', '운전하세요')):
                line_text = self.big.render(line, True, (255, 255, 255))
                display.blit(line_text, line_text.get_rect(center=(rect.centerx, rect.centery + (k - 0.5) * 56)))

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
        self.questions = []
        self.ndrt = None        # the set's NDRT video questions (load_ndrt), None: none asked
        self.first_visible = {}  # event id -> first time its car was in its mirror (MIN_PX)
        self.first_recognizable = {}  # ... big enough to make out (RECOGNIZE_PX): its gaze window starts
        self.mode = AUTO
        self.frozen = False
        self.exit_times = {}    # R id -> time it fell back past 10 m (measured)
        self._r_release = {e['id']: e['t'] + self.config['templates']['R']['release_rel_s']
                           for e in self.schedule['events'] if e['type'] == 'R'}
        self._marks_done = set()
        self.g2 = None
        self.media = []         # NDRT video players: pause() / resume() at the questions, alert() at the TOR
        self.tor = None         # TorRun (the schedule's TOR, once the scene is set up)

    # -- marks ---------------------------------------------------------------------------------

    def mark(self, t, what, eid='-', **fields):
        self.log.event(t, what, eid)
        if self.g2 is not None:
            self.g2.mark(what.split(' ')[0], id=eid, t_sim=round(t, 3), **fields)

    def timed_marks(self, t):
        """The schedule's moments (event T, gaze window ends) as they pass."""
        for e in self.schedule['events']:
            if e['type'] in ('S', 'SD', 'R', 'F') and e['id'] not in self._marks_done and t >= e['t']:
                self._marks_done.add(e['id'])
                signal = any(c['id'] == e['id'] and c.get('lights') for c in self.schedule['cars'])
                what = {'S': ('alongside (overtaking, then a lane change)' if 'lane_change' in e else
                              'alongside (overtaking, no lane change)') if 'gone_t' in e else
                        'onset (turn signal on)' if signal else 'onset (no signal)', 'SD': 'onset (no signal)',
                        'R': 'onset (closer than 10 m)', 'F': 'onset (brake light)'}[e['type']]
                self.mark(t, what, e['id'], type=e['type'])
            if e['type'] in ('S', 'SD', 'R', 'F') and e['id'] + '/end' not in self._marks_done:
                end = self.gaze_window(e)[1]
                if end is not None and t >= end:
                    self._marks_done.add(e['id'] + '/end')
                    self.mark(t, 'gaze window end', e['id'])

    @staticmethod
    def aoi(e):
        """The area of interest of an event."""
        if e['type'] in ('S', 'SD'):
            return 'left_mirror' if e['lane'] == 1 else 'right_mirror'
        return 'rear_mirror' if e['type'] == 'R' else 'lead_car'

    def gaze_window(self, e):
        """[start, end] of an event's gaze window (None where not known yet)."""
        if e['type'] == 'F':
            return [e['t'] + F_GAZE[0], e['t'] + F_GAZE[1]]
        start = self.first_recognizable.get(e['id'])
        if e['type'] == 'R':
            exit_t = self.exit_times.get(e['id'], e.get('t_exit'))
            return [start, round(exit_t + self.config['templates']['R']['window_after_exit_s'], 3)]
        if 'gone_t' in e:   # the S that overtakes (2026-11-13), with or without a lane change
            return [start, e['t'] + self.config['templates']['S']['window_rel_s'][1]]
        return [start, e['t'] + GAZE_AFTER[e['type']]]

    def track_visible(self, t, mirrors):
        """mirrors: {course id: {mirror: px}} this frame. The first frame an event's car is big enough
        to make out in its own mirror starts its gaze window."""
        for e in self.schedule['events']:
            if e['type'] not in ('S', 'SD', 'R') or e['id'] in self.first_recognizable:
                continue
            want = self.aoi(e).split('_')[0]
            px = mirrors.get(e['id'], {}).get(want)
            if px is None:
                continue
            if e['id'] not in self.first_visible:
                self.first_visible[e['id']] = round(t, 3)
                self.mark(t, 'first in the %s mirror (%.0f px)' % (want, px), e['id'])
            if px >= MirrorVisibility.RECOGNIZE_PX:
                self.first_recognizable[e['id']] = round(t, 3)
                self.mark(t, 'big enough in the %s mirror, %.0f px (gaze window start)' % (want, px), e['id'])

    def track_rear(self, t, state):
        """R: the time it really falls back past 10 m bumper to bumper (onset_dx_m), for its window."""
        onset = self.config['templates']['R']['onset_dx_m']
        for rid, release in self._r_release.items():
            if rid in self.exit_times or rid not in state or t < release:
                continue
            if state[rid][1] < onset:
                self.exit_times[rid] = t
                self.mark(t, 'falls back past 10 m', rid)

    # -- video -------------------------------------------------------------------------------

    def media_results(self, t):
        """What the video players did (their own reports), into the event log."""
        for player in self.media:
            while not player.results.empty():
                wall, action, delivered, state = player.results.get()
                what = 'video %s: %s' % (action, 'not sent' if delivered is None else
                                         'no player connected' if not delivered else
                                         '%s at %s s%s%s%s' % (player.device, state.get('t'), ', paused' if state.get('paused') else '',
                                                                    ', covered' if state.get('frozen') else '',
                                                                    # the video (gaze_video.py shows it on the display)
                                                                    ' [%s]' % state['title'] if state.get('title') else ''))
                self.log.event(t, what, state.get('id') or '-')

    # -- the end -------------------------------------------------------------------------------

    def finish(self, t_end, aborted):
        windows = []
        for e in self.schedule['events']:
            if e['type'] not in ('S', 'SD', 'R', 'F') or e['t'] > t_end:
                continue
            start, end = self.gaze_window(e)
            row = {'id': e['id'], 'type': e['type'], 'lane': e.get('lane', 2), 't': e['t'], 'aoi': self.aoi(e),
                   'first_visible': self.first_visible.get(e['id']),
                   'first_recognizable': self.first_recognizable.get(e['id']), 'window_start': start, 'window_end': end}
            windows.append(row)
            self.log.row('gaze_windows.csv', [('' if row[k] is None else row[k]) for k in
                                              ('id', 'type', 'lane', 't', 'aoi', 'first_visible', 'first_recognizable',
                                               'window_start', 'window_end')])
        answered = [q['score'] for q in self.questions if q['score'].get('answered')]
        sagat = round(100.0 * sum(s['score'] or 0 for s in answered) / len(answered)) if answered else None
        missing = [w['id'] for w in windows if w['type'] != 'F' and w['first_recognizable'] is None]
        asked = [q['ndrt']['score'] for q in self.questions if q.get('ndrt')]
        n_items = sum(a['asked'] for a in asked)
        video = round(100.0 * sum(a['correct'] for a in asked) / n_items) if n_items else None
        feedback = VIDEO_FEEDBACK % ('○○' if video is None else video)
        summary = {
            'set': self.args.set, 'block': self.args.block, 'condition': self.args.condition,
            'participant': self.args.participant, 'test': self.args.test, 'aborted': aborted, 't_end': round(t_end, 2),
            'gaze_windows': windows, 'never_visible_in_their_mirror': missing,
            'tor': self.tor.row(self) if self.tor is not None and self.tor.t_alert is not None else None,
            'sagat': {'score_percent': sagat, 'questions': [{'id': q['id'], **q['score']} for q in self.questions]},
            'ndrt': {'score_percent': video, 'clip': self.ndrt['clip'] if self.ndrt else None,
                     'questions': [{'id': q['id'], **q['ndrt']['score']} for q in self.questions if q.get('ndrt')]},
            'feedback': feedback}
        self.log.json('summary.json', summary)
        if summary['tor']:
            self.log.row('tor_events.csv', [('' if summary['tor'][k] is None else summary['tor'][k]) for k in TOR_COLUMNS])
        self.log.json('sagat.json', self.questions)
        self.log.text('feedback.txt', feedback + '\n(블록 뒤 실험자가 읽음: 영상 질문 정답 비율. 주변 차량 질문 점수는 알리지 않음)\n')
        print()
        print('=' * 78)
        print('Block over (%s). SAGAT %s (not told to the participant). Gaze windows: %d events%s' % (
            'aborted' if aborted else 'complete', '-' if sagat is None else '%d %%' % sagat, len(windows),
            '; never in their mirror: ' + ', '.join(missing) if missing else ''))
        if summary['tor']:
            tor = summary['tor']
            print('TOR at %.1f s: %s, first input %s, lane change to %s (%s), min TTC %s s, conflict %s, collision %s' % (
                tor['t_tor'], 'no takeover (emergency stop)' if tor['no_takeover'] else
                'takeover %.2f s after it' % (tor['t_manual'] - tor['t_tor']) if tor['t_manual'] is not None else
                'no takeover', tor['first_input_type'] or '-', tor['chosen_lane'] or '-',
                'safe' if tor['chose_safe'] else '-' if tor['chose_safe'] is None else 'not the safe lane', tor['min_ttc_obstacle_s'], tor['conflict'],
                tor['collision'] or 'none'))
        print('Video questions: %s. Say: "%s"' % ('-' if video is None else '%d %% of %d' % (video, n_items), feedback))
        if self.log.dir:
            print('  data: %s' % self.log.dir)
        print('=' * 78)


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
                        help='checking: start the block this many s in (events before it are skipped), the car '
                             'where it would be then (abc_ego.py profile)')
    parser.add_argument('--duration', type=float, default=None, help='checking: quit after this many s of the block')
    parser.add_argument('--feedback-seconds', type=float, default=600.0,
                        help='the end screen stays this long at most (a key closes it)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('-p', '--port', type=int, default=2000)
    # three 1920x1080 monitors: at 2560x1440 the GPU (RTX 3070 Ti) draws 28 fps on average with a stall every
    # 0.2 s; at 1080p, capped at 34 fps, 33-35 fps with none (block A, 40 cars). The monitors are set to
    # 1920x1080 in Windows (they scale it up themselves)
    parser.add_argument('--res', default='5760x1080')
    parser.add_argument('--window-pos', default='-1920,0')
    parser.add_argument('--screens', type=int, default=3)
    parser.add_argument('--screen-fov', type=float, default=43.0)
    parser.add_argument('--no-mirrors', action='store_true')
    parser.add_argument('--render-scale', type=float, default=1.0)
    parser.add_argument('--fps', type=float, default=34.0, help='frame cap: under what the GPU keeps up with (even frames)')
    parser.add_argument('--filter', default=base.DEFAULT_VEHICLE)
    parser.add_argument('--view', choices=['driver', 'windshield', 'chase'], default='driver')
    parser.add_argument('--gamma', type=float, default=2.2)
    parser.add_argument('--trees', action='store_true')
    parser.add_argument('--camera-iso', type=float, default=CAMERA_ISO,
                        help='manual exposure of the monitor cameras (the automatic one keeps the view dim)')
    parser.add_argument('--fog', type=float, nargs=3, default=FOG, metavar=('DENSITY', 'DISTANCE', 'FALLOFF'),
                        help='carla.WeatherParameters fog_density (0-100), fog_distance (m), fog_falloff')
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
    parser.add_argument('--sim-driver', choices=('safe', 'unsafe', 'brake'),
                        help='checking the TOR: a scripted driver takes over 1 s after the alert and changes '
                             'to the safe or the unsafe lane, or brakes')
    parser.add_argument('--snap', type=float, nargs='+', metavar='T',
                        help='checking: save the screen and each mirror inset (x3) at these block times, to <data>/snaps/')
    parser.add_argument('--hud-preview', action='store_true',
                        help="the outline of the HUD's video area right of the cluster (for setting up)")
    parser.add_argument('--g2', metavar='HOST', help='Tobii Pro Glasses 2 recording unit: event markers')
    parser.add_argument('--g2-record', action='store_true', help='with --g2: start and stop a recording too')
    parser.add_argument('--g2-no-stream', action='store_true',
                        help='with --g2: do not save the live gaze and scene video in the data folder')
    parser.add_argument('--no-post', action='store_true',
                        help='with --g2: no postprocess.py at the end (mirror glances, SAGAT gaze, gaze_video.mp4)')
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
    world = client = sim_world = ticker = traffic = sagat = audio = driver_input = sound = None
    async_settings = None
    server_weather = None
    collision_sensor = None
    green_lights = []
    t = 0.0
    aborted = True
    try:
        from sagat_server import SagatServer
        sagat = SagatServer(args.sagat_port)
        if args.g2:
            from g2_link import G2Link
            block.g2 = G2Link(args.g2, os.path.basename(block.log.dir or 'abc'), record=args.g2_record,
                              stream_dir=None if args.g2_no_stream else block.log.dir)
            # the glasses display in the Glasses 2 gaze (g2_calibrate.py) and the gaze's accuracy (g2_validate.py)
            # and the bezel markers in the window's pixels (mirror_register.py), for mirror_aoi.py
            for name in ('g2_display.json', 'g2_validation.json', os.path.join('mirror_markers', 'bezel_screen.json')):
                path = os.path.join(HERE, name)
                if block.log.dir and os.path.isfile(path):
                    import shutil
                    shutil.copy(path, os.path.join(block.log.dir, os.path.basename(name)))
        # the NDRT video questions after each SAGAT stop, about the set's clip: it is the video played
        block.ndrt = load_ndrt(args.set)
        if block.ndrt is None:
            logging.warning('No NDRT video questions for set %s (%s): only the SAGAT questions', args.set, NDRT_ITEMS)
        elif args.video_file is None:
            args.video_file = block.ndrt['clip']
            logging.info("NDRT video: %s (the set's clip, ndrt_items.json)", args.video_file)
        elif os.path.basename(args.video_file) != block.ndrt['clip']:
            logging.warning("--video-file %s is not set %s's clip %s: no video questions", args.video_file, args.set,
                            block.ndrt['clip'])
            block.ndrt = None
        if args.condition == 'hud':
            # the HUD's video: played here, in the HUD area (no glasses / phone app: the glasses app
            # would do the commands of every condition)
            from hud_video import HudVideo
            block.media.append(HudVideo(args.video_file, args.video_start, resume=block.ndrt is None))
        elif args.video:
            from video_link import VideoLink
            block.media.append(VideoLink(args.video, args.video_file, args.video_start, args.condition,
                                         resume=block.ndrt is None))
            if args.condition == 'glasses' and block.log.dir:
                # the app's version: where on the display it shows the video (v14 on: at the top;
                # postprocess.display_outline)
                with open(os.path.join(block.log.dir, 'glasses_app.json'), 'w', encoding='utf-8') as handle:
                    json.dump({'v': block.media[-1].app_version()}, handle)
        driver_input = base.WheelInput(args) if args.input == 'wheel' else base.KeyboardInput()
        client = base.connect_server(args.host, args.port)
        sim_world = client.get_world()
        if not sim_world.get_map().name.endswith(base.MAP_NAME):
            logging.info('Loading %s...', base.MAP_NAME)
            sim_world = client.load_world(base.MAP_NAME)
        server_weather = sim_world.get_weather()
        weather = getattr(carla.WeatherParameters, WEATHER)
        # a light haze: the far cars (they appear and leave spawn_ahead_dx_m ahead) fade in, not pop up
        weather.fog_density, weather.fog_distance, weather.fog_falloff = args.fog
        sim_world.set_weather(weather)
        trees = {tree.id for tree in sim_world.get_environment_objects(carla.CityObjectLabel.Vegetation)}
        sim_world.enable_environment_objects(trees, args.trees)
        gore = {o.id for o in sim_world.get_environment_objects(carla.CityObjectLabel.Any)
                if o.name.startswith(GORE_OBJECTS)}
        sim_world.enable_environment_objects(gore, False)
        traffic_manager = client.get_trafficmanager(base._free_port())  # pylint: disable=protected-access
        async_settings = sim_world.get_settings()
        async_settings.synchronous_mode = False
        async_settings.fixed_delta_seconds = None
        settings = sim_world.get_settings()
        settings.synchronous_mode = True
        # a fixed step, 1 / --fps (the frame cap the GPU keeps up with: real time). Not a variable one
        # (each step as long as the frame): when the server is held up, its step jumps (0.8 .. 2.4 s
        # in one frame) while the physics moves at most 0.1 s, so the ego car fell behind its
        # schedule (10 s in a lap) and the predicted curves were off
        settings.fixed_delta_seconds = 1.0 / args.fps
        sim_world.apply_settings(settings)
        traffic_manager.set_synchronous_mode(True)
        ticker = base.SimTicker(sim_world)
        audio = base.AudioEngine(not args.no_audio_engine)
        sound = base.AlertSound(not args.no_sound)  # the TOR's beeps (carla_base, as in the takeover experiment)
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
        start_m = schedule.get('ego_start_m', 0.0)
        speed = block.config['ego']['speed_kmh']
        # the speed of the profile there (in a curve's slow part not 95 km/h, which the prediction of the
        # curves would not match); --start-at (checking): where the car would be by then, at its speed there
        import abc_ego
        if os.path.isfile(abc_ego.PROFILE_FILE):
            start_m, v = abc_ego.position(abc_ego.load_profile(), start_m, args.start_at)
            speed = v * 3.6
        start_throttle = None  # the autonomous driving's throttle there in the profile run
        if os.path.isfile(abc_ego.PROFILE_FILE):
            profile = abc_ego.load_profile()
            if 'throttle' in profile:
                start_throttle = profile['throttle'][int((start_m % profile['length_m']) / profile['bin_m'])
                                                     % len(profile['throttle'])]
        start_index = traffic.ego_route.index_at(start_m)
        traffic.start(start_index)
        logging.info('Start %.0f m along the loop (route point %d), %.0f km/h', start_m, start_index, speed)
        start = route[start_index].transform
        start.location.z += 0.5
        world.player.set_transform(start)
        sim_world.tick()
        forward = start.get_forward_vector()
        world.player.set_target_velocity(carla.Vector3D(forward.x * speed / 3.6, forward.y * speed / 3.6, 0.0))
        sim_world.tick()
        planner = base.GlobalRoutePlanner(carla_map, base.ROUTE_RESOLUTION)
        follower = base.LoopFollower(world.player, route, block.config['ego']['speed_kmh'], carla_map, planner)
        follower._agent.ignore_vehicles(True)  # pylint: disable=protected-access  (it reacts to nothing)
        sim_clock = [sim_world.get_snapshot().timestamp.elapsed_seconds]
        follower.clock = lambda: sim_clock[0]  # its speed changes with the simulation's time: the same every run
        overlay = Overlay(world, hud_preview=args.hud_preview, condition=args.condition)
        overlay.hud_video = next((p for p in block.media if getattr(p, 'device', '') == 'hud'), None)
        tor_event = next((e for e in schedule['events'] if e['type'] == 'TOR'), None)
        if tor_event is not None:
            scene = abc_traffic.TorScene(traffic, tor_event, block.config['templates']['TOR'],
                                         block.config['event_vehicle'])
            block.tor = TorRun(block, tor_event, block.config['templates']['TOR'], scene, world.player)
        mirror_view = MirrorVisibility(world, args.height)
        save_mirrors(world.camera_manager, block.log.dir)
        collision_sensor, collisions = collision_log(sim_world, world.player)
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
        holding = True  # the start speed (START_HOLD_S)
        blinker = None  # the turn signal on: 'left', 'right' or None
        mirrors = {}    # the last frame's mirror visibility of each car (MirrorVisibility): SAGAT truth
        snaps = sorted(args.snap or [])
        # the Fs' brakes [(brake, its lead car back at its place, lead car id)] (abc_schedule f_spans)
        f_spans = sorted((a, b, c['id']) for c in schedule['cars'] for a, b in c.get('f_spans', [])
                         if a >= args.start_at)
        follow = None   # abc_follow.Follow while the ego car brakes for an F and makes the distance up
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
                if not fixed_frames:  # back to the block's own steps
                    settings.fixed_delta_seconds = 1.0 / args.fps
                    sim_world.apply_settings(settings)
            keys = pygame.key.get_pressed()
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYUP and event.key == pygame.K_ESCAPE):
                    return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                    base.next_view(world)
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
                    world.hud.toggle_info()
                # the turn signals: the paddles behind the wheel (wheel_buttons.json), Z / X on the keyboard;
                # again on the same side switches it off
                paddle = driver_input.paddle_event(event) if hasattr(driver_input, 'paddle_event') else None
                if paddle:  # held / let go: the mirror check's marks (mirror_check.py)
                    block.mark(t, 'paddle %s %s' % paddle)
                side = driver_input.light_event(event) if hasattr(driver_input, 'light_event') else None
                if side in ('left', 'right'):
                    blinker = None if blinker == side else side
                    block.mark(t, 'turn signal %s' % (blinker or 'off'))
                    if blinker and block.tor is not None:
                        block.tor.signal(t, blinker)
            ended = block.tor is not None and block.tor.over(t)  # 5 s after the car stands still
            if t >= schedule['block_end_s'] or ended or (args.duration and t - args.start_at >= args.duration):
                aborted = t < schedule['block_end_s'] and not ended
                break

            # a question: everything stops until it is answered
            if questions and t >= questions[0]['t']:
                q = questions.pop(0)
                q_number += 1
                if not ask_question(block, q, q_number, t, traffic, sagat, overlay, display, clock, mirrors):
                    return
                settings.fixed_delta_seconds = 1.0 / args.fps  # the next step is one frame, not the freeze
                sim_world.apply_settings(settings)
                fixed_frames = RESUME_FIXED_FRAMES
                ticker.start()
                continue

            # an F: the ego car brakes after the lead car (abc_follow), the other cars keep their speeds
            if follow is None and f_spans and t >= f_spans[0][0] and block.mode == AUTO:
                t_brake, t_back, f_car = f_spans.pop(0)
                follow = abc_follow.Follow(block.config['templates']['F'], t_brake, t_back)
                follow.car, follow.closest, follow.lowest = f_car, None, None
                block.mark(t, 'F follow start', f_car)
            v_nominal = follower._wanted_speed() / 3.6  # pylint: disable=protected-access
            state = traffic.tick(t, world.player, dt, lag=follow.lag if follow else 0.0,
                                 ref_speed=v_nominal if follow else None)
            for t_log, cid, what in traffic.log:
                block.log.event(t_log, what, cid)
            del traffic.log[:]
            block.timed_marks(t)
            block.track_rear(t, state)
            mirrors = {cid: mirror_view.of(traffic.cars[cid]['actor']) for cid in state}
            block.track_visible(t, mirrors)
            block.media_results(t)

            # the ego car
            transform = world.player.get_transform()
            velocity = world.player.get_velocity()
            speed_kmh = velocity.length() * 3.6
            forward = transform.get_forward_vector()
            ego_speed = velocity.x * forward.x + velocity.y * forward.y
            ego_s = traffic.ego_s(transform)
            lateral = lateral_offset(traffic.ego_route, ego_s, transform.location)
            wheel = driver_input.peek(keys)  # (steer axis, throttle, brake) the driver gives
            sim = args.sim_driver and block.tor is not None and block.tor.t_alert is not None                 and t >= block.tor.t_alert + 1.0
            if sim:  # checking: its input
                wheel = (0.0, 0.0, 0.5) if args.sim_driver == 'brake' else (0.02, 0.0, 0.0)
            if block.tor is not None:
                block.tor.tick(t, block, transform, ego_s, ego_speed, lateral, wheel, dt, sound, collisions)
            if block.mode in (AUTO, TOR):
                control = follower.run_step()  # it drives itself until the takeover
                pedal = control.throttle
                if follow is not None:
                    lead = state.get(follow.car)
                    gap = lead[1] if lead and lead[1] > 0 else None
                    v_lead = ego_speed + lead[2] / 3.6 if gap is not None else None
                    wanted = follow.step(t, dt, v_nominal, ego_speed, gap, v_lead)
                    if gap is not None:
                        follow.closest = gap if follow.closest is None else min(follow.closest, gap)
                    if wanted is not None and ego_speed > 0.3:
                        follow.lowest = ego_speed if follow.lowest is None else min(follow.lowest, ego_speed)
                        if wanted < ego_speed - 0.05:   # braking: no throttle, the brake light on
                            control = carla.VehicleControl(throttle=0.0, steer=control.steer,
                                                           brake=min(1.0, (ego_speed - wanted) / max(dt, 1e-3) / 8.0))
                            pedal = 0.0
                        world.player.set_target_velocity(carla.Vector3D(velocity.x * wanted / ego_speed,
                                                                        velocity.y * wanted / ego_speed, velocity.z))
                    if follow.done:
                        block.mark(t, 'F follow end: lowest %.0f km/h, closest %.1f m, %.1f m behind at most' % (
                            (follow.lowest or 0.0) * 3.6, follow.closest or -1.0, follow.most), follow.car)
                        follow = None
                        follower.engage()   # from the speed it has now (its controller was overridden)
            elif follow is not None:   # the TOR or a takeover during an F: the driver drives
                follow = None
            elif block.mode == STOPPED:
                # full brake, and the speed brought down so that the car stops 3 m before the stopped
                # car: from TTC 1.5 s at highway speed the brakes alone would not make it
                control = carla.VehicleControl(throttle=0.0, brake=1.0)
                pedal = 0.0
                gap = block.tor.obstacle_gap(ego_s)
                if ego_speed > 0.3 and gap is not None:
                    decel = max(ego_speed * ego_speed / (2.0 * max(gap - 3.0, 0.5)), 6.0)
                    slower = max(ego_speed - decel * max(dt, 1.0 / args.fps), 0.0)
                    world.player.set_target_velocity(carla.Vector3D(velocity.x * slower / ego_speed,
                                                                    velocity.y * slower / ego_speed, velocity.z))
            elif sim:  # MANUAL, checking: the scripted driver
                control = sim_driver(args.sim_driver, block.tor, traffic.ego_route, ego_s, transform, lateral,
                                     ego_speed, follower._wanted_speed())  # pylint: disable=protected-access
                pedal = control.throttle
            else:  # MANUAL: the driver
                driver_input.update(control, keys, clock.get_time(), speed_kmh, forward.z)
                pedal = wheel[1]
            if holding:
                if t - args.start_at < START_HOLD_S:  # the wheels turn up to the start speed
                    world.player.set_target_velocity(carla.Vector3D(forward.x * speed / 3.6, forward.y * speed / 3.6,
                                                                    velocity.z))
                else:
                    holding = False
                    follower.engage()  # from the speed it has now
                    if start_throttle is not None:
                        follower.prime(start_throttle)  # as when it has been driving the loop for a while
            world.player.apply_control(control)
            driver_input.force_feedback(speed_kmh)
            signal = {'left': base.LEFT_BLINKER, 'right': base.RIGHT_BLINKER}.get(blinker, 0)
            overlay._lights = signal  # pylint: disable=protected-access  (the cluster's arrows)
            lights = (base.BRAKE_LIGHT if control.brake > 0.0 else 0) | signal
            world.player.set_light_state(carla.VehicleLightState(lights))
            while logged_collisions < len(collisions):
                block.mark(t, 'collision: %s' % (block.tor.what_is(collisions[logged_collisions][1])
                                                 if block.tor is not None else collisions[logged_collisions][0]))
                logged_collisions += 1

            location = transform.location
            ttc = block.tor.ttc if block.tor is not None else None
            block.log.row('frames.csv', (round(t, 3), round(time.time(), 3), snapshot.frame, block.mode,
                                         'manual' if block.mode == MANUAL else 'auto',
                                         block.tor.phase if block.tor is not None else '',
                                         round(location.x, 2), round(location.y, 2), round(location.z, 2),
                                         round(transform.rotation.yaw, 2), round(speed_kmh, 2),
                                         2 + int(round(lateral / base.LANE_WIDTH)),
                                         round(lateral - base.LANE_WIDTH * round(lateral / base.LANE_WIDTH), 3),
                                         round(control.steer, 3), round(control.throttle, 3), round(control.brake, 3),
                                         round(wheel[0], 4), round(wheel[0] * WHEEL_HALF_DEG, 2), round(wheel[1], 3),
                                         round(wheel[2], 3), '' if ttc is None else round(ttc, 2),
                                         round(clock.get_fps(), 1)))
            for cid, (lane, dx, dv) in state.items():
                car = traffic.cars.get(cid)
                course = car['course'] if car else None
                planned = course.at(t) if course else None
                block.log.row('vehicles.csv', (round(t, 3), cid, course.kind if course else '',
                                               (course.event or ('F' if course.f_event else '')) if course else '',
                                               lane, '' if planned is None else round(planned[0], 2), round(dx, 2),
                                               round(dv, 2), abc_traffic._light_names(car['lights']) if car else '',
                                               '+'.join(sorted(mirrors.get(cid, {}))),
                                               ';'.join('%s:%s' % kv for kv in sorted(mirrors.get(cid, {}).items()))))
            if block.tor is not None:
                for cid, lane, dx, dv, lights, actor in block.tor.cars(transform, ego_s, ego_speed):
                    seen = mirror_view.of(actor)
                    block.tor.seen(t, block, cid, seen)
                    block.log.row('vehicles.csv', (round(t, 3), cid, 'tor', 'TOR', lane, '', round(dx, 2),
                                                   round(dv, 2), lights, '+'.join(sorted(seen)),
                                                   ';'.join('%s:%s' % kv for kv in sorted(seen.items()))))

            ticker.start()
            world.tick(clock)
            world.render(display)
            overlay.render(display, block.mode, speed_kmh, pedal,
                           block.tor.alert_wall if block.tor is not None and block.mode in (TOR, STOPPED) else None)
            pygame.display.flip()
            if snaps and t >= snaps[0]:
                snaps.pop(0)
                save_snapshot(display, world.camera_manager, t, state, mirrors, block.log.dir or DATA_DIR)
                # saving takes seconds: the next steps one frame each, not that long (as after a question)
                ticker.wait()
                settings.fixed_delta_seconds = 1.0 / args.fps
                sim_world.apply_settings(settings)
                fixed_frames = RESUME_FIXED_FRAMES
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
        block.finish(t, aborted)
        if block.g2 is not None:
            block.mark(t, 'run end')
            block.g2.close()
        block.log.close()
        if block.g2 is not None and not args.g2_no_stream and not args.no_post and block.log.dir:
            # the gaze analyses and the gaze video, in the background at idle priority (postprocess.py)
            try:
                import postprocess
                postprocess.detach(block.log.dir)
                logging.info('Gaze analyses and gaze_video.mp4 started in the background (postprocess.log)')
            except OSError as error:
                logging.warning('postprocess.py not started: %s', error)
        if sim_world is not None and client is not None:
            try:  # all cars stay put: in asynchronous mode (below) they would roll on (guardrail, each other)
                client.apply_batch_sync([carla.command.SetSimulatePhysics(a, False)
                                         for a in sim_world.get_actors().filter('vehicle.*')], False)
            except RuntimeError:
                pass
        if server_weather is not None:
            try:
                sim_world.set_weather(server_weather)
            except RuntimeError:
                pass
        if async_settings is not None:
            try:
                sim_world.apply_settings(async_settings)
            except RuntimeError:
                pass
        if sagat is not None:
            sagat.close()
        if driver_input is not None:
            driver_input.close()
        if audio is not None:
            audio.stop()
            # its collision sensor on the car: the killed process does not destroy it
            if world is not None and world.player is not None and sim_world is not None:
                own = {s.id for s in (collision_sensor, getattr(getattr(world, 'collision_sensor', None), 'sensor', None))
                       if s is not None}  # ours and the World's (world.destroy)
                try:
                    left = [a for a in sim_world.get_actors().filter('sensor.other.collision')
                            if a.parent is not None and a.parent.id == world.player.id and a.id not in own]
                    if left:
                        base.destroy_actors(client, left)
                except RuntimeError as error:
                    logging.warning('Audio engine sensor not removed: %s', error)
        if sound is not None:
            sound.stop()
        if block.tor is not None:
            block.tor.scene.destroy()
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
                show_end(display, Overlay(world, condition=args.condition), args.feedback_seconds)
            except Exception:  # pylint: disable=broad-except
                logging.exception('Feedback screen')
        pygame.quit()
    return aborted


def save_mirrors(manager, directory):
    """mirrors.json in the block folder: each mirror's glass outline in window px (the window over the
    three monitors, 5760 x 1080), for mirror_aoi.py (the gaze in the window's pixels through the bezel
    markers: mirror_register.py)."""
    if not directory:
        return
    views = getattr(manager, 'mirror_views', [])
    mirrors = {view['name']: {'rect': [rect.x, rect.y, rect.width, rect.height],
                              'glass': [[round(x, 1), round(y, 1)] for x, y in view['glass']]}
               for rect, _, view in views if 'name' in view}
    if not mirrors:
        logging.warning('No mirrors to save (mirrors.json)')
        return
    with open(os.path.join(directory, 'mirrors.json'), 'w', encoding='utf-8') as handle:
        json.dump({'window_px': [manager.screen_width * manager.screens, manager.screen_size[1]],
                   'mirrors': mirrors}, handle, indent=1)


def save_snapshot(display, manager, t, state, mirrors, directory):
    """--snap: the whole window and each mirror inset (3 x larger, as it is drawn) as PNG files, named
    with the time and the event cars' dx and mirrors."""
    folder = os.path.join(directory, 'snaps')
    os.makedirs(folder, exist_ok=True)
    events = ['%s_dx%.0f_%s' % (cid, dx, '+'.join('%s%.0fpx' % kv for kv in sorted(mirrors.get(cid, {}).items())) or 'none')
              for cid, (lane, dx, dv) in sorted(state.items()) if cid.split('-')[1][:1] in 'SR' and '-B' not in cid
              and '-Q' not in cid and '-F' not in cid]
    name = 't%06.1f_%s' % (t, '_'.join(events) or 'noevent')
    pygame.image.save(display, os.path.join(folder, name + '_screen.png'))
    for rect, camera, _ in getattr(manager, 'mirror_views', []):
        offset = camera.get_transform().location - manager._parent.get_location()  # pylint: disable=protected-access
        right = manager._parent.get_transform().get_right_vector()  # pylint: disable=protected-access
        side = offset.x * right.x + offset.y * right.y
        which = 'left' if side < -0.5 else 'right' if side > 0.5 else 'rear'
        crop = display.subsurface(rect.clip(display.get_rect())).copy()
        crop = pygame.transform.scale(crop, (crop.get_width() * 3, crop.get_height() * 3))
        pygame.image.save(crop, os.path.join(folder, '%s_%s.png' % (name, which)))
    logging.info('Snapshot %s', name)


def sim_driver(kind, tor, route, s, transform, lateral, speed, wanted_kmh):
    """--sim-driver: after the takeover, to the middle of the safe or unsafe lane, at the speed the
    car drove itself at (slower in the curves), or a full stop in lane 2. Pure pursuit of a point
    on the lane's line ahead."""
    if kind == 'brake':
        return carla.VehicleControl(throttle=0.0, brake=0.6)
    target = (tor.safe if kind == 'safe' else tor.unsafe) - 2  # -1 left, +1 right
    error = target * base.LANE_WIDTH - lateral
    ahead = max(12.0, 1.0 * speed)
    # the lane line ahead, moved over to the target lane over at most 2 lane widths' worth of path
    shift = lateral + max(-0.12 * ahead, min(0.12 * ahead, error))
    point, _, _, (rx, ry) = route.pose(s + ahead)
    gx, gy = point.x + rx * shift, point.y + ry * shift
    location = transform.location
    yaw = math.radians(transform.rotation.yaw)
    dx, dy = gx - location.x, gy - location.y
    alpha = math.atan2(dy, dx) - yaw
    alpha = (alpha + math.pi) % (2.0 * math.pi) - math.pi
    distance = max(math.hypot(dx, dy), 1.0)
    angle = math.atan(2.0 * 2.9 * math.sin(alpha) / distance)  # wheel base ~2.9 m
    steer = max(-1.0, min(1.0, angle / math.radians(70.0)))
    goal = wanted_kmh / 3.6
    if speed > goal + 0.5:
        return carla.VehicleControl(throttle=0.0, brake=min(0.6, 0.15 * (speed - goal)), steer=steer)
    throttle = max(0.0, min(0.8, 0.4 + 0.15 * (goal - speed)))
    return carla.VehicleControl(throttle=throttle, steer=steer)


def lateral_offset(route, s, location):
    """m the location is right of the route's line at s (< 0: left); the ego car's lane is lane 2."""
    here, _, _, (rx, ry) = route.pose(s)
    return (location.x - here.x) * rx + (location.y - here.y) * ry


def collision_log(sim_world, vehicle):
    """carla_base.log_collisions with the other actor's id: [(type_id, id)]."""
    hits = []
    last = {}

    def on_collision(event):
        other = event.other_actor
        now = time.monotonic()
        if now - last.get(other.id, -1e9) < base.COLLISION_LOG_GAP:
            return
        last[other.id] = now
        hits.append((other.type_id, other.id))
        logging.warning('Collision with %s', other.type_id)
    sensor = sim_world.spawn_actor(sim_world.get_blueprint_library().find('sensor.other.collision'),
                                   carla.Transform(), attach_to=vehicle)
    sensor.listen(on_collision)
    return sensor, hits


class TorRun(object):
    """The block's TOR as it happens: the scene's timeline (abc_traffic.TorScene), the alert, the
    takeover, the automatic emergency stop, and the measures of tor_events.csv."""

    def __init__(self, block, event, template, scene, ego):
        self.event = event
        self.tt = template
        self.scene = scene
        self.t = event['t']
        self.safe, self.unsafe = event['safe_lane'], event['unsafe_lane']
        self.phase = ''
        self._hazard_due = self.t + template['hazard_vehicle']['spawn_rel_s']
        self._obstacle_due = self.t + template['obstacle']['spawn_rel_s']
        self._clear_at = self.t + template['clear_rel_s']
        self._ego_length, self._ego_width = 2.0 * ego.bounding_box.extent.x, 2.0 * ego.bounding_box.extent.y
        self._ego_id = ego.id
        self.t_alert = None
        self.alert_wall = None     # time.monotonic() of the alert: the blink
        self.baseline = None       # (steer, throttle, brake) at the alert
        self.t_first_input = self.first_input_type = self.t_manual = None
        self.lc_start = self.lc_end = self.chosen = None
        self.t_blinker = self.blinker_side = None  # the first turn signal from the alert on
        self.min_ttc = self.min_gap_hazard = None
        self.ttc = None
        self.conflict = False
        self.no_takeover = False
        self.collision = None
        self.t_stop = None
        self._seen_logged = False
        self._hits_before = 0      # collisions before the alert (not the TOR's)
        self._new = False          # the approaching car appeared this frame

    # -- the cars ----------------------------------------------------------------------------

    def obstacle_gap(self, ego_s):
        """m bumper to bumper to the stopped car ahead (None: not there, or passed)."""
        dx = self.scene.obstacle_dx(ego_s)
        if dx is None:
            return None
        gap = dx - (self._ego_length + self.scene.obstacle_length) / 2.0
        return gap if gap > -2.0 else None

    def _accel(self, transform):
        """m/s^2 the ego car speeds up at, along its heading."""
        a = self.scene._traffic._world.get_actor(self._ego_id).get_acceleration()  # pylint: disable=protected-access
        f = transform.get_forward_vector()
        return a.x * f.x + a.y * f.y

    def what_is(self, actor_id):
        if self.scene.obstacle_actor is not None and actor_id == self.scene.obstacle_actor.id:
            return 'obstacle'
        if self.scene.hazard_actor is not None and actor_id == self.scene.hazard_actor.id:
            return 'hazard'
        return 'other'

    def cars(self, transform, ego_s, ego_speed):
        """[(id, lane, dx, dv km/h, lights, actor)] of its cars (vehicles.csv)."""
        out = []
        prefix = self.event['id']
        if self.scene.hazard_actor is not None and not self._new:
            out.append((prefix + '-hazard', self.unsafe, self.scene.hazard_dx(transform),
                        (self.scene.hazard_speed - ego_speed) * 3.6, 'brake' if self.scene.yielding else 'off',
                        self.scene.hazard_actor))
        if self.scene.obstacle_actor is not None:
            out.append((prefix + '-obstacle', 2, self.scene.obstacle_dx(ego_s), -ego_speed * 3.6, 'hazard',
                        self.scene.obstacle_actor))
        return out

    def seen(self, t, block, cid, mirrors):
        """At the alert: how big the approaching car is in its side mirror (logged once)."""
        if self._seen_logged or self.t_alert is None or not cid.endswith('-hazard'):
            return
        self._seen_logged = True
        side = 'right' if self.unsafe == 3 else 'left'
        px = mirrors.get(side)
        block.log.event(t, 'approaching car in the %s mirror at the alert: %s' % (
            side, 'not visible' if px is None else '%.0f px%s' % (
                px, '' if px >= MirrorVisibility.RECOGNIZE_PX else ' (smaller than RECOGNIZE_PX)')), self.event['id'])

    # -- per frame ---------------------------------------------------------------------------

    def over(self, t):
        return self.t_stop is not None and t >= self.t_stop + self.tt['end_after_stop_s']

    def tick(self, t, block, transform, ego_s, ego_speed, lateral, wheel, dt, sound, collisions):
        eid = self.event['id']
        scene = self.scene
        self._new = False
        # the timeline
        if t >= self._clear_at and not self.phase:
            self.phase = 'clear'
            block.mark(t, 'tor clear (no other cars from here)', eid)
        if t >= self._hazard_due and scene.hazard_actor is None and self.phase == 'clear':
            if scene.hazard(t, transform, ego_speed):
                self.phase = 'hazard_spawn'
                self._new = True
                block.mark(t, 'tor hazard_spawn (lane %d, %.0f m behind)' % (
                    self.unsafe, -self.tt['hazard_vehicle']['spawn_dx_m']), eid)
        if t >= self._obstacle_due and scene.obstacle_actor is None and self.phase == 'hazard_spawn':
            accel = self._accel(transform)
            if scene.obstacle(ego_s, ego_speed, block.config['ego']['speed_kmh'] / 3.6, accel,
                              -self.tt['obstacle']['spawn_rel_s']):
                self.phase = 'obstacle_spawn'
                block.mark(t, 'tor obstacle_spawn (lane 2, %.0f m ahead at %.0f km/h)' % (
                    scene.obstacle_spawn_dx, ego_speed * 3.6), eid)
        if scene.hazard_actor is not None and not self._new:
            scene.tick(t, transform, ego_speed, dt)  # (the client sees where it is from the frame after it appeared)
        if t >= self.t and self.t_alert is None and scene.obstacle_actor is not None:
            self.t_alert = t
            self.alert_wall = time.monotonic()
            self.phase = 'alert'
            self.baseline = wheel
            self._hits_before = len(collisions)
            block.mode = TOR
            scene.release()  # the approaching car keeps its speed from here
            if self.tt['alert'].get('sound', True):
                sound.tor()
            for player in block.media:
                player.alert(eid, base.TOR_MESSAGE)
            hazard = scene.hazard_dx(transform)
            obstacle = self.obstacle_gap(ego_s)
            block.mark(t, 'tor alert (stopped car %s m ahead, TTC %s s; approaching car %s m)' % (
                '-' if obstacle is None else '%.0f' % obstacle,
                '-' if obstacle is None or ego_speed < 0.5 else '%.1f' % (obstacle / ego_speed),
                '-' if hazard is None else '%.0f' % hazard), eid, safe_lane=self.safe, unsafe_lane=self.unsafe)
        # the stopped car: TTC while the ego car is in its lane
        gap = self.obstacle_gap(ego_s)
        in_lane2 = abs(lateral) < (self._ego_width + scene.obstacle_width) / 2.0
        self.ttc = gap / ego_speed if gap is not None and gap > 0.0 and ego_speed > 0.3 and in_lane2 else None
        if self.t_alert is None:
            return
        if self.ttc is not None:
            self.min_ttc = self.ttc if self.min_ttc is None else min(self.min_ttc, self.ttc)
        # the driver
        if block.mode in (TOR, STOPPED):
            steer, throttle, brake = wheel
            d_steer = abs(steer - self.baseline[0])
            d_throttle, d_brake = throttle - self.baseline[1], brake - self.baseline[2]
            if self.t_first_input is None:
                shares = {'steering': d_steer / FIRST_INPUT_STEER, 'throttle': d_throttle / FIRST_INPUT_PEDAL,
                          'brake': d_brake / FIRST_INPUT_PEDAL}
                kind = max(shares, key=shares.get)
                if shares[kind] >= 1.0:
                    self.t_first_input, self.first_input_type = t, kind
                    block.mark(t, 'first input (%s) %.2f s after the alert' % (kind, t - self.t_alert), eid)
            if d_steer > base.STEER_TAKEOVER or d_throttle > base.PEDAL_TAKEOVER or d_brake > base.PEDAL_TAKEOVER:
                was = block.mode
                block.mode = MANUAL
                self.phase = 'manual'
                if self.t_manual is None:
                    self.t_manual = t
                if self.t_first_input is None:  # past both thresholds in one frame
                    self.t_first_input = t
                    self.first_input_type = ('steering' if d_steer > base.STEER_TAKEOVER else
                                             'brake' if d_brake > base.PEDAL_TAKEOVER else 'throttle')
                sound.stop(confirm=True)
                for player in block.media:
                    player.alert_off(eid)
                block.mark(t, 'takeover %.2f s after the alert%s' % (
                    t - self.t_alert, ' (during the emergency stop)' if was == STOPPED else ''), eid)
            elif block.mode == TOR and self.ttc is not None and self.ttc <= self.tt['auto_stop_ttc_s']:
                block.mode = STOPPED
                self.phase = 'auto_stop'
                self.no_takeover = True
                sound.stop()
                block.mark(t, 'no takeover: automatic emergency stop at TTC %.2f s' % self.ttc, eid)
        # the lane change (from the middle of lane 2: its sides touch the line, then all of it across)
        half = base.LANE_WIDTH / 2.0
        if self.lc_end is None:
            if abs(lateral) + self._ego_width / 2.0 >= half:
                if self.lc_start is None:
                    self.lc_start = t
                    block.mark(t, 'lane change start (towards lane %d)' % (3 if lateral > 0 else 1), eid)
                if abs(lateral) - self._ego_width / 2.0 >= half:
                    self.lc_end = t
                    self.chosen = 3 if lateral > 0 else 1
                    block.mark(t, 'lane change end: lane %d (%s)' % (
                        self.chosen, 'the safe lane' if self.chosen == self.safe else 'the approaching car\'s lane'), eid)
            elif self.lc_start is not None:
                self.lc_start = None  # back in lane 2
                block.mark(t, 'lane change given up', eid)
        # the approaching car: the gap while the ego car is (partly) in its lane, and its yielding
        hazard = scene.hazard_dx(transform)
        middle = (self.unsafe - 2) * base.LANE_WIDTH
        if hazard is not None and abs(lateral - middle) < half + self._ego_width / 2.0:
            gap = abs(hazard) - (self._ego_length + scene.hazard_length) / 2.0
            self.min_gap_hazard = gap if self.min_gap_hazard is None else min(self.min_gap_hazard, gap)
            if not self.conflict and hazard < 0 and gap < self.tt['hazard_vehicle']['yield_if_cut_in_gap_m']:
                self.conflict = True
                scene.yield_to()
                block.mark(t, 'conflict: in the approaching car\'s lane %.1f m ahead of it, it brakes' % gap, eid)
        # the first collision from the alert on: its cars, or anything else (e.g. static.guardrail)
        if self.collision is None and len(collisions) > self._hits_before:
            type_id, actor_id = collisions[self._hits_before]
            what = self.what_is(actor_id)
            self.collision = what if what != 'other' else type_id
        # standing still: the block ends end_after_stop_s later
        if self.t_stop is None and ego_speed * 3.6 < STOPPED_KMH:
            self.t_stop = t
            self.phase = 'end'
            block.mark(t, 'the car stands still: the block ends in %.0f s' % self.tt['end_after_stop_s'], eid)

    def signal(self, t, side):
        """The driver's turn signal (left / right paddle) switched on at t."""
        if self.t_alert is not None and t >= self.t_alert and self.t_blinker is None:
            self.t_blinker, self.blinker_side = t, side

    def row(self, block):
        def r(x, n=2):
            return None if x is None else round(x, n)
        args = block.args
        return {'participant': args.participant, 'block': args.block, 'set': args.set, 'condition': args.condition,
                't_tor': r(self.t_alert, 3), 'safe_lane': self.safe, 'unsafe_lane': self.unsafe,
                't_first_input': r(self.t_first_input, 3), 't_manual': r(self.t_manual, 3),
                'first_input_type': self.first_input_type, 't_lane_change_start': r(self.lc_start, 3),
                't_lane_change_end': r(self.lc_end, 3), 'chosen_lane': self.chosen,
                'chose_safe': None if self.chosen is None else self.chosen == self.safe, 'min_ttc_obstacle_s': r(self.min_ttc),
                'min_gap_hazard_m': r(self.min_gap_hazard), 'conflict': self.conflict, 'collision': self.collision,
                'no_takeover': self.no_takeover, 't_blinker': r(self.t_blinker, 3), 'blinker_side': self.blinker_side,
                'blinker_before_lane_change': None if self.t_blinker is None or self.lc_start is None
                else self.t_blinker <= self.lc_start,
                'blinker_matches_lane': None if self.t_blinker is None or self.chosen is None
                else (self.blinker_side == 'left') == (self.chosen == 1)}


def car_sound(on):
    """The car sound of carla-audio-engine on or off (it plays on while the simulation stands still)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.sendto(b'unmute' if on else b'mute', ('127.0.0.1', AUDIO_MUTE_PORT))
    except OSError:
        pass


def ask_question(block, q, number, t, traffic, sagat, overlay, display, clock, mirrors=None):
    """SAGAT: the simulation is not stepped, the monitors are black, the tablet asks. Returns False
    if the run was ended (ESC)."""
    truth = sagat_truth(traffic.snapshot(t, block.qt['approach_window_s']), block.qt, mirrors)
    block.frozen = True
    car_sound(False)
    for player in block.media:
        player.pause(q['id'])
    block.mark(t, 'freeze (SAGAT %d)' % number, q['id'])
    seconds = block.qt['max_answer_s']
    stop = (block.ndrt or {}).get('stops', {}).get(q['id'])   # its NDRT video questions
    sagat.ask(q['id'], number, seconds, [i['image'] for i in stop['items']] if stop else ())
    started = time.monotonic()
    if not sagat.connected():
        logging.warning('SAGAT tablet not connected: open %s on the iPad or the laptop (sagat_laptop.bat)', sagat.url)
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
        answer = sagat.answer()
        waited = time.monotonic() - started
        if answer is not None or skipped or waited >= seconds:
            break
        overlay.black(display, ['화면이 멈췄습니다', '태블릿의 질문에 답해 주세요'])
        pygame.display.flip()
        clock.tick(30)
    answer_s = round(time.monotonic() - started, 2)
    score = sagat_score(truth, answer)
    entry = {'id': q['id'], 'number': number, 't': round(t, 3), 't_planned': q['t'],
             'planned': {'cells': q['cells'], 'approach': q['approach'], 'safe': q['safe']},
             'truth': truth, 'answer': answer, 'answer_s': answer_s,
             'ended_by': 'answer' if answer is not None else 'skipped' if skipped else 'timeout',
             'score': score}
    block.questions.append(entry)
    block.mark(t, 'answer after %.1f s (%s)' % (answer_s, 'answered' if answer else 'skipped' if skipped else 'timeout'),
               q['id'])
    if score.get('answered'):
        logging.info('   correct %.0f %% (behind %s, ahead %s; not scored: %s)', 100 * (score['score'] or 0),
                     score['behind'], score['ahead'], ', '.join(score['unscored']) or '-')
    if stop and not ask_ndrt(block, q, t, stop, entry, started, sagat, overlay, display, clock):
        sagat.idle()
        car_sound(True)
        return False
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


def ask_ndrt(block, q, t, stop, entry, started, sagat, overlay, display, clock):
    """The NDRT video questions of a stop at the freeze (started, time.monotonic()) + ndrt_at_s: the
    tablet waits until then; at most ndrt_max_answer_s. Into entry['ndrt'] and ndrt.csv. False if the
    run was ended (ESC)."""
    def frozen_until(done, until):
        """The black monitors until done() or until (time.monotonic()): 'esc', 'skip' (N) or None."""
        while not done() and time.monotonic() < until:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYUP and event.key == pygame.K_ESCAPE):
                    return 'esc'
                if event.type == pygame.KEYDOWN and event.key == pygame.K_n:
                    return 'skip'
            overlay.black(display, ['화면이 멈췄습니다', '태블릿의 질문에 답해 주세요'])
            pygame.display.flip()
            clock.tick(30)
        return None

    qid = q['id']
    sagat.wait(qid)
    waited = frozen_until(lambda: False, started + block.qt['ndrt_at_s'])
    if waited == 'esc':
        return False
    answer, ended, asked_at = None, 'skipped', None
    if waited is None:
        seconds = block.qt['ndrt_max_answer_s']
        sagat.ask_ndrt(qid, [i['image'] for i in stop['items']], seconds)
        asked_at = time.monotonic()
        block.mark(t, 'video questions (%.1f s after the freeze)' % (asked_at - started), qid)
        result = frozen_until(lambda: sagat.answer() is not None, asked_at + seconds)
        if result == 'esc':
            return False
        answer = sagat.answer()
        ended = 'answer' if answer is not None else 'skipped' if result == 'skip' else 'timeout'
    score = ndrt_score(stop, answer)
    entry['ndrt'] = {'asked_after_freeze_s': None if asked_at is None else round(asked_at - started, 2),
                     'answer_s': None if asked_at is None else round(time.monotonic() - asked_at, 2),
                     'ended_by': ended, 'items': stop['items'], 'answer': answer, 'score': score}
    given = {a.get('image'): a for a in (answer or {}).get('answers') or []}
    for k, item in enumerate(stop['items'], 1):
        a = given.get(item['image'], {})
        said = a.get('shown')
        block.log.row('ndrt.csv', [qid, k, item['image'], item['shown'], '' if said is None else said,
                                   a.get('confidence', ''), a.get('ms', ''), '' if said is None else said == item['shown'],
                                   item.get('video_t', ''), item.get('before_stop_s', ''), item.get('episode_t', '')])
    block.mark(t, 'video questions: %s' % ('%d / %d correct' % (score['correct'], score['asked'])
                                           if score['answered'] else ended), qid)
    return True


def show_end(display, overlay, seconds):
    """The end of the drive on the monitors (no scores) until a key or a wheel button (or `seconds`)."""
    until = time.monotonic() + seconds
    pygame.event.clear()
    while time.monotonic() < until:
        for event in pygame.event.get():
            if event.type in (pygame.KEYDOWN, pygame.QUIT, pygame.JOYBUTTONDOWN):
                return
        overlay.black(display, ['주행이 끝났습니다', '잠시 기다려 주세요'])
        pygame.display.flip()
        time.sleep(0.05)


if __name__ == '__main__':
    main()
