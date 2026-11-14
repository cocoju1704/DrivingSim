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

A course may change lanes once (lane_change [time, to lane]: an S car, since 2026-11-13, overtakes and
moves over, lane 1 to lane 0 or lane 3 to lane 2): from that time it is driven along the other lane's
route, steer_along takes it across (SIDEWAYS at most) with its turn signal (the course's lights).

The TOR's two cars are not courses (the driver drives after it): TorScene puts them in the world and
drives the approaching one at its own speed (see there).

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
# patrol_2021: its body and wheels are drawn ~0.3 m above the road (the actor itself is on it): a floating car
BLUEPRINT_EXCLUDED = ('police', 'ambulance', 'firetruck', 'microlino', 'carlacola', 'cybertruck', 'patrol_2021')


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
        self.lane = data['lane']          # the lane it is in now (a lane change moves it: ScriptedTraffic)
        self.first_lane = data['lane']
        self.t0 = data['t0']
        self.dx = data['dx']
        self.dt = dt
        self.t1 = self.t0 + (len(self.dx) - 1) * dt
        self.lights = data.get('lights', [])
        self.event = data.get('event')    # S, SD, R for event cars
        self.color = data.get('color')
        self.f_event = data.get('f_event')
        self.f_spans = data.get('f_spans')         # an F's lead car: [[brake, gone]]
        self.lane_change = data.get('lane_change')   # [time, to lane] or None

    def lane_at(self, t):
        if self.lane_change and t >= self.lane_change[0] - 1e-6:
            return self.lane_change[1]
        return self.first_lane

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
        # schedule lanes 1-3 are the road's lanes 2-4; lane 0 (the road's lane 1, next to the median:
        # scenery, outside the SAGAT grid) one lane width left of lane 1 (it runs the whole loop)
        self._routes = {0: Route(routes[2], -base.LANE_WIDTH), 1: Route(routes[2]), 2: Route(routes[3]),
                        3: Route(routes[3], base.LANE_WIDTH)}
        self.ego_route = self._routes[2]
        self._courses = [Course(c, schedule['dt']) for c in schedule['cars']]
        self._courses.sort(key=lambda c: c.t0)
        self._next = 0                 # first course not started yet
        self.cars = {}                 # course id -> dict(actor, course, hint, speed, lights, history)
        self._ego_hint = None
        self._ref_hint = {}
        library = sim_world.get_blueprint_library()
        self._event_blueprint = library.find(config['event_vehicle'])
        f_template = config.get('templates', {}).get('F', {})
        self._f_blueprint = library.find(f_template['lead_vehicle']) if f_template.get('lead_vehicle') else None
        self._f_color = f_template.get('lead_color')
        # background cars: bright, saturated colours (the recommended ones are mostly dark grey, black
        # and silver: hard to tell apart in the mirrors and at a SAGAT question)
        self._colors = config.get('background', {}).get('colors') or None
        self._blueprints = sorted(
            [bp for bp in library.filter('vehicle.*')
             if bp.has_attribute('base_type') and bp.get_attribute('base_type').as_str() == 'car'
             and not any(word in bp.id for word in BLUEPRINT_EXCLUDED)], key=lambda bp: bp.id)
        self.log = []                  # (t, course id, what) appearances and removals for the event log

    # -- where things are -----------------------------------------------------------------------

    def start(self, ego_index):
        """The ego car is at route point ego_index (of its lane): where the searches begin."""
        self._ego_hint = ego_index
        for lane in self._routes:
            self._ref_hint[lane] = min(ego_index, self._routes[lane].count - 1)

    def ego_s(self, ego_transform):
        loc = ego_transform.location
        self._ego_hint, s = self.ego_route.locate(loc.x, loc.y, self._ego_hint)
        return s

    def ref_s(self, lane, ego_transform):
        """Distance along `lane`'s route level with the ego car."""
        route = self._routes[lane]
        loc = ego_transform.location
        if lane in (0, 1):  # one (two) lane widths to the left of the ego car
            right = ego_transform.get_right_vector()
            w = base.LANE_WIDTH * (2 - lane)
            x, y = loc.x - right.x * w, loc.y - right.y * w
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

    def _frame(self, car, planned, refs, ego_speed, lag, ref_speed):
        """(refs, speed) a car is driven relative to: the ego car, or while it has fallen behind for an
        F (lag m, abc_follow) the place the schedule has it at, at ref_speed - the other cars keep their
        speeds - but the lane 2 cars behind it (they brake with it)."""
        # an F's lead car is never one of those, though its planned dx dips below 0 after its brake
        # (2026-11-13: -25 km/h for 3 s; the ego car brakes too, the real gap stays ~8 m and more)
        if lag and not (car['course'].lane == 2 and planned[0] < 0 and not car['course'].f_spans):
            return {lane: s + lag for lane, s in refs.items()}, ref_speed
        return refs, ego_speed

    def tick(self, t, ego, dt_real, lag=0.0, ref_speed=None):
        """Spawn, drive and remove the cars for simulation time t. Returns {id: (lane, dx, dv km/h)}:
        dx measured from the ego car itself. lag, ref_speed: see _frame."""
        transform = ego.get_transform()
        velocity = ego.get_velocity()
        forward = transform.get_forward_vector()
        ego_speed = velocity.x * forward.x + velocity.y * forward.y  # m/s along its heading
        if ref_speed is None:
            ref_speed = ego_speed
        refs = {lane: self.ref_s(lane, transform) for lane in self._routes}
        while self._next < len(self._courses) and self._courses[self._next].t0 <= t + 1e-6:
            course = self._courses[self._next]
            self._next += 1
            if course.t1 >= t:
                self._pending(course)
        for cid in list(self.cars):
            car = self.cars[cid]
            lane = car['course'].lane_at(t)
            if lane != car['course'].lane:   # an S car moves over: from now on along that lane's route
                car['course'].lane = lane
                planned = car['course'].at(t)
                if car['actor'] is not None and planned is not None:
                    car['hint'] = self._routes[lane].index_at(refs[lane] + planned[0])
                    self.log.append((t, cid, 'lane change to lane %d' % lane))
            if car['actor'] is None:
                planned = car['course'].at(t)
                if planned is not None:
                    self._spawn(car, t, *self._frame(car, planned, refs, ego_speed, lag, ref_speed))
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
            self._drive(car, planned, s, *self._frame(car, planned, refs, ego_speed, lag, ref_speed), dt_real=dt_real)
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
        elif course.f_spans and self._f_blueprint is not None:
            # an F's lead car (2026-11-14): the model whose brake light shows most (config F lead_vehicle;
            # 1114 A-F1's Citroen C3 showed none)
            blueprint = self._f_blueprint
            color = self._f_color
        else:  # a fixed choice per car id: the same cars every run
            digest = int(hashlib.md5(course.id.encode('ascii')).hexdigest(), 16)
            blueprint = self._blueprints[digest % len(self._blueprints)]
            color = None
            if blueprint.has_attribute('color'):
                values = self._colors or blueprint.get_attribute('color').recommended_values
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
        steer_along(actor, route, s, car['speed'])

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


def steer_along(actor, route, s, speed):
    """Drives `actor` (at distance s along `route`) at `speed` m/s along the middle of the route's lane:
    its velocity and turn rate set directly."""
    transform = actor.get_transform()
    location = transform.location
    here, _, (fx, fy), (rx, ry) = route.pose(s)
    drift = (here.x - location.x) * rx + (here.y - location.y) * ry
    side = max(-SIDEWAYS, min(CENTERING * drift, SIDEWAYS))
    ahead, _, _, _ = route.pose(s + max(8.0, speed * 0.8))
    heading = math.degrees(math.atan2(ahead.y - location.y, ahead.x - location.x))
    turn = (heading - transform.rotation.yaw + 180.0) % 360.0 - 180.0
    actor.set_target_velocity(carla.Vector3D(fx * speed + rx * side, fy * speed + ry * side, actor.get_velocity().z))
    actor.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, TURNING * turn))


