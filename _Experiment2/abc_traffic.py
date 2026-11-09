#!/usr/bin/env python

"""
Scenario ABC in CARLA: the cars of a schedule (abc_schedule.py) driven along their courses.

Each car has a lane (1, 2, 3 of the document: the real highway lanes 2, 3, 4) and dx(t), metres
ahead of the ego car along the road. Every frame a car is driven towards its place: the ego car's
speed plus the course's own relative speed, corrected for the distance still missing, along the
middle of its lane (velocity and turn rate set directly, as EscortCars in carla_base.py: physics on,
so it rolls and sways like a car, but it does not wander). A car appears when its course begins and
is removed when it ends, both 65 m or more from the ego car.

Real lane 4 is lane 3's route shifted one lane width to the right: lane 4 itself leaves the loop at
the exits, the shifted line goes straight on.

"""

from __future__ import print_function

import hashlib
import logging
import math

import carla

import carla_base as base

LANE_SHIFT = {1: (2, 0.0), 2: (3, 0.0), 3: (3, base.LANE_WIDTH)}  # document lane -> (real route lane, m right)
GAIN = 0.8            # m/s per m missing from the car's place
CATCH_UP = 5.0        # m/s at most faster or slower than the course for that
ACCEL = 6.0           # m/s^2 at most the commanded speed changes by
CENTERING = 0.8       # m/s sideways per m off the middle of the lane
SIDEWAYS = 1.5        # m/s sideways at most
TURNING = 3.0         # deg/s turn rate per deg off the line to a point ahead
HISTORY_S = 6.0       # s of dx kept per car (approaching cars at a question)
BLUEPRINT_EXCLUDED = ('police', 'ambulance', 'firetruck', 'microlino', 'carlacola', 'cybertruck')


class Route(object):
    """A loop route as arrays: points, yaw, distance along it; locate() and pose()."""

    def __init__(self, waypoints, shift=0.0):
        self.points = []
        self.yaws = []
        for wp in waypoints:
            t = wp.transform
            loc = t.location
            if shift:
                right = t.get_right_vector()
                loc = carla.Location(loc.x + right.x * shift, loc.y + right.y * shift, loc.z)
            self.points.append((loc.x, loc.y, loc.z))
            self.yaws.append(t.rotation.yaw)
        self.s = [0.0]
        for (x0, y0, _), (x1, y1, _) in zip(self.points, self.points[1:]):
            self.s.append(self.s[-1] + math.hypot(x1 - x0, y1 - y0))
        x0, y0, _ = self.points[-1]
        x1, y1, _ = self.points[0]
        self.length = self.s[-1] + math.hypot(x1 - x0, y1 - y0)
        self.count = len(self.points)

    def locate(self, x, y, hint=None):
        """(index, s): the nearest segment's start and the distance along the route of (x, y)."""
        n = self.count
        if hint is None:
            candidates = range(n)
        else:
            candidates = [(hint + k) % n for k in range(-30, 31)]
        best = min(candidates, key=lambda i: (self.points[i][0] - x) ** 2 + (self.points[i][1] - y) ** 2)
        if hint is not None and (self.points[best][0] - x) ** 2 + (self.points[best][1] - y) ** 2 > 400.0:
            # lost: a wider search around the hint first (a search of all of it can land on the
            # other road where the figure-8 crosses itself)
            wide = [(hint + k) % n for k in range(-300, 301)]
            best = min(wide, key=lambda i: (self.points[i][0] - x) ** 2 + (self.points[i][1] - y) ** 2)
            if (self.points[best][0] - x) ** 2 + (self.points[best][1] - y) ** 2 > 400.0:
                return self.locate(x, y)
        # project onto the segment after it (or before it)
        for i in (best, (best - 1) % n):
            j = (i + 1) % n
            ax, ay, _ = self.points[i]
            bx, by, _ = self.points[j]
            dx, dy = bx - ax, by - ay
            seg = dx * dx + dy * dy
            if seg <= 0.0:
                continue
            u = ((x - ax) * dx + (y - ay) * dy) / seg
            if 0.0 <= u <= 1.0:
                return i, (self.s[i] + u * math.sqrt(seg)) % self.length
        return best, self.s[best]

    def index_at(self, s):
        """Index of the route point at or before distance s."""
        s %= self.length
        lo, hi = 0, self.count - 1
        while lo < hi:  # last index with self.s[i] <= s
            mid = (lo + hi + 1) // 2
            if self.s[mid] <= s:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def pose(self, s):
        """(location, yaw degrees, forward (x, y), right (x, y)) at distance s along the route."""
        s %= self.length
        i = self.index_at(s)
        j = (i + 1) % self.count
        seg = (self.s[j] if j else self.length) - self.s[i]
        u = (s - self.s[i]) / seg if seg > 0 else 0.0
        (ax, ay, az), (bx, by, bz) = self.points[i], self.points[j]
        x, y, z = ax + u * (bx - ax), ay + u * (by - ay), az + u * (bz - az)
        length = math.hypot(bx - ax, by - ay) or 1.0
        fx, fy = (bx - ax) / length, (by - ay) / length
        yaw = math.degrees(math.atan2(fy, fx))
        return carla.Location(x, y, z), yaw, (fx, fy), (-fy, fx)

    def wrap(self, ds):
        """A difference of distances along the loop, to -length/2 .. length/2."""
        return (ds + self.length / 2.0) % self.length - self.length / 2.0


