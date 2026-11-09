#!/usr/bin/env python

"""
Real-time gaze on objects for takeover_experiment.py --gaze: which object in the driving scene the
driver is looking at, frame by frame, on the middle monitor only.

    gaze_bridge.py (Python 3.10, Tobii SDK) --UDP--> GazeReceiver --> GazeTracker.tick() --> state

Every frame the bounding boxes of the vehicles, walkers and props (cones, barriers, signs) within
MAX_DISTANCE are projected onto the middle monitor. During a fixation (the samples of the last
FIXATION_WINDOW s stay within the tolerance) the gaze goes to the box it is in, or the closest box
within the tolerance. Where boxes overlap the nearest one wins: it hides the others. Only actors are
known here: buildings, terrain and the road do not hide anything, and they are never the answer.

GazeTracker.state is the result, for anything that reacts while driving:
    state.object_class, state.object_id, state.distance   what is looked at, None if nothing
    state.dwell      s on that object so far
    state.confirmed  dwell >= MIN_DWELL: use this one, a shorter look may be a passing glance
    state.ambiguous  another object is also within the tolerance (small, far objects next to each other)

What the car "perceives" (--unperceived names what it misses, the rest is perceived) decides what the driver gets:
    --gaze-box    (box condition) a box on every perceived object all the time, colored by class as in
                  Wang et al. 2026 (EP): red vehicles and obstacles, blue pedestrians, yellow signs
    --gaze-query  (query condition) no boxes; the wheel's query button asks about the gaze of just before:
                  a perceived object within the tolerance -> its box and "인식함"; else a ring at the gaze
                  and "인식된 물체 없음". Only perceived objects are compared, as a real car could: with
                  the gaze on a missed object next to a perceived one the answer is "인식함".
    neither       (no display) the gaze is only logged
gaze_queries.csv logs every query, with the object looked at by the full list of objects (true_*).

Logged next to raw.csv (which gets the same per frame, as gaze_* columns):
    gaze_samples.csv  every sample as received
    gaze_events.csv   one row per confirmed look at an object
"""

from __future__ import print_function

import collections
import csv
import datetime
import fnmatch
import json
import logging
import math
import os
import socket
import threading
import time

import numpy

DEFAULT_PORT = 5010
DEFAULT_TOLERANCE = 45.0  # px: about 1 degree on a 48 cm wide 1920 px monitor seen from 65 cm
MAX_DISTANCE = 250.0      # m
FIXATION_WINDOW = 0.1     # s of samples that have to stay together
MIN_SAMPLES = 3           # valid samples in that window; fewer: no fixation
STALE_AFTER = 0.15        # s without a sample: the samples stopped
MIN_DWELL = 0.1           # s on an object before it counts
HOLD_LOST = 0.1           # s a look survives without the object (blinks, a noisy sample)
REFRESH_ACTORS = 1.0      # s between actor lists (a server round trip)
NO_SAMPLES_WARN = 5.0     # s without samples before the warning
FALLBACK_EXTENT = 0.3     # m: half size of a prop that reports an empty bounding box

OBJECT_CLASSES = ('vehicle', 'walker', 'cone', 'barrier', 'sign', 'prop')
CLASS_COLORS = {'vehicle': (230, 40, 40), 'cone': (230, 40, 40), 'barrier': (230, 40, 40), 'prop': (230, 40, 40),
                'walker': (40, 130, 255), 'sign': (250, 210, 40)}  # Wang et al. 2026, EP
BOX_WIDTH = 2             # px
LABEL_MIN_WIDTH = 30      # px: smaller boxes go without their class label, against clutter
QUERY_WINDOW = 0.2        # s before the button press that make up the gaze asked about
QUERY_SHOW = 1.5          # s the answer stays
QUERY_RING = 40           # px
QUERY_PERCEIVED, QUERY_NONE, QUERY_NO_GAZE = 'perceived', 'none', 'no_gaze'
QUERY_TEXTS = {QUERY_PERCEIVED: '인식함', QUERY_NONE: '인식된 물체 없음', QUERY_NO_GAZE: '시선을 찾지 못함'}
QUERY_COLORS = {QUERY_PERCEIVED: (60, 230, 90), QUERY_NONE: (255, 120, 0), QUERY_NO_GAZE: (200, 200, 200)}
KOREAN_FONT = 'malgungothic'