HAZARD_LIGHTS = base.LEFT_BLINKER | base.RIGHT_BLINKER
HAZARD_FOLLOW_GAP = 20.0   # m: after yielding, the approaching car stays this far behind the ego car
HAZARD_ACCEL = 2.0         # m/s^2 it speeds up again at
HAZARD_GONE_M = 250.0      # m ahead or behind: removed


class TorScene(object):
    """The TOR's cars (Notion 시나리오 ABC, 2): the approaching car in the unsafe lane and the stopped
    car in lane 2. Both at fixed places of the road, not relative to the ego car: from the TOR on the
    driver drives.

        hazard()    T-9: dx -80 m in the unsafe lane, no turn signal; until the alert it comes up at
                    +20 km/h relative to the ego car (a course: -80 m + 20 km/h x the time, whatever
                    the ego car's speed: after the curve before the loop's long straight it is still
                    speeding up), so it is 30 m behind at T; release() at T: from then on it keeps its
                    speed (next to the ego car ~5.4 s later if that keeps its own)
        obstacle()  T-3: in lane 2, standing (hand brake), hazard lights on: 297 m ahead at 95 km/h;
                    at another speed (still speeding up after the curve) where it makes the same TTC at
                    T, ~8.25 s centre to centre, 8.0 s as logged (bumper to bumper; 270 m, 7.2 / 7.0 s before 2026-11-13)
        tick()      drives the approaching car; yield(): once the ego car has come into its lane less
                    than 10 m ahead of it, it brakes (6 m/s^2) and stays HAZARD_FOLLOW_GAP behind
    """

    def __init__(self, traffic, event, template, event_vehicle):
        self._traffic = traffic
        self.event = event
        self.template = template
        self.unsafe = event['unsafe_lane']
        self.safe = event['safe_lane']
        self.hazard_actor = self.obstacle_actor = None
        self.hazard_s = self.obstacle_s = None   # along their lane routes (the obstacle: lane 2 = ego route)
        self.hazard_length = self.obstacle_length = 4.8
        self.obstacle_spawn_dx = None
        self.hazard_width = self.obstacle_width = 1.9
        self._hint = None
        self._speed = None        # m/s, the approaching car's
        self._cruise = None       # m/s, its own speed from the alert on (None: still on its course)
        self._course = None       # (t, dx) it appeared at
        self.yielding = False
        self._event_vehicle = event_vehicle

    def _blueprint(self, settings, fallback):
        library = self._traffic._world.get_blueprint_library()  # pylint: disable=protected-access
        blueprint = library.find(settings.get('blueprint') or fallback)
        blueprint.set_attribute('role_name', 'npc')
        if settings.get('color') and blueprint.has_attribute('color'):
            blueprint.set_attribute('color', settings['color'])
        return blueprint

    def _place(self, settings, fallback, lane, s, speed):
        route = self._traffic._routes[lane]  # pylint: disable=protected-access
        loc, yaw, (fx, fy), _ = route.pose(s)
        actor = self._traffic._world.try_spawn_actor(  # pylint: disable=protected-access
            self._blueprint(settings, fallback),
            carla.Transform(carla.Location(loc.x, loc.y, loc.z + 0.3), carla.Rotation(yaw=yaw)))
        if actor is not None and speed:
            actor.set_target_velocity(carla.Vector3D(fx * speed, fy * speed, 0.0))
        return actor

    def hazard(self, t, ego_transform, ego_speed):
        """Puts the approaching car in; False if its place is taken (try again next frame)."""
        settings = self.template['hazard_vehicle']
        s = self._traffic.ref_s(self.unsafe, ego_transform) + settings['spawn_dx_m']
        speed = ego_speed + settings['dv_kmh'] / 3.6
        actor = self._place(settings, self._event_vehicle, self.unsafe, s, speed)
        if actor is None:
            return False
        self.hazard_actor, self.hazard_s, self._speed = actor, s, speed
        self._course = (t, settings['spawn_dx_m'])
        self._hint = self._traffic._routes[self.unsafe].index_at(s)  # pylint: disable=protected-access
        extent = actor.bounding_box.extent
        self.hazard_length, self.hazard_width = 2.0 * extent.x, 2.0 * extent.y
        logging.info('TOR: approaching car in lane %d, %.0f m behind, %.0f km/h', self.unsafe,
                     -settings['spawn_dx_m'], speed * 3.6)
        return True

    def obstacle(self, ego_s, ego_speed, nominal_speed, ego_accel=0.0, lead_s=3.0):
        """Puts the stopped car in lane 2, lead_s before the alert, where it is as many seconds ahead
        at the alert as spawn_dx_m would be at nominal_speed m/s (the ego car's speed then from its
        speed and acceleration now); False if its place is taken. self.obstacle_spawn_dx: how far
        ahead it went."""
        settings = self.template['obstacle']
        v_alert = max(ego_speed + max(ego_accel, 0.0) * lead_s, 1.0)
        # its TTC at the alert as designed (8.25 s: 297 m - 3 s at 95 km/h, 8.0 s bumper to bumper as logged; 7.2 s before 2026-11-13), also at a slower cruise speed
        nominal_speed = settings.get('spawn_nominal_kmh', nominal_speed * 3.6) / 3.6
        ttc = settings['spawn_dx_m'] / nominal_speed - lead_s
        self.obstacle_spawn_dx = ttc * v_alert + lead_s * (ego_speed + v_alert) / 2.0
        s = ego_s + self.obstacle_spawn_dx
        actor = self._place(settings, 'vehicle.tesla.model3', 2, s, 0.0)
        if actor is None:
            return False
        actor.apply_control(carla.VehicleControl(hand_brake=True, brake=1.0))
        if settings.get('hazard_lights', True):
            actor.set_light_state(carla.VehicleLightState(HAZARD_LIGHTS))
        self.obstacle_actor, self.obstacle_s = actor, s % self._traffic.ego_route.length
        extent = actor.bounding_box.extent
        self.obstacle_length, self.obstacle_width = 2.0 * extent.x, 2.0 * extent.y
        logging.info('TOR: stopped car %.0f m ahead in lane 2', self.obstacle_spawn_dx)
        return True

    def hazard_dx(self, ego_transform):
        """m the approaching car is ahead of the ego car (< 0 behind), centre to centre, along its lane."""
        if self.hazard_actor is None:
            return None
        route = self._traffic._routes[self.unsafe]  # pylint: disable=protected-access
        return route.wrap(self.hazard_s - self._traffic.ref_s(self.unsafe, ego_transform))

    def obstacle_dx(self, ego_s):
        if self.obstacle_actor is None:
            return None
        return self._traffic.ego_route.wrap(self.obstacle_s - ego_s)

    def release(self):
        """The alert: from now on the approaching car keeps the speed it has."""
        if self._cruise is None and self._speed is not None:
            self._cruise = self._speed

    def yield_to(self):
        """The ego car has come into its lane just ahead: from now on it brakes and keeps behind."""
        self.yielding = True

    def tick(self, t, ego_transform, ego_speed, dt):
        """Drives the approaching car. Returns its dx (None if there is none)."""
        actor = self.hazard_actor
        if actor is None:
            return None
        route = self._traffic._routes[self.unsafe]  # pylint: disable=protected-access
        loc = actor.get_location()
        self._hint, self.hazard_s = route.locate(loc.x, loc.y, self._hint)
        dx = self.hazard_dx(ego_transform)
        if abs(dx) > HAZARD_GONE_M:
            self._traffic._client.apply_batch([carla.command.DestroyActor(actor.id)])  # pylint: disable=protected-access
            self.hazard_actor = None
            logging.info('TOR: the approaching car is gone (%.0f m)', dx)
            return None
        dt = max(dt, 1e-3)
        settings = self.template['hazard_vehicle']
        if self._cruise is None:  # its course: dx -80 m + 20 km/h x the time, relative to the ego car
            planned = self._course[1] + settings['dv_kmh'] / 3.6 * (t - self._course[0])
            goal = ego_speed + settings['dv_kmh'] / 3.6 + max(-CATCH_UP, min(GAIN * (planned - dx), CATCH_UP))
        else:
            goal = self._cruise
        if self.yielding and dx < 0:  # behind the ego car: stay HAZARD_FOLLOW_GAP behind its bumper
            gap = -dx - (self.hazard_length + 4.8) / 2.0
            goal = max(0.0, min(goal, ego_speed + 0.5 * (gap - HAZARD_FOLLOW_GAP)))
        if self._cruise is None:  # on its course: as the cars of the schedule
            self._speed += max(-ACCEL * dt, min(goal - self._speed, ACCEL * dt))
        elif goal < self._speed:
            self._speed = max(goal, self._speed - settings['yield_decel_mps2'] * dt)
        else:
            self._speed = min(goal, self._speed + HAZARD_ACCEL * dt)
        steer_along(actor, route, self.hazard_s, self._speed)
        if self.yielding and self._cruise is not None and self._speed < self._cruise - 0.5:
            actor.set_light_state(carla.VehicleLightState(base.BRAKE_LIGHT))
        else:
            actor.set_light_state(carla.VehicleLightState(0))
        return dx

    @property
    def hazard_speed(self):
        return self._speed

    def actors(self):
        return [a for a in (self.hazard_actor, self.obstacle_actor) if a is not None]

    def destroy(self):
        actors = self.actors()
        if actors:
            base.destroy_actors(self._traffic._client, actors)  # pylint: disable=protected-access
        self.hazard_actor = self.obstacle_actor = None