class Course(object):
    """One car's course from the schedule."""

    def __init__(self, data, dt):
        self.id = data['id']
        self.kind = data['kind']          # bg, lead, event
        self.lane = data['lane']
        self.t0 = data['t0']
        self.dx = data['dx']
        self.dt = dt
        self.t1 = self.t0 + (len(self.dx) - 1) * dt
        self.lights = data.get('lights', [])
        self.event = data.get('event')    # S, SD, R for event cars
        self.color = data.get('color')
        self.f_event = data.get('f_event')

    def at(self, t):
        """(dx, relative speed m/s) at t; None outside the course."""
        if t < self.t0 - 1e-6 or t > self.t1 + 1e-6:
            return None
        u = (t - self.t0) / self.dt
        i = min(int(u), len(self.dx) - 2)
        f = u - i
        x = self.dx[i] + f * (self.dx[i + 1] - self.dx[i])
        v = (self.dx[i + 1] - self.dx[i]) / self.dt
        return x, v

    def light_flags(self, t):
        flags = 0
        for on, off, kind in self.lights:
            if on <= t < off:
                flags |= {'left': base.LEFT_BLINKER, 'right': base.RIGHT_BLINKER, 'brake': base.BRAKE_LIGHT}[kind]
        return flags


class ScriptedTraffic(object):
    """The cars of a schedule in the world."""

    def __init__(self, client, sim_world, carla_map, routes, schedule, config):
        self._client = client
        self._world = sim_world
        self._routes = {1: Route(routes[2]), 2: Route(routes[3]), 3: Route(routes[3], base.LANE_WIDTH)}
        self.ego_route = self._routes[2]
        self._courses = [Course(c, schedule['dt']) for c in schedule['cars']]
        self._courses.sort(key=lambda c: c.t0)
        self._next = 0                 # first course not started yet
        self.cars = {}                 # course id -> dict(actor, course, hint, speed, lights, history)
        self._ego_hint = None
        self._ref_hint = {}
        library = sim_world.get_blueprint_library()
        self._event_blueprint = library.find(config['event_vehicle'])
        self._blueprints = sorted(
            [bp for bp in library.filter('vehicle.*')
             if bp.has_attribute('base_type') and bp.get_attribute('base_type').as_str() == 'car'
             and not any(word in bp.id for word in BLUEPRINT_EXCLUDED)], key=lambda bp: bp.id)
        self.log = []                  # (t, course id, what) appearances and removals for the event log

    # -- where things are -----------------------------------------------------------------------

    def start(self, ego_index):
        """The ego car is at route point ego_index (of its lane): where the searches begin."""
        self._ego_hint = ego_index
        for lane in (1, 2, 3):
            self._ref_hint[lane] = min(ego_index, self._routes[lane].count - 1)

    def ego_s(self, ego_transform):
        loc = ego_transform.location
        self._ego_hint, s = self.ego_route.locate(loc.x, loc.y, self._ego_hint)
        return s

    def ref_s(self, lane, ego_transform):
        """Distance along `lane`'s route level with the ego car."""
        route = self._routes[lane]
        loc = ego_transform.location
        if lane == 1:  # one lane width to the left of the ego car
            right = ego_transform.get_right_vector()
            x, y = loc.x - right.x * base.LANE_WIDTH, loc.y - right.y * base.LANE_WIDTH
        else:
            x, y = loc.x, loc.y
        self._ref_hint[lane], s = route.locate(x, y, self._ref_hint.get(lane))
        return s

    def dx_of(self, car, refs):
        """Measured dx of a car (m ahead of the ego car along its lane)."""
        route = self._routes[car['course'].lane]
        loc = car['actor'].get_location()
        car['hint'], s = route.locate(loc.x, loc.y, car['hint'])
        return route.wrap(s - refs[car['course'].lane]), s

    # -- per frame ------------------------------------------------------------------------------

    def tick(self, t, ego, dt_real):
        """Spawn, drive and remove the cars for simulation time t. Returns {id: (lane, dx, dv km/h)}."""
        transform = ego.get_transform()
        velocity = ego.get_velocity()
        forward = transform.get_forward_vector()
        ego_speed = velocity.x * forward.x + velocity.y * forward.y  # m/s along its heading
        refs = {lane: self.ref_s(lane, transform) for lane in (1, 2, 3)}
        while self._next < len(self._courses) and self._courses[self._next].t0 <= t + 1e-6:
            course = self._courses[self._next]
            self._next += 1
            if course.t1 >= t:
                self._pending(course)
        for cid in list(self.cars):
            car = self.cars[cid]
            if car['actor'] is None:
                self._spawn(car, t, refs, ego_speed)
            elif t > car['course'].t1:
                self._remove(cid, t, 'course end')
        state = {}
        for cid, car in list(self.cars.items()):
            if car['actor'] is None:
                continue
            if car.get('fresh'):  # spawned this frame: the client sees it from the next step on
                car['fresh'] = False
                continue
            dx, s = self.dx_of(car, refs)
            car['history'].append((t, dx))
            while car['history'] and car['history'][0][0] < t - HISTORY_S:
                car['history'].pop(0)
            # relative speed along the road, over the last half second
            t_old, x_old = next(((th, xh) for th, xh in car['history'] if th >= t - 0.5), car['history'][0])
            dv = (dx - x_old) / (t - t_old) * 3.6 if t - t_old > 0.05 else 0.0
            state[cid] = (car['course'].lane, dx, dv)
            planned = car['course'].at(t)
            if planned is None:
                continue
            self._drive(car, planned, s, refs, ego_speed, dt_real)
            lights = car['course'].light_flags(t)
            if lights != car['lights']:
                car['actor'].set_light_state(carla.VehicleLightState(lights))
                car['lights'] = lights
                self.log.append((t, cid, 'lights %s' % _light_names(lights)))
        return state

    def _pending(self, course):
        self.cars[course.id] = {'actor': None, 'course': course, 'hint': None, 'speed': None, 'lights': 0,
                                'history': []}

    def _blueprint(self, course):
        if course.kind == 'event':
            blueprint = self._event_blueprint
            color = course.color
        else:  # a fixed choice per car id: the same cars every run
            digest = int(hashlib.md5(course.id.encode('ascii')).hexdigest(), 16)
            blueprint = self._blueprints[digest % len(self._blueprints)]
            color = None
            if blueprint.has_attribute('color'):
                values = blueprint.get_attribute('color').recommended_values
                color = values[(digest // 7) % len(values)] if values else None
        if color and blueprint.has_attribute('color'):
            blueprint.set_attribute('color', color)
        blueprint.set_attribute('role_name', 'npc')
        return blueprint

    def _spawn(self, car, t, refs, ego_speed):
        course = car['course']
        planned = course.at(t)
        if planned is None:
            return
        route = self._routes[course.lane]
        loc, yaw, (fx, fy), _ = route.pose(refs[course.lane] + planned[0])
        transform = carla.Transform(carla.Location(loc.x, loc.y, loc.z + 0.3), carla.Rotation(yaw=yaw))
        actor = self._world.try_spawn_actor(self._blueprint(course), transform)
        if actor is None:
            return  # the place is taken: next frame
        speed = ego_speed + planned[1]
        actor.set_target_velocity(carla.Vector3D(fx * speed, fy * speed, 0.0))
        car['actor'] = actor
        car['fresh'] = True
        car['speed'] = speed
        car['hint'] = route.index_at(refs[course.lane] + planned[0])  # not a full search: the loop crosses itself
        self.log.append((t, course.id, 'appears at dx %.1f m' % planned[0]))

    def _drive(self, car, planned, s, refs, ego_speed, dt_real):
        course = car['course']
        route = self._routes[course.lane]
        actor = car['actor']
        dx_plan, dv_plan = planned
        missing = route.wrap(refs[course.lane] + dx_plan - s)
        goal = ego_speed + dv_plan + max(-CATCH_UP, min(GAIN * missing, CATCH_UP))
        goal = max(goal, 0.0)
        step = ACCEL * max(dt_real, 1e-3)
        car['speed'] += max(-step, min(goal - car['speed'], step))
        speed = car['speed']
        transform = actor.get_transform()
        location = transform.location
        here, _, (fx, fy), (rx, ry) = route.pose(s)
        drift = (here.x - location.x) * rx + (here.y - location.y) * ry
        side = max(-SIDEWAYS, min(CENTERING * drift, SIDEWAYS))
        ahead, _, _, _ = route.pose(s + max(8.0, speed * 0.8))
        heading = math.degrees(math.atan2(ahead.y - location.y, ahead.x - location.x))
        turn = (heading - transform.rotation.yaw + 180.0) % 360.0 - 180.0
        actor.set_target_velocity(carla.Vector3D(fx * speed + rx * side, fy * speed + ry * side,
                                                 actor.get_velocity().z))
        actor.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, TURNING * turn))

    def _remove(self, cid, t, why):
        car = self.cars.pop(cid)
        if car['actor'] is not None:
            base.destroy_actors(self._client, [car['actor']])
            self.log.append((t, cid, 'removed (%s)' % why))

    # -- questions ---------------------------------------------------------------------------------

    def snapshot(self, t, window):
        """[(id, lane, dx, dx `window` s before or None)] of the cars in the world now."""
        result = []
        for cid, car in self.cars.items():
            if car['actor'] is None or not car['history']:
                continue
            dx = car['history'][-1][1]
            t_h, x_h = min(car['history'], key=lambda item: abs(item[0] - (t - window)))
            before = x_h if abs(t_h - (t - window)) < 0.5 else None  # a car that appeared since: none
            result.append((cid, car['course'].lane, dx, before))
        return result

    def destroy(self):
        actors = [car['actor'] for car in self.cars.values() if car['actor'] is not None]
        if actors:
            base.destroy_actors(self._client, actors)
        self.cars = {}


def _light_names(flags):
    names = [name for flag, name in ((base.LEFT_BLINKER, 'left'), (base.RIGHT_BLINKER, 'right'),
                                     (base.BRAKE_LIGHT, 'brake')) if flags & flag]
    return '+'.join(names) or 'off'