Box = collections.namedtuple('Box', 'id cls distance left top right bottom perceived', defaults=(True,))
GazeState = collections.namedtuple('GazeState', 'valid fixating x y pupil object_id object_class distance '
                                                'dwell confirmed ambiguous')
NO_GAZE = GazeState(False, False, None, None, None, None, None, None, 0.0, False, False)


def object_class(type_id):
    """One of OBJECT_CLASSES for a blueprint id; None: not a gaze target."""
    if type_id.startswith('vehicle.'):
        return 'vehicle'
    if type_id.startswith('walker.'):
        return 'walker'
    if not type_id.startswith('static.prop.') or 'debris' in type_id:
        return None
    if 'cone' in type_id:
        return 'cone'
    if 'barrier' in type_id or 'barrel' in type_id:
        return 'barrier'
    if 'warning' in type_id or 'sign' in type_id:
        return 'sign'
    return 'prop'


def project_box(points, eye, size, focal):
    """(left, top, right, bottom, distance) on one monitor of `points` (3 x N, car coordinates) seen
    from `eye` (x, y, z, pitch, yaw; degrees); None if a point is behind the eye or all is off it.
    The same projection as _project in takeover_experiment.py, for many points at once."""
    width, height = size
    dx, dy, dz = points[0] - eye[0], points[1] - eye[1], points[2] - eye[2]
    pitch, yaw = math.radians(eye[3]), math.radians(eye[4])
    x = dx * math.cos(yaw) + dy * math.sin(yaw)
    y = -dx * math.sin(yaw) + dy * math.cos(yaw)
    x, z = x * math.cos(pitch) + dz * math.sin(pitch), -x * math.sin(pitch) + dz * math.cos(pitch)
    if x.min() <= 0.05:
        return None
    u = width / 2.0 + focal * y / x
    v = height / 2.0 - focal * z / x
    left, top, right, bottom = u.min(), v.min(), u.max(), v.max()
    if right < 0 or left >= width or bottom < 0 or top >= height:
        return None
    return left, top, right, bottom, math.sqrt(dx.mean() ** 2 + dy.mean() ** 2 + dz.mean() ** 2)


def select_object(boxes, x, y, tolerance, current_id=None):
    """(box, ambiguous) at gaze point (x, y); (None, False) if no box is within the tolerance.
    `current_id` is the object looked at so far: it stays unless another is clearly better, so that
    noise does not hop between neighbours."""
    candidates = []
    for box in boxes:
        off = math.hypot(max(box.left - x, 0.0, x - box.right), max(box.top - y, 0.0, y - box.bottom))
        if off <= tolerance:
            candidates.append((off, box))
    if not candidates:
        return None, False
    # the nearest box the gaze is in hides those behind it; else the closest box
    inside = [box for off, box in candidates if off == 0.0]
    if inside:
        front = min(inside, key=lambda box: box.distance)
        candidates = [(off, box) for off, box in candidates if off > 0.0 or box is front]
        best_off, best = 0.0, front
    else:
        best_off, best = min(candidates, key=lambda candidate: candidate[0])
    for off, box in candidates:
        if box.id == current_id and off - best_off < tolerance / 2.0:
            best = box
    return best, len(candidates) > 1