class TorCar(object):
    """One more car of the TOR (2026-11-14), driven by TorCars: a lane (its route), where it is along it,
    its speed. Its lane can change (steer_along takes it across, SIDEWAYS at most)."""

    def __init__(self, traffic, name, actor, lane, s, speed):
        self.traffic, self.name, self.actor, self.lane = traffic, name, actor, lane
        self.s, self.speed = s, speed
        self.hint = traffic._routes[lane].index_at(s)  # pylint: disable=protected-access
        extent = actor.bounding_box.extent
        self.length, self.width = 2.0 * extent.x, 2.0 * extent.y
        self.fresh = True
        self.light = 0
        self.blink = 0      # turn signal flags (moving over)

    def route(self):
        return self.traffic._routes[self.lane]  # pylint: disable=protected-access

    def locate(self):
        loc = self.actor.get_location()
        self.hint, self.s = self.route().locate(loc.x, loc.y, self.hint)

    def dx(self, ego_transform):
        """m ahead of the ego car (< 0 behind), centre to centre, along its lane."""
        return self.route().wrap(self.s - self.traffic.ref_s(self.lane, ego_transform))

    def move_to(self, lane, ego_transform):
        """From now on along `lane`'s route (it moves across)."""
        dx = self.dx(ego_transform)
        self.lane = lane
        self.s = self.traffic.ref_s(lane, ego_transform) + dx
        self.hint = self.route().index_at(self.s)

    def drive(self, goal, dt, accel=2.5, decel=7.0):
        step = self.speed + max(-decel * dt, min(goal - self.speed, accel * dt))
        light = base.BRAKE_LIGHT if step < self.speed - 0.5 * dt else 0
        self.speed = max(0.0, step)
        steer_along(self.actor, self.route(), self.s, self.speed)
        if (light | self.blink) != self.light:
            self.light = light | self.blink
            self.actor.set_light_state(carla.VehicleLightState(self.light))


class TorCars(object):
    """The TOR's cars behind in the ego car's lane and in the safe lane, and the lane 0 traffic
    (2026-11-14; config TOR rear_own, rear_safe, lane0). The approaching car of the unsafe lane is
    TorScene's.

    rear_own (lane 2): from spawn_dx_m behind at spawn_rel_s, comes up to dx_at_alert_m by the alert
        (a course relative to the ego car, as the approaching car's); then it urges on: its gap to the
        ego car's bumper down to urge_gap_m over urge_s, never nearer than min_gap_m (it brakes with the
        ego car). evade(lane): it moves over to that lane once it is free of the approaching car
        (evade_clear_m around it), then on at its speed at the alert.
    rear_safe (the safe lane): comes up to dx_at_alert_m by the alert, then keeps the speed it has;
        once the ego car is in its lane ahead of it, it follows at follow_gap_m (min_gap_m at least):
        close behind, no threat.
    lane 0: every every_s a car spawn_dx_m behind at speed_kmh, a constant speed whatever the ego car
        does, gone beyond gone_dx_m.
    Every car also keeps behind any car ahead in its lane (the approaching car, the ego car, each other)."""

    def __init__(self, traffic, scene, template, t_alert, rng):
        self.traffic, self.scene, self.tt = traffic, scene, template
        self.t_alert = t_alert
        self.rng = rng
        self.own = self.safe = None
        self.lane0 = []
        self._own_course = self._safe_course = None
        self._own_cruise = self._safe_cruise = None
        self.own_target = None       # the lane rear_own is to move over to
        self.own_evaded = None       # (t, lane) it went over
        self._own_gap0 = None
        self._next0 = None
        self._count0 = 0

    def _spawn(self, name, settings, lane, ego_transform, speed):
        s = self.traffic.ref_s(lane, ego_transform) + settings['spawn_dx_m']
        route = self.traffic._routes[lane]  # pylint: disable=protected-access
        loc, yaw, (fx, fy), _ = route.pose(s)
        library = self.traffic._world.get_blueprint_library()  # pylint: disable=protected-access
        blueprint = library.find(settings.get('blueprint') or 'vehicle.tesla.model3')
        blueprint.set_attribute('role_name', 'npc')
        if settings.get('color') and blueprint.has_attribute('color'):
            blueprint.set_attribute('color', settings['color'])
        actor = self.traffic._world.try_spawn_actor(  # pylint: disable=protected-access
            blueprint, carla.Transform(carla.Location(loc.x, loc.y, loc.z + 0.3), carla.Rotation(yaw=yaw)))
        if actor is None:
            return None
        actor.set_target_velocity(carla.Vector3D(fx * speed, fy * speed, 0.0))
        return TorCar(self.traffic, name, actor, lane, s, speed)

    def spawn_rear(self, t, ego_transform, ego_speed):
        """The two cars behind (spawn_rel_s): True once both are there."""
        for key in ('rear_own', 'rear_safe'):
            settings = self.tt.get(key)
            if not settings or getattr(self, key[5:]) is not None or t < self.t_alert + settings['spawn_rel_s']:
                continue
            lane = 2 if key == 'rear_own' else self.scene.safe
            v_rel = (settings['dx_at_alert_m'] - settings['spawn_dx_m']) / max(self.t_alert - t, 1.0)
            car = self._spawn(key, settings, lane, ego_transform, ego_speed + v_rel)
            if car is not None:
                setattr(self, key[5:], car)
                course = (t, settings['spawn_dx_m'], v_rel)
                if key == 'rear_own':
                    self._own_course = course
                else:
                    self._safe_course = course
                logging.info('TOR: car behind in lane %d, %.0f m behind', lane, -settings['spawn_dx_m'])

    def spawn_lane0(self, t, ego_transform):
        settings = self.tt.get('lane0')
        if not settings:
            return
        if self._next0 is None:
            self._next0 = t
        if t < self._next0:
            return
        car = self._spawn('lane0-%d' % (self._count0 + 1), settings, 0, ego_transform, settings['speed_kmh'] / 3.6)
        if car is not None:
            self._count0 += 1
            self.lane0.append(car)
            self._next0 = t + self.rng.uniform(*settings['every_s'])

    def cars(self):
        return [c for c in [self.own, self.safe] + self.lane0 if c is not None]

    def evade(self, lane):
        if self.own is not None and self.own_target is None and self.own_evaded is None:
            self.own_target = lane

    def _ahead(self, car, ego_transform, ego_lanes, ego_length, ego_speed):
        """(bumper gap m, speed m/s) of the nearest car ahead in its lane, or None."""
        best = None
        mine = car.dx(ego_transform)
        others = []
        if car.lane in ego_lanes:
            others.append((0.0, ego_length, ego_speed))
        hazard = self.scene.hazard_actor
        if hazard is not None and self.scene.unsafe == car.lane:
            dx = self.scene.hazard_dx(ego_transform)
            if dx is not None:
                others.append((dx, self.scene.hazard_length, self.scene.hazard_speed or 0.0))
        for other in self.cars():
            if other is not car and other.lane == car.lane and not other.fresh:
                others.append((other.dx(ego_transform), other.length, other.speed))
        for dx, length, speed in others:
            if dx > mine:
                gap = dx - mine - (length + car.length) / 2.0
                if best is None or gap < best[0]:
                    best = (gap, speed)
        return best

    def tick(self, t, ego_transform, ego_speed, ego_lanes, ego_length, dt):
        dt = max(dt, 1e-3)
        for car in self.cars():
            if car.fresh:   # spawned this frame: the client sees it from the next one
                car.fresh = False
                continue
            car.locate()
            dx = car.dx(ego_transform)
            if car is self.own:
                goal = self._tick_own(t, car, dx, ego_transform, ego_speed, ego_lanes, ego_length)
            elif car is self.safe:
                goal = self._tick_safe(t, car, dx, ego_speed, ego_lanes, ego_length)
            else:
                goal = self.tt['lane0']['speed_kmh'] / 3.6
            ahead = self._ahead(car, ego_transform, ego_lanes, ego_length, ego_speed)
            if ahead is not None:   # never into the car ahead: 1 s and min 6 m behind it
                gap, v_lead = ahead
                keep = max(6.0, 1.0 * car.speed)
                goal = min(goal, max(0.0, v_lead + 0.5 * (gap - keep)))
            car.drive(goal, dt)
        low, high = self.tt.get('lane0', {}).get('gone_dx_m', (-120, 250))
        for car in list(self.lane0):
            if not car.fresh and not low <= car.dx(ego_transform) <= high:
                base.destroy_actors(self.traffic._client, [car.actor])  # pylint: disable=protected-access
                self.lane0.remove(car)

    def _course_goal(self, course, t, dx, ego_speed):
        t0, x0, v_rel = course
        planned = x0 + v_rel * (t - t0)
        return ego_speed + v_rel + max(-CATCH_UP, min(GAIN * (planned - dx), CATCH_UP))

    def _tick_own(self, t, car, dx, ego_transform, ego_speed, ego_lanes, ego_length):
        settings = self.tt['rear_own']
        if t < self.t_alert:
            return self._course_goal(self._own_course, t, dx, ego_speed)
        if self._own_cruise is None:
            self._own_cruise = car.speed
            self._own_gap0 = -dx - (ego_length + car.length) / 2.0
        if self.own_target is not None and self.own_evaded is None:
            # over to the other lane once the approaching car is not beside it there
            clear = True
            if self.scene.hazard_actor is not None and self.scene.unsafe == self.own_target:
                gap = self.scene.hazard_dx(ego_transform) - dx
                low, high = settings['evade_clear_m']
                clear = not low <= gap <= high
            if clear:
                car.move_to(self.own_target, ego_transform)
                self.own_evaded = (t, self.own_target)
                car.blink = base.LEFT_BLINKER if self.own_target == 1 else base.RIGHT_BLINKER
                logging.info('TOR: the car behind moves over to lane %d', self.own_target)
        if self.own_evaded is not None:
            return max(self._own_cruise, car.speed)
        # behind the ego car in lane 2: its gap down to urge_gap_m over urge_s, never below min_gap_m
        share = min(1.0, (t - self.t_alert) / max(settings['urge_s'], 0.1))
        wanted = self._own_gap0 + (settings['urge_gap_m'] - self._own_gap0) * share
        gap = -dx - (ego_length + car.length) / 2.0
        goal = ego_speed + 0.5 * (gap - max(wanted, settings['min_gap_m']))
        return max(0.0, min(goal, ego_speed + 15.0 / 3.6))

    def _tick_safe(self, t, car, dx, ego_speed, ego_lanes, ego_length):
        settings = self.tt['rear_safe']
        if t < self.t_alert:
            return self._course_goal(self._safe_course, t, dx, ego_speed)
        if self._safe_cruise is None:
            self._safe_cruise = car.speed
        if car.lane in ego_lanes and dx < 0:
            # the driver is in its lane ahead: close behind at follow_gap_m, at least min_gap_m
            gap = -dx - (ego_length + car.length) / 2.0
            goal = ego_speed + 0.4 * (gap - settings['follow_gap_m'])
            if gap < settings['min_gap_m']:
                goal = min(goal, ego_speed - 1.0)
            return max(0.0, min(goal, self._safe_cruise + 10.0 / 3.6))
        return self._safe_cruise

    def destroy(self):
        actors = [c.actor for c in self.cars()]
        if actors:
            base.destroy_actors(self.traffic._client, actors)  # pylint: disable=protected-access
        self.own = self.safe = None
        self.lane0 = []


def _light_names(flags):
    names = [name for flag, name in ((base.LEFT_BLINKER, 'left'), (base.RIGHT_BLINKER, 'right'),
                                     (base.BRAKE_LIGHT, 'brake')) if flags & flag]
    return '+'.join(names) or 'off'