class GazeJudge(object):
    """The look at one object over time, from the gaze point and boxes of each frame."""

    def __init__(self, tolerance=DEFAULT_TOLERANCE, on_look_end=None):
        self.tolerance = tolerance
        self._on_look_end = on_look_end
        self.box = None
        self.ambiguous = False
        self._start = None
        self._seen = None

    def update(self, now, point, boxes):
        """`point`: gaze (x, y) on the monitor during a fixation, else None."""
        box, ambiguous = (None, False)
        if point is not None:
            box, ambiguous = select_object(boxes, point[0], point[1], self.tolerance,
                                           self.box.id if self.box is not None else None)
        if box is None:
            if self.box is not None and now - self._seen > HOLD_LOST:
                self.end()
            return
        if self.box is None or box.id != self.box.id:
            self.end()
            self._start = now
        self.box = box
        self.ambiguous = ambiguous
        self._seen = now

    def dwell(self, now):
        return now - self._start if self.box is not None else 0.0

    def end(self):
        if self.box is not None and self._on_look_end is not None and self._seen - self._start >= MIN_DWELL:
            self._on_look_end(self.box, self._start, self._seen, self.ambiguous)
        self.box = None
        self.ambiguous = False


class GazeReceiver(object):
    """Keeps the latest samples from gaze_bridge.py. Runs in its own thread: the samples come at 60 Hz
    whatever the frame rate is."""

    def __init__(self, port=DEFAULT_PORT, on_sample=None):
        self._samples = collections.deque(maxlen=64)
        self._lock = threading.Lock()
        self._on_sample = on_sample
        self.received = 0
        self.valid = 0
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(('127.0.0.1', port))
        self._socket.settimeout(0.2)
        self._running = True
        self._thread = threading.Thread(target=self._run, name='gaze-receiver', daemon=True)
        self._thread.start()

    def _run(self):
        while self._running:
            try:
                packet, _ = self._socket.recvfrom(1024)
                sample = json.loads(packet.decode('utf-8'))
            except (OSError, ValueError):  # socket.timeout is an OSError
                continue
            arrived = time.monotonic()
            with self._lock:
                self.received += 1
                self.valid += sample.get('x') is not None
                self._samples.append((arrived, sample))
            if self._on_sample is not None:
                self._on_sample(arrived, sample)

    def recent(self, now, seconds):
        with self._lock:
            return [sample for arrived, sample in self._samples if now - arrived <= seconds]

    def last_arrival(self):
        with self._lock:
            return self._samples[-1][0] if self._samples else None

    def close(self):
        self._running = False
        self._thread.join(1.0)
        self._socket.close()


def fixation_point(samples, size, tolerance):
    """(x, y, pupil, fixating) in monitor pixels from samples with x, y as shares of the monitor;
    None if there are too few valid ones."""
    points = [(s['x'] * size[0], s['y'] * size[1]) for s in samples if s.get('x') is not None]
    if len(points) < MIN_SAMPLES:
        return None
    xs, ys = zip(*points)
    pupils = [s['pupil'] for s in samples if s.get('pupil') is not None]
    pupil = sum(pupils) / len(pupils) if pupils else None
    x, y = sum(xs) / len(xs), sum(ys) / len(ys)
    fixating = max(xs) - min(xs) <= tolerance and max(ys) - min(ys) <= tolerance
    return x, y, pupil, fixating


class SceneObjects(object):
    """The gaze targets in the world and their boxes on the middle monitor."""

    def __init__(self, sim_world, player, max_distance=MAX_DISTANCE, unperceived=()):
        self._world = sim_world
        self._player = player
        self._max_distance = max_distance
        self._unperceived = unperceived  # patterns of blueprint ids and role names
        self._objects = {}  # id: (actor, class, 4 x 8 corners in actor coordinates, perceived)
        self._refreshed = None

    def _perceived(self, actor):
        names = (actor.type_id, actor.attributes.get('role_name', ''))
        return not any(fnmatch.fnmatch(name, pattern) for pattern in self._unperceived for name in names)

    def refresh(self, now):
        if self._refreshed is not None and now - self._refreshed < REFRESH_ACTORS:
            return
        self._refreshed = now
        present = set()
        for actor in self._world.get_actors():
            cls = object_class(actor.type_id)
            if cls is None or actor.id == self._player.id:
                continue
            present.add(actor.id)
            if actor.id not in self._objects:
                # bounding_box: a round trip
                self._objects[actor.id] = (actor, cls, self._corners(actor), self._perceived(actor))
        for gone in set(self._objects) - present:
            del self._objects[gone]

    @staticmethod
    def _corners(actor):
        box = actor.bounding_box
        extent = [box.extent.x, box.extent.y, box.extent.z]
        if max(extent) <= 0.01:
            extent = [FALLBACK_EXTENT] * 3
        center = (box.location.x, box.location.y, box.location.z)
        corners = [[center[0] + sx * extent[0], center[1] + sy * extent[1], center[2] + sz * extent[2], 1.0]
                   for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        return numpy.array(corners).T

    def boxes(self, eye, size, focal):
        transform = self._player.get_transform()
        origin = transform.location
        to_car = numpy.array(transform.get_inverse_matrix())
        limit = self._max_distance ** 2
        boxes = []
        for actor_id, (actor, cls, corners, perceived) in self._objects.items():
            try:
                other = actor.get_transform()
            except RuntimeError:  # destroyed since the last actor list
                continue
            location = other.location
            if (location.x - origin.x) ** 2 + (location.y - origin.y) ** 2 > limit:
                continue
            projected = project_box(to_car.dot(numpy.array(other.get_matrix()).dot(corners)), eye, size, focal)
            if projected is not None:
                boxes.append(Box(actor_id, cls, projected[4], *projected[:4], perceived))
        return boxes


class GazeTracker(object):
    """--gaze: tick() once per frame, then read .state."""

    def __init__(self, sim_world, world, port=DEFAULT_PORT, tolerance=DEFAULT_TOLERANCE, unperceived=()):
        self._manager = world.camera_manager
        self._scene = SceneObjects(sim_world, world.player, unperceived=unperceived)
        self._tolerance = tolerance
        self._answer = None  # the query answer on screen: {kind, until, object_id, x, y}
        self._fonts = {}
        self._judge = GazeJudge(tolerance, self._log_look)
        self._boxes = []
        self._started = time.monotonic()
        self._flowing = None
        self._dir = None
        self._lock = threading.Lock()
        self._files = {}
        self.state = NO_GAZE
        self._receiver = GazeReceiver(port, self._log_sample)
        logging.info('Gaze: waiting for gaze_bridge.py on UDP port %d', port)

    def log_to(self, directory):
        self._dir = directory

    def tick(self, now, driver_view=True):
        """`driver_view`: the middle monitor shows the driver's view, so the boxes mean something."""
        self._watch_samples(now)
        self._scene.refresh(now)
        manager = self._manager
        size = manager.screen_size
        gaze = fixation_point(self._receiver.recent(now, FIXATION_WINDOW), size, self._tolerance)
        self._boxes = []
        if driver_view:
            transform = manager._camera_transforms[manager.transform_index][0]  # pylint: disable=protected-access
            eye = (transform.location.x, transform.location.y, transform.location.z,
                   transform.rotation.pitch, transform.rotation.yaw)
            fov = manager.view_options.get(manager.transform_index, (None, False))[0] or manager.default_fov
            focal = size[0] / 2.0 / math.tan(math.radians(fov) / 2.0)
            self._boxes = self._scene.boxes(eye, size, focal)
        fixation = (gaze[0], gaze[1]) if gaze is not None and gaze[3] else None
        self._judge.update(now, fixation, self._boxes)
        if self._answer is not None and now >= self._answer['until']:
            self._answer = None
        box = self._judge.box
        dwell = self._judge.dwell(now)
        self.state = GazeState(gaze is not None, fixation is not None,
                               gaze[0] if gaze else None, gaze[1] if gaze else None, gaze[2] if gaze else None,
                               box.id if box else None, box.cls if box else None, box.distance if box else None,
                               dwell, box is not None and dwell >= MIN_DWELL, self._judge.ambiguous)

    def query(self, now):
        """The query button: answer for the gaze of just before, compared with the perceived objects
        only. Returns the kind of answer."""
        gaze = fixation_point(self._receiver.recent(now, QUERY_WINDOW), self._manager.screen_size, self._tolerance)
        answered = looked_at = None
        if gaze is None:
            kind = QUERY_NO_GAZE
        else:
            answered, _ = select_object([box for box in self._boxes if box.perceived], gaze[0], gaze[1], self._tolerance)
            looked_at, _ = select_object(self._boxes, gaze[0], gaze[1], self._tolerance)
            kind = QUERY_PERCEIVED if answered is not None else QUERY_NONE
        self._answer = {'kind': kind, 'until': now + QUERY_SHOW, 'object_id': answered.id if answered else None,
                        'x': gaze[0] if gaze else None, 'y': gaze[1] if gaze else None}
        self._write('gaze_queries.csv', ('wall_time', 'monotonic_s', 'gaze_x', 'gaze_y', 'answer', 'object_id', 'object_class',
                                         'distance_m', 'true_object_id', 'true_object_class', 'true_perceived'),
                    (_wall_time(), round(now, 4), round(gaze[0], 1) if gaze else '', round(gaze[1], 1) if gaze else '', kind,
                     answered.id if answered else '', answered.cls if answered else '',
                     round(answered.distance, 1) if answered else '', looked_at.id if looked_at else '',
                     looked_at.cls if looked_at else '', int(looked_at.perceived) if looked_at else ''))
        return kind

    def _watch_samples(self, now):
        last = self._receiver.last_arrival()
        flowing = last is not None and now - last <= STALE_AFTER
        if flowing and self._flowing is not True:
            logging.info('Gaze: samples are coming in')
            self._flowing = True
        elif not flowing and self._flowing is not False and now - (last or self._started) > NO_SAMPLES_WARN:
            logging.warning('Gaze: no samples for %.0f s, is gaze_bridge.py running?', NO_SAMPLES_WARN)
            self._flowing = False

    def log_fields(self):
        """The gaze_* columns of raw.csv for this frame."""
        state = self.state

        def number(value, digits):
            return '' if value is None else round(value, digits)
        return {'gaze_valid': int(state.valid), 'gaze_fixating': int(state.fixating),
                'gaze_x': number(state.x, 1), 'gaze_y': number(state.y, 1), 'gaze_pupil_mm': number(state.pupil, 3),
                'gaze_object_id': '' if state.object_id is None else state.object_id,
                'gaze_object_class': state.object_class or '', 'gaze_object_dist_m': number(state.distance, 1),
                'gaze_dwell_s': round(state.dwell, 3), 'gaze_confirmed': int(state.confirmed),
                'gaze_ambiguous': int(state.ambiguous), 'gaze_query': self._answer['kind'] if self._answer else ''}

    def _write(self, name, columns, row):
        with self._lock:
            if self._dir is None:
                return
            if name not in self._files:
                os.makedirs(self._dir, exist_ok=True)
                stream = open(os.path.join(self._dir, name), 'w', newline='', encoding='utf-8')
                writer = csv.writer(stream)
                writer.writerow(columns)
                self._files[name] = (stream, writer)
            self._files[name][1].writerow(row)

    def _log_sample(self, arrived, sample):
        self._write('gaze_samples.csv', ('wall_time', 'monotonic_s', 'device_us', 'x', 'y', 'pupil_mm'),
                    (_wall_time(), round(arrived, 4), sample.get('t', ''), sample.get('x', ''), sample.get('y', ''),
                     sample.get('pupil', '')))

    def _log_look(self, box, start, seen, ambiguous):
        self._write('gaze_events.csv', ('wall_time_end', 'start_monotonic_s', 'dwell_s', 'object_id', 'object_class',
                                        'distance_m', 'ambiguous'),
                    (_wall_time(), round(start, 4), round(seen - start, 3), box.id, box.cls, round(box.distance, 1),
                     int(ambiguous)))

    def _font(self, pygame, size):
        if size not in self._fonts:
            self._fonts[size] = pygame.font.SysFont(KOREAN_FONT, size)
        return self._fonts[size]

    def _draw_box(self, display, pygame, offset, box, color, width=BOX_WIDTH):
        pygame.draw.rect(display, color, (offset + box.left, box.top, box.right - box.left, box.bottom - box.top), width)

    def _middle_monitor(self, display):
        """Clips drawing to the middle monitor; its left edge in the window."""
        size = self._manager.screen_size
        offset = self._manager.screens // 2 * self._manager.screen_width
        display.set_clip((offset, 0, size[0], size[1]))
        return offset

    def render_perceived(self, display, pygame, classes):
        """--gaze-box: a box and class label on every perceived object of `classes`."""
        offset = self._middle_monitor(display)
        for box in self._boxes:
            if box.perceived and box.cls in classes:
                color = CLASS_COLORS[box.cls]
                self._draw_box(display, pygame, offset, box, color)
                if box.right - box.left >= LABEL_MIN_WIDTH:
                    label = self._font(pygame, 14).render(box.cls, True, color)
                    display.blit(label, (offset + box.left, box.top - label.get_height()))
        display.set_clip(None)

    def render_query(self, display, pygame):
        """--gaze-query: the answer on screen, if any. Nothing else: no boxes, no gaze cursor."""
        answer = self._answer
        if answer is None:
            return
        color = QUERY_COLORS[answer['kind']]
        size = self._manager.screen_size
        offset = self._middle_monitor(display)
        x, y = answer['x'], answer['y']
        if answer['kind'] == QUERY_PERCEIVED:
            box = next((box for box in self._boxes if box.id == answer['object_id']), None)
            if box is not None:
                self._draw_box(display, pygame, offset, box, color, BOX_WIDTH + 1)
                x, y = (box.left + box.right) / 2.0, box.top - QUERY_RING  # the text above the box, as it moves
        elif answer['kind'] == QUERY_NONE:
            pygame.draw.circle(display, color, (int(offset + x), int(y)), QUERY_RING, 3)
            y -= QUERY_RING * 2
        else:
            x, y = size[0] / 2.0, size[1] / 3.0
        text = self._font(pygame, 26).render(QUERY_TEXTS[answer['kind']], True, color)
        plate = pygame.Surface((text.get_width() + 16, text.get_height() + 6), pygame.SRCALPHA)
        plate.fill((0, 0, 0, 170))
        plate.blit(text, (8, 3))
        left = min(max(x - plate.get_width() / 2.0, 0), size[0] - plate.get_width())
        display.blit(plate, (offset + left, max(y - plate.get_height() / 2.0, 0)))
        display.set_clip(None)

    def render_debug(self, display, pygame):
        """--gaze-debug, for the experimenter: boxes and gaze on the middle monitor."""
        offset = self._manager.screens // 2 * self._manager.screen_width
        for box in self._boxes:
            color = (60, 230, 90) if box.id == self.state.object_id else (170, 170, 170) if box.perceived else (255, 80, 255)
            self._draw_box(display, pygame, offset, box, color, 1)
        if self.state.valid:
            center = (int(offset + self.state.x), int(self.state.y))
            pygame.draw.circle(display, (255, 220, 0), center, int(self._tolerance), 1)
            pygame.draw.circle(display, (255, 220, 0), center, 4)

    def close(self):
        self._judge.end()
        self._receiver.close()
        with self._lock:
            for stream, _ in self._files.values():
                stream.close()
            self._files = {}
            self._dir = None
        if self._receiver.received:
            logging.info('Gaze: %d samples, %.1f%% valid', self._receiver.received,
                         100.0 * self._receiver.valid / self._receiver.received)


def _wall_time():
    return datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
