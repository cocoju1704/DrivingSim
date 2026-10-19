#!/usr/bin/env python

"""
Takeover (TOR) experiment on the Town04 figure-8 highway.

The vehicle starts in autonomous mode in lane 2 (the second lane from the median)
and loops the figure-8 highway forever. Use --vehicles N to add traffic.
--scenario 0 is a practice drive: manual driving from the start.

    Driver input      : steering wheel + pedals if one is connected, else keyboard
                        (--input wheel / keyboard to choose). Wheel buttons (reverse,
                        turn signals, horn, lights, ...): set them up once with --wheel-setup.
                          keyboard : W/A/S/D or ARROWS
                          wheel    : steering wheel, throttle pedal, brake pedal
                        Autonomous driving is locked until the pre-alert: input is
                        ignored. From the pre-alert on, any driver input switches
                        to manual driving immediately.
    P                 : start a takeover sequence (autonomous mode only)
                          0 s   pre-alert shown, chime
                          5 s   TOR (takeover request) shown, repeating beeps (--pre-alert)
                          10 s  manual driving is forced if there was no input (TOR + 5 s)
                        The sequence also starts by itself, see the scenarios below.
                        --no-auto-alert turns that off.
    Q                 : toggle reverse (manual driving; also --reverse-button)
    SPACE             : hand-brake (manual driving; also --handbrake-button)
    M                 : manual / automatic transmission (manual driving)
    , / .             : gear down / up (manual transmission)

    Lights (any mode; brake and reverse lights follow the controls by themselves):
    Z / X             : left / right turn signal on/off (also --left/right-blinker-button)
    L                 : position -> low beam -> fog -> off (also --light-button)
    SHIFT + L         : high beam on/off (also --high-beam-button)
    I                 : interior light on/off
    H                 : horn (played by the audio engine)
    E                 : re-engage autonomous mode (manual driving)

    TAB               : next camera position: driver's seat, windshield (no steering wheel),
                        left mirror, right mirror, behind the car, hood, ...
    F1                : toggle HUD
    ESC               : quit

Scenarios (--scenario N). Each has an event point on the loop; the pre-alert starts
automatically --alert-lead seconds before the car reaches it, once per pass:
    0  practice       manual driving from the start, for getting used to the wheel and
                      pedals: no autonomous mode, no pre-alert (P and E do nothing),
                      nothing logged
    1  highway exit   event: the exit point (end of the overpass, --exit-at)
                      pre-alert 10 s before it
    2  work zone      after the first lap, lanes 3 and 4 are closed further ahead
                      (cones, barriers, signs, work vehicles, --workzone-at);
                      pre-alert 20 s before the work zone
    3  sudden fog     at the fog point (--fog-at) the fog starts to thicken from 0;
                      pre-alert when it reaches --fog-threshold (45, after --fog-rise
                      20 s); it keeps thickening and reaches --fog-max (90)
                      --fog-peak-after (10) s after the takeover

Every takeover sequence (P key) is logged. The run leaves the folder
Data/YYMMDD_HHMMSS/ (start time, inside the CARLA_0.9.16 folder) with
    raw.csv       one row per frame from the pre-alert on, plus a TRIAL_END row per trial
    summary.csv   takeover metrics per trial (takeover time, max lateral and
                  longitudinal acceleration, lane keeping, ...)
    figure.png    speed, acceleration, lane offset and driver input of every trial
summary.csv and figure.png are written when the program ends (raw.csv is written
while it runs). Use --no-log to turn the log off.

The car is a Lincoln MKZ 2020 (--filter), seen from the driver's seat so the
dashboard is in view (--view chase: from behind the car).

Run from the CARLA_0.9.16 root folder:

    python PythonAPI\\examples\\takeover_experiment.py
    python PythonAPI\\examples\\takeover_experiment.py --input wheel
    python PythonAPI\\examples\\takeover_experiment.py --lane 1 --vehicles 15
    python PythonAPI\\examples\\takeover_experiment.py --wheel-test   (find axis numbers)
"""

from __future__ import print_function

import argparse
import csv
import ctypes
import datetime
import json
import logging
import math
import os
import random
import socket
import statistics
import subprocess
import sys
import time

import carla
import numpy

# SDL drops wheel input while none of its windows has focus: --wheel-test has no window at all,
# and in the experiment a click on the CARLA server window would freeze the wheel
os.environ.setdefault('SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', '1')

try:
    import pygame
    from pygame.locals import KMOD_SHIFT
    from pygame.locals import K_COMMA
    from pygame.locals import K_DOWN
    from pygame.locals import K_ESCAPE
    from pygame.locals import K_F1
    from pygame.locals import K_LEFT
    from pygame.locals import K_PERIOD
    from pygame.locals import K_RIGHT
    from pygame.locals import K_SPACE
    from pygame.locals import K_TAB
    from pygame.locals import K_UP
    from pygame.locals import K_a
    from pygame.locals import K_d
    from pygame.locals import K_e
    from pygame.locals import K_i
    from pygame.locals import K_l
    from pygame.locals import K_m
    from pygame.locals import K_p
    from pygame.locals import K_q
    from pygame.locals import K_s
    from pygame.locals import K_w
    from pygame.locals import K_x
    from pygame.locals import K_z
except ImportError:
    raise RuntimeError('cannot import pygame, make sure pygame package is installed')

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'carla'))
from agents.navigation.basic_agent import BasicAgent  # pylint: disable=import-error
from agents.navigation.global_route_planner import GlobalRoutePlanner  # pylint: disable=import-error
from agents.navigation.local_planner import RoadOption  # pylint: disable=import-error

# Reuse the world, HUD and camera of the stock manual_control example.
from manual_control import HUD, CameraManager, World  # pylint: disable=import-error

# ==============================================================================
# -- constants -----------------------------------------------------------------
# ==============================================================================

MAP_NAME = 'Town04'
# Spawn point on the figure-8 highway (road 35). Following one of its lanes with
# the straightest choice at every junction closes the loop after ~3045 m. That
# works for lanes 1-3 (lane 1 is next to the median); lane 4 is the exit lane.
START_SPAWN_INDEX = 15
DEFAULT_LANE = 2
DEFAULT_VEHICLE = 'vehicle.lincoln.mkz_2020'  # detailed interior with an instrument cluster
WINDSHIELD_FORWARD = 0.55  # m in front of the driver's eyes: past the steering wheel (every car model has one)
MIRROR_FOV = 60.0          # degrees, side mirror views
DRIVER_VIEWS = (0, 1)      # driver seat, windshield: the views that use all monitors (--screens)
# Mirror glass, measured on the Lincoln MKZ 2020 from where its mirrors appear in the driver's seat view.
MIRROR_GLASS = (0.281, 0.05, 1.40)  # side mirror: x and z as shares of the car's half length / height, y m outside
LEFT_MIRROR_SIZE = (0.251, 0.127)  # m, as seen from the driver (the right glass is seen more from the side)
RIGHT_MIRROR_SIZE = (0.180, 0.116)
# Glass outlines in the driver's seat view, as (x, y) shares of the glass's bounding box
LEFT_MIRROR_OUTLINE = [(0.0, 0.40), (0.13, 0.05), (0.77, 0.0), (0.88, 0.08), (1.0, 0.50), (0.99, 0.81),
                       (0.93, 0.98), (0.85, 1.0), (0.05, 0.71)]
RIGHT_MIRROR_OUTLINE = [(0.0, 0.48), (0.06, 0.06), (0.66, 0.0), (0.87, 0.15), (1.0, 0.51), (0.95, 0.86),
                        (0.66, 1.0), (0.02, 1.0)]
MIRROR_INSET_FOV = 40.0            # degrees, side mirror images on the glass
REAR_MIRROR = (0.60, 0.0, 0.11)    # rear-view mirror glass, m from the driver's eyes (forward, right, up)
REAR_MIRROR_SIZE = (0.26, 0.055)   # m
REAR_MIRROR_FOV = 45.0             # degrees
WHEEL_SETUP_WAIT = 10         # seconds --wheel-setup waits for each button
PEDAL_DEADZONE = 0.02        # pedal travel below this reads 0 (released pedals are not exactly at rest)
WHEEL_SPRING_STANDSTILL = 0.45  # force feedback: centering force when standing, share of --wheel-force
WHEEL_SPRING_FULL_SPEED = 80.0  # km/h at which the centering force reaches --wheel-force
WHEEL_DAMPING = 0.3            # damping (wheel weight), share of --wheel-force
# manual_control's camera positions, in its order (they come after the experiment's views)
STOCK_VIEW_NAMES = ['Behind the car', 'Hood', 'Front side', 'Far behind', 'Low side']
LANES = (1, 2, 3)
NPC_SLOT_SPACING = 40.0   # meters between possible traffic positions in a lane
NPC_CLEARANCE = 60.0      # no traffic closer than this to the start position
NPC_NEAR_RANGE = 300.0    # traffic fills this stretch around the start first
WORKZONE_AT = 1990.0          # scenario 2: taper start, m from the start (straight, 4 lanes)
WORKZONE_AFTER_LAPS = 1       # scenario 2: the work zone appears after this many laps
WORKZONE_TAPER = 60.0         # length of the taper that closes lanes 3 and 4
WORKZONE_LENGTH = 260.0       # closed stretch after the taper
WORKZONE_END_TAPER = 24.0     # cones that open the lanes again
WORKZONE_CLEARANCE = 5.0      # the work zone appears only when no car is this close (m) to lane 3 along it
WORKZONE_MAX_WAIT = 30.0      # ... but after at most this many seconds
CONE_SPACING = 10.0
LANE_WIDTH = 3.5
WORKZONE_LANES = (3, 4)
NPC_PATH_STEP = 5         # use every 5th route waypoint (10 m) for traffic paths
NPC_PATH_LAPS = 2         # laps handed to the Traffic Manager at a time
NPC_PATH_REFRESH = 30.0   # seconds between path refreshes (keeps traffic looping)
ROUTE_RESOLUTION = 2.0  # meters between route waypoints
REFILL_BELOW = 200      # extend the agent's plan when fewer waypoints are left

PRE_ALERT_SECONDS = 5.0  # pre-alert -> TOR
TOR_SECONDS = 5.0        # TOR -> forced manual driving

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
LOG_DIR = os.path.join(ROOT, 'Data')
AUDIO_ENGINE_DIR = os.path.join(ROOT, 'carla-audio-engine')  # vehicle sounds, --no-audio-engine
AUDIO_ENGINE_PYTHON = os.path.join(ROOT, 'venv_carla', 'Scripts', 'python.exe')     # has pyfmodex installed
POST_WINDOW = 10.0  # seconds after the takeover that count as the takeover period
FALLBACK_EXIT = 1000.0  # exit point (m from the start) if the route has no overpass
FOG_AT = 700.0          # scenario 3: where the fog starts to thicken, m from the start
FOG_THRESHOLD = 45.0    # fog density at which the pre-alert starts
FOG_MAX = 90.0          # densest fog
FOG_RISE = 20.0         # seconds from the start of the fog to the threshold
FOG_PEAK_AFTER = 10.0   # the fog is densest this many seconds after the takeover
FOG_CLEAR = 5.0         # seconds for the fog to clear when autonomous driving is re-engaged
FOG_FALLOFF = 0.2       # fog stays close to the ground

# Scenario number -> name, pre-alert message, seconds before the event point at which
# the pre-alert starts.
SCENARIOS = {
    0: ('practice', 'Practice drive', 0.0),  # manual driving only, no alerts
    1: ('exit', 'Highway exit ahead', 10.0),
    2: ('workzone', 'Work zone ahead', 20.0),
    3: ('fog', 'Low visibility', 0.0),   # the lead starts the fog; the pre-alert follows its density
}

AUTO = 'AUTO'
PRE_ALERT = 'PRE_ALERT'
TOR = 'TOR'
MANUAL = 'MANUAL'
AUTONOMOUS_MODES = (AUTO, PRE_ALERT, TOR)
ALERT_MODES = (PRE_ALERT, TOR)  # driver input can take over only in these

DRIVE_KEYS = (K_w, K_a, K_s, K_d, K_UP, K_DOWN, K_LEFT, K_RIGHT)

# Vehicle light flags as ints (carla.VehicleLightState)
POSITION_LIGHT = int(carla.VehicleLightState.Position)
LOW_BEAM = int(carla.VehicleLightState.LowBeam)
HIGH_BEAM = int(carla.VehicleLightState.HighBeam)
FOG_LIGHT = int(carla.VehicleLightState.Fog)
INTERIOR_LIGHT = int(carla.VehicleLightState.Interior)
LEFT_BLINKER = int(carla.VehicleLightState.LeftBlinker)
RIGHT_BLINKER = int(carla.VehicleLightState.RightBlinker)
BRAKE_LIGHT = int(carla.VehicleLightState.Brake)
REVERSE_LIGHT = int(carla.VehicleLightState.Reverse)

# Wheel input counts as a takeover above these deviations (0..1 of full travel).
PEDAL_TAKEOVER = 0.05
STEER_TAKEOVER = 0.05

# ==============================================================================
# -- route ---------------------------------------------------------------------
# ==============================================================================


def build_loop_route(carla_map, start_waypoint):
    """Waypoints of the closed figure-8 loop, starting at start_waypoint."""
    route = [start_waypoint]
    wp = start_waypoint
    for step in range(100000):
        candidates = wp.next(ROUTE_RESOLUTION)
        if not candidates:
            raise RuntimeError('The route has a dead end, it does not form a loop')
        if len(candidates) > 1:
            yaw = wp.transform.rotation.yaw
            candidates.sort(key=lambda w: abs((w.transform.rotation.yaw - yaw + 180.0) % 360.0 - 180.0))
        wp = candidates[0]
        if (step > 10 and wp.road_id == start_waypoint.road_id and
                wp.transform.location.distance(start_waypoint.transform.location) < ROUTE_RESOLUTION + 0.5):
            return route
        route.append(wp)
    raise RuntimeError('The route did not close into a loop')


def destroy_actors(client, actors):
    """Destroy actors in one batch. Destroying a Traffic Manager car one by one crashes the client."""
    client.apply_batch_sync([carla.command.DestroyActor(actor) for actor in actors], False)


def remove_stale_actors(client, sim_world):
    """Destroy hero/npc cars (and their sensors) that an earlier run left in the server, and sensors
    whose car is gone (the audio engine's collision sensor: its process is killed, not closed)."""
    actors = sim_world.get_actors()
    stale = [a for a in actors.filter('vehicle.*') if a.attributes.get('role_name') in ('hero', 'npc', 'workzone')]
    stale += [a for a in actors.filter('static.prop.*') if a.attributes.get('role_name') == 'workzone']
    ids = set(a.id for a in stale)
    sensors = [a for a in actors.filter('sensor.*') if a.parent is None or a.parent.id in ids]
    if not stale and not sensors:
        return
    logging.warning('Removing %d actor(s) left over from an earlier run', len(stale) + len(sensors))
    destroy_actors(client, sensors + stale)


def overpass_end_index(route):
    """Index of the last waypoint of the first overpass (where the road comes back to the ground)."""
    end = None
    for index, waypoint in enumerate(route):
        if waypoint.transform.location.z > 1.0:
            end = index
        elif end is not None:
            break
    return end


def lane_waypoint(waypoint, lane):
    """The waypoint at the same place in highway lane 1-3 (lane 1 is next to the median)."""
    for _ in range(8):
        if waypoint.lane_id == -lane:
            return waypoint
        waypoint = waypoint.get_left_lane() if waypoint.lane_id < -lane else waypoint.get_right_lane()
        if waypoint is None:
            break
    raise RuntimeError('Could not find highway lane %d' % lane)


def experiment_views(extent):
    """Camera positions added in front of manual_control's: (name, transform, fov, mirrored).

    Driver seat measured on the Lincoln MKZ 2020, Mercedes Coupe 2020, Dodge Charger 2020 and
    Tesla Model 3: just behind the car's center, left seat, eyes at 1.6 x the half height of the
    car. The windshield view is the same spot 0.55 m further forward, past the steering wheel
    (no wheel, no instrument cluster). The mirror views look back from the side mirrors with a
    narrower field of view, flipped left-right like a real mirror.
    """
    eye_x, eye_z = -0.04 * extent.x, 1.6 * extent.z
    mirror_x, mirror_y, mirror_z = 0.25 * extent.x, extent.y + 0.1, 1.35 * extent.z
    return [
        ('Driver seat', carla.Transform(carla.Location(x=eye_x, y=-0.36, z=eye_z), carla.Rotation(pitch=-4.0)),
         None, False),
        ('Windshield (no steering wheel)',
         carla.Transform(carla.Location(x=eye_x + WINDSHIELD_FORWARD, y=-0.36, z=eye_z), carla.Rotation(pitch=-4.0)),
         None, False),
        ('Left mirror', carla.Transform(carla.Location(x=mirror_x, y=-mirror_y, z=mirror_z),
                                        carla.Rotation(pitch=-5.0, yaw=-165.0)), MIRROR_FOV, True),
        ('Right mirror', carla.Transform(carla.Location(x=mirror_x, y=mirror_y, z=mirror_z),
                                         carla.Rotation(pitch=-5.0, yaw=165.0)), MIRROR_FOV, True),
    ]


def car_mirrors(extent):
    """The car's mirrors as (glass center, glass width and height in m, glass outline or None,
    camera transform, fov).

    CARLA does not render reflections, so the mirrors of the car model stay empty. Each mirror gets
    a camera looking back, and its image is drawn over the glass where the glass appears in the
    driver views (see _mirror_rect), cut to the glass outline. Fitted to the Lincoln MKZ 2020.
    """
    eye_x, eye_z = -0.04 * extent.x, 1.6 * extent.z
    side_x, side_y, side_z = 0.25 * extent.x, extent.y + 0.1, 1.35 * extent.z
    glass_x, glass_y, glass_z = MIRROR_GLASS[0] * extent.x, extent.y + MIRROR_GLASS[1], MIRROR_GLASS[2] * extent.z
    return [
        (carla.Location(x=glass_x, y=-glass_y, z=glass_z), LEFT_MIRROR_SIZE, LEFT_MIRROR_OUTLINE,
         carla.Transform(carla.Location(x=side_x, y=-side_y, z=side_z), carla.Rotation(pitch=-3.0, yaw=-170.0)),
         MIRROR_INSET_FOV),
        (carla.Location(x=glass_x, y=glass_y, z=glass_z), RIGHT_MIRROR_SIZE, RIGHT_MIRROR_OUTLINE,
         carla.Transform(carla.Location(x=side_x, y=side_y, z=side_z), carla.Rotation(pitch=-3.0, yaw=170.0)),
         MIRROR_INSET_FOV),
        (carla.Location(x=eye_x + REAR_MIRROR[0], y=REAR_MIRROR[1], z=eye_z + REAR_MIRROR[2]), REAR_MIRROR_SIZE, None,
         carla.Transform(carla.Location(x=-extent.x - 0.2, z=eye_z + 0.1), carla.Rotation(pitch=-2.0, yaw=180.0)),
         REAR_MIRROR_FOV),
    ]


def _glass_mask(size, outline):
    """White glass shape on transparent, multiplied into a mirror image to cut it to the glass."""
    mask = pygame.Surface(size, pygame.SRCALPHA)
    mask.fill((0, 0, 0, 0))
    pygame.draw.polygon(mask, (255, 255, 255, 255), [(x * (size[0] - 1), y * (size[1] - 1)) for x, y in outline])
    return mask


def _project(manager, eye, point):
    """Window pixel (x, y) of `point` (car coordinates) seen from the driver view `eye`, and pixels
    per meter at that distance; None when it is off the monitors."""
    fov = manager.view_options.get(manager.transform_index, (None, False))[0] or manager.default_fov
    width, height = manager.screen_size
    focal = width / 2.0 / math.tan(math.radians(fov) / 2.0)
    dx, dy, dz = point.x - eye.location.x, point.y - eye.location.y, point.z - eye.location.z
    pitch = math.radians(eye.rotation.pitch)
    middle = manager.screens // 2
    for screen in range(manager.screens):
        yaw = math.radians(eye.rotation.yaw + (screen - middle) * manager.screen_fov)
        x = dx * math.cos(yaw) + dy * math.sin(yaw)
        y = -dx * math.sin(yaw) + dy * math.cos(yaw)
        x, z = x * math.cos(pitch) + dz * math.sin(pitch), -x * math.sin(pitch) + dz * math.cos(pitch)
        if x <= 0.05:
            continue
        u, v = width / 2.0 + focal * y / x, height / 2.0 - focal * z / x
        if 0 <= u < width:
            return screen * width + u, v, focal / x
    return None


def _mirror_rect(manager, eye, center, size):
    """Window rectangle of a mirror glass of `size` (m) at `center`, seen from `eye`. Mirrors are
    turned towards the driver, so the glass is taken as facing the eye."""
    projected = _project(manager, eye, center)
    if projected is None:
        return None
    x, y, scale = projected
    width, height = size[0] * scale, size[1] * scale
    if width < 8 or height < 8:
        return None
    return pygame.Rect(int(x - width / 2), int(y - height / 2), int(width), int(height))


def add_driver_view(world, args):
    """Add the experiment's camera positions in front of manual_control's; start in the driver's
    seat unless --view chase. TAB (next_view) cycles through all of them and shows the name.

    With --screens N the window is split into N monitors, each with its own camera: in the driver
    views the outer cameras are turned by --screen-fov per monitor so the images join at the
    monitor edges; the other views use only the middle monitor.
    """
    manager = world.camera_manager
    views = experiment_views(world.player.bounding_box.extent)
    # pylint: disable=protected-access
    manager._camera_transforms[0:0] = [(transform, carla.AttachmentType.Rigid) for _, transform, _, _ in views]
    manager.view_names = [name for name, _, _, _ in views] + STOCK_VIEW_NAMES
    driver_fov = args.screen_fov if args.screens > 1 else None
    manager.view_options = {i: (fov or driver_fov, mirrored) for i, (_, _, fov, mirrored) in enumerate(views)}
    manager.default_fov = manager.sensors[0][-1].get_attribute('fov').as_float()

    manager.screens = args.screens
    manager.screen_width = args.width // args.screens
    manager.screen_fov = args.screen_fov
    manager.side_views = []  # [(screen, camera, {'image', 'surface'})], driver views only
    manager.mirror_views = []  # [(window rect, camera, {'image', 'surface'})], driver views only
    manager.mirrors = [] if args.no_mirrors else car_mirrors(world.player.bounding_box.extent)
    manager.latest_image = None  # newest RGB image, converted when it is drawn
    # cameras render at --render-scale of a monitor, the client scales them up
    manager.render_size = (int(manager.screen_width * args.render_scale), int(args.height * args.render_scale))
    manager.screen_size = (manager.screen_width, args.height)
    for sensor in manager.sensors:
        if sensor[0].startswith('sensor.camera'):
            sensor[-1].set_attribute('image_size_x', str(manager.render_size[0]))
            sensor[-1].set_attribute('image_size_y', str(manager.render_size[1]))

    def render(display):
        _, mirrored = manager.view_options.get(manager.transform_index, (None, False))
        middle = manager.screens // 2
        image, manager.latest_image = manager.latest_image, None
        if image is not None:
            manager.surface = _camera_surface(manager, image)
        if manager.surface is not None:
            surface = pygame.transform.flip(manager.surface, True, False) if mirrored else manager.surface
            display.blit(surface, (middle * manager.screen_width, 0))
        shown = {middle}
        for screen, _, view in manager.side_views:
            image, view['image'] = view['image'], None
            if image is not None:
                view['surface'] = _camera_surface(manager, image)
            if view['surface'] is not None:
                display.blit(view['surface'], (screen * manager.screen_width, 0))
                shown.add(screen)
        for screen in range(manager.screens):
            if screen not in shown:
                display.fill((0, 0, 0), (screen * manager.screen_width, 0, manager.screen_width, args.height))
        for rect, _, view in manager.mirror_views:
            image, view['image'] = view['image'], None
            if image is not None:  # flipped left-right like a real mirror
                surface = pygame.transform.flip(
                    pygame.image.frombuffer(image.raw_data, (image.width, image.height), 'BGRA').convert(), True, False)
                if view['mask'] is not None:
                    surface = surface.convert_alpha()
                    surface.blit(view['mask'], (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                view['surface'] = surface
            if view['surface'] is not None:
                display.blit(view['surface'], rect)
    manager.render = render

    manager.transform_index = len(views) if args.view == 'chase' else 0  # driver's seat, or behind the car
    _respawn_view(manager)


def _camera_surface(manager, image):
    """carla.Image (BGRA) -> display-format surface the size of one monitor. SDL converts the
    pixels directly; manual_control's numpy path is too slow for 2560x1440 images."""
    surface = pygame.image.frombuffer(image.raw_data, (image.width, image.height), 'BGRA').convert()
    if surface.get_size() != manager.screen_size:
        surface = pygame.transform.scale(surface, manager.screen_size)
    return surface


def _parse_image(weak_self, image):
    """Replaces CameraManager._parse_image: RGB images are only kept and converted when drawn (the
    server sends more images than the client draws), other sensors take the stock path."""
    self = weak_self()
    if self is not None and hasattr(self, 'screen_size') and self.sensors[self.index][0] == 'sensor.camera.rgb' \
            and self.sensors[self.index][1] == carla.ColorConverter.Raw:
        self.latest_image = image
    else:
        _stock_parse_image(weak_self, image)


_stock_parse_image = CameraManager._parse_image
CameraManager._parse_image = staticmethod(_parse_image)


def destroy_side_views(manager):
    for _, camera, _ in manager.side_views + manager.mirror_views:
        camera.stop()
        camera.destroy()
    manager.side_views = []
    manager.mirror_views = []


def _respawn_view(manager):
    """Respawn the camera at manager.transform_index with that view's field of view, and the side
    monitors' cameras in the driver views."""
    fov, _ = manager.view_options.get(manager.transform_index, (None, False))
    for sensor in manager.sensors:
        if sensor[-1].has_attribute('fov'):
            sensor[-1].set_attribute('fov', str(fov or manager.default_fov))
    manager.set_sensor(manager.index, notify=False, force_respawn=True)
    manager.latest_image = None

    destroy_side_views(manager)
    if manager.screens > 1 and manager.transform_index in DRIVER_VIEWS:
        # pylint: disable=protected-access
        transform = manager._camera_transforms[manager.transform_index][0]
        blueprint = manager.sensors[0][-1]  # RGB, already at this view's fov
        middle = manager.screens // 2
        for screen in range(manager.screens):
            if screen == middle:
                continue
            rotation = carla.Rotation(pitch=transform.rotation.pitch,
                                      yaw=transform.rotation.yaw + (screen - middle) * manager.screen_fov)
            camera = manager._parent.get_world().spawn_actor(
                blueprint, carla.Transform(transform.location, rotation),
                attach_to=manager._parent, attachment_type=carla.AttachmentType.Rigid)
            view = {'image': None, 'surface': None}
            camera.listen(lambda image, view=view: view.__setitem__('image', image))
            manager.side_views.append((screen, camera, view))

    if manager.transform_index in DRIVER_VIEWS:
        # pylint: disable=protected-access
        eye = manager._camera_transforms[manager.transform_index][0]
        library = manager._parent.get_world().get_blueprint_library()
        for center, size, outline, transform, fov in manager.mirrors:
            rect = _mirror_rect(manager, eye, center, size)
            if rect is None:
                continue
            blueprint = library.find('sensor.camera.rgb')
            blueprint.set_attribute('image_size_x', str(rect.width))
            blueprint.set_attribute('image_size_y', str(rect.height))
            blueprint.set_attribute('fov', str(fov))
            blueprint.set_attribute('gamma', str(manager.sensors[0][-1].get_attribute('gamma').as_float()))
            camera = manager._parent.get_world().spawn_actor(
                blueprint, transform, attach_to=manager._parent, attachment_type=carla.AttachmentType.Rigid)
            view = {'image': None, 'surface': None, 'mask': outline and _glass_mask(rect.size, outline)}
            camera.listen(lambda image, view=view: view.__setitem__('image', image))
            manager.mirror_views.append((rect, camera, view))


def next_view(world):
    """TAB: next camera position, its name on the HUD."""
    manager = world.camera_manager
    manager.transform_index = (manager.transform_index + 1) % len(manager._camera_transforms)  # pylint: disable=protected-access
    _respawn_view(manager)
    world.hud.notification(manager.view_names[manager.transform_index])


class _FixedBoundingBox(object):
    """The vehicle, with its bounding box read once. Each bounding_box read is a server round trip
    (5 ms, several times that while the server renders the monitor cameras) and BasicAgent reads it
    four times per step."""

    def __init__(self, vehicle):
        self._vehicle = vehicle
        self.bounding_box = vehicle.bounding_box

    def __getattr__(self, name):
        return getattr(self._vehicle, name)


class LoopFollower(object):
    """Drives a vehicle around a closed route forever with a BasicAgent."""

    def __init__(self, vehicle, route, target_speed, carla_map, route_planner):
        self._vehicle = vehicle
        self._route = route
        self._agent = BasicAgent(_FixedBoundingBox(vehicle), target_speed=target_speed, opt_dict={},
                                 map_inst=carla_map, grp_inst=route_planner)
        self._agent.ignore_traffic_lights(True)
        self._agent.ignore_stop_signs(True)
        self._plan = []
        self.engage()

    def engage(self):
        """(Re)start following the route from the point closest to the vehicle."""
        location = self._vehicle.get_location()
        nearest = min(range(len(self._route)),
                      key=lambda i: self._route[i].transform.location.distance(location))
        rotated = self._route[nearest:] + self._route[:nearest]
        self._plan = [(wp, RoadOption.LANEFOLLOW) for wp in rotated]
        self._agent.set_global_plan(self._plan, stop_waypoint_creation=True, clean_queue=True)

    def run_step(self):
        planner = self._agent.get_local_planner()
        if len(planner._waypoints_queue) < REFILL_BELOW:  # pylint: disable=protected-access
            self._agent.set_global_plan(self._plan, stop_waypoint_creation=True, clean_queue=False)
        return self._agent.run_step()


def spawn_workzone(sim_world, route, start_index):
    """Close lanes 3 and 4 from `start_index` on. `route` is the lane 3 route of the loop.

    Layout, along the route: two warning signs, a taper of cones that leads from the outer
    edge of lane 4 to the edge of lane 2, a row of barriers across both lanes, cones along
    the closed lanes with a work truck in lane 3 and a work van in lane 4, and a short
    taper that opens the lanes again.
    """
    library = sim_world.get_blueprint_library()
    actors = []

    def put(name, distance, offset, yaw_add=0.0, lift=0.05, hold=False):
        """Spawn `name` at route `distance` m from start_index, `offset` m right of lane 3's center."""
        waypoint = route[(start_index + int(round(distance / ROUTE_RESOLUTION))) % len(route)]
        right = waypoint.transform.get_right_vector()
        location = waypoint.transform.location
        position = carla.Location(location.x + right.x * offset, location.y + right.y * offset, location.z + lift)
        blueprint = library.find(name)
        if blueprint.has_attribute('role_name'):
            blueprint.set_attribute('role_name', 'workzone')
        actor = sim_world.try_spawn_actor(
            blueprint, carla.Transform(position, carla.Rotation(yaw=waypoint.transform.rotation.yaw + yaw_add)))
        if actor is None:
            return None
        if hold:
            actor.apply_control(carla.VehicleControl(hand_brake=True, brake=1.0))
        actors.append(actor)
        return actor

    inner = -0.5 * LANE_WIDTH + 0.55        # just inside lane 3, next to the lane 2 edge
    outer = 1.5 * LANE_WIDTH                # outer edge of lane 4 (offset from lane 3's center)
    taper_end = WORKZONE_TAPER
    body_end = taper_end + WORKZONE_LENGTH

    # warning signs on the shoulder and a large warning board where the taper starts
    put('static.prop.warningconstruction', -160.0, outer + 1.2, yaw_add=180.0)
    put('static.prop.warningconstruction', -80.0, outer + 1.2, yaw_add=180.0)
    put('static.prop.trafficwarning', -10.0, outer - 1.0, yaw_add=180.0)

    # taper: from the outer edge of lane 4 to the edge of lane 2
    count = int(WORKZONE_TAPER / 7.5)
    for k in range(count + 1):
        put('static.prop.trafficcone01', k * WORKZONE_TAPER / count, outer + (inner - outer) * k / count)

    # barriers across lanes 3 and 4 at the end of the taper
    barrier_length = 1.22
    lateral = -0.5 * LANE_WIDTH + 0.6
    while lateral < outer + 0.3:
        put('static.prop.streetbarrier', taper_end + 2.0, lateral, yaw_add=90.0)
        lateral += barrier_length

    # cones along the closed lanes
    distance = taper_end + CONE_SPACING
    while distance < body_end:
        put('static.prop.trafficcone01', distance, inner)
        distance += CONE_SPACING

    # work vehicles
    put('vehicle.carlamotors.carlacola', taper_end + 70.0, 0.6, lift=0.3, hold=True)
    put('vehicle.mercedes.sprinter', taper_end + 190.0, LANE_WIDTH, lift=0.3, hold=True)
    for distance in (taper_end + 52.0, taper_end + 94.0, taper_end + 172.0, taper_end + 214.0):
        put('static.prop.barrel', distance, 0.6 if distance < taper_end + 150.0 else LANE_WIDTH, yaw_add=0.0)

    # the lanes open again
    count = int(WORKZONE_END_TAPER / 6.0)
    for k in range(count + 1):
        put('static.prop.trafficcone01', body_end + k * WORKZONE_END_TAPER / count,
            inner + (outer - inner) * k / count)

    logging.info('Work zone: %d objects close lanes 3 and 4 from %.0f m to %.0f m',
                 len(actors), start_index * ROUTE_RESOLUTION, start_index * ROUTE_RESOLUTION + body_end)
    return actors


class TrafficVehicle(object):
    """A traffic car driven by the Traffic Manager along one lane of the loop.

    The Traffic Manager runs inside the server, so many cars cost the client
    (and the ego agent's control loop) almost nothing.
    """

    def __init__(self, vehicle, route, traffic_manager, speed):
        self._vehicle = vehicle
        self._route = route
        self._tm = traffic_manager
        self.half_length = vehicle.bounding_box.extent.x  # read once: bounding_box is a server round trip
        vehicle.set_autopilot(True, traffic_manager.get_port())
        traffic_manager.auto_lane_change(vehicle, False)
        traffic_manager.set_desired_speed(vehicle, speed)
        traffic_manager.ignore_lights_percentage(vehicle, 100)
        traffic_manager.ignore_signs_percentage(vehicle, 100)
        self.refresh_path()

    @property
    def actor(self):
        return self._vehicle

    def refresh_path(self):
        """Hand the next laps of the route, starting from where the car is now."""
        location = self._vehicle.get_location()
        nearest = min(range(len(self._route)),
                      key=lambda i: self._route[i].transform.location.distance(location))
        lap = self._route[nearest:] + self._route[:nearest]
        path = [wp.transform.location for wp in (lap * NPC_PATH_LAPS)[::NPC_PATH_STEP]]
        self._tm.set_path(self._vehicle, path)


def prune_traffic(traffic, sim_world):
    """Drop traffic cars the server destroyed (e.g. one that fell off the map after a crash).

    In place: the recorder and the path refresh share this list. Checked against the world
    snapshot: after a destroy from elsewhere, actor.is_alive stays True for a while.
    """
    if not traffic:
        return
    snapshot = sim_world.get_snapshot()
    gone = [npc for npc in traffic if snapshot.find(npc.actor.id) is None]
    for npc in gone:
        logging.warning('Traffic car %d is gone, dropped from the traffic list', npc.actor.id)
        traffic.remove(npc)


def spawn_traffic(sim_world, routes, args, traffic_manager, lanes):
    """Place args.vehicles cars on the highway, each driving the loop in one of the given lanes."""
    if args.vehicles <= 0:
        return []
    ego_location = routes[args.lane][0].transform.location
    step = int(NPC_SLOT_SPACING / ROUTE_RESOLUTION)
    slots = [(lane, i) for lane in routes if lane in lanes for i in range(0, len(routes[lane]), step)
             if routes[lane][i].transform.location.distance(ego_location) > NPC_CLEARANCE]
    count = min(args.vehicles, len(slots))
    if count < args.vehicles:
        logging.warning('Only %d traffic positions are available, placing %d vehicles', len(slots), count)
    # Positions within NPC_NEAR_RANGE of the start (ahead or behind) are used first.
    near = [slot for slot in slots
            if min(slot[1], len(routes[slot[0]]) - slot[1]) * ROUTE_RESOLUTION <= NPC_NEAR_RANGE]
    far = [slot for slot in slots if slot not in near]
    chosen = random.sample(near, min(count, len(near)))
    chosen += random.sample(far, count - len(chosen))
    # Passenger cars only: they handle the highway curves at traffic speed.
    blueprints = [bp for bp in sim_world.get_blueprint_library().filter('vehicle.*')
                  if bp.has_attribute('base_type') and bp.get_attribute('base_type').as_str() == 'car']
    traffic = []
    for lane, index in chosen:
        blueprint = random.choice(blueprints)
        blueprint.set_attribute('role_name', 'npc')
        if blueprint.has_attribute('color'):
            blueprint.set_attribute('color', random.choice(blueprint.get_attribute('color').recommended_values))
        transform = routes[lane][index].transform
        transform.location.z += 0.5
        vehicle = sim_world.try_spawn_actor(blueprint, transform)
        if vehicle is not None:
            traffic.append(TrafficVehicle(vehicle, routes[lane], traffic_manager, args.npc_speed))
    logging.info('Traffic: %d of %d vehicles placed (%.0f km/h)', len(traffic), args.vehicles, args.npc_speed)
    return traffic


# ==============================================================================
# -- driver inputs -------------------------------------------------------------
# ==============================================================================


def keyboard_light_event(event):
    """Light switch a key press asks for: 'left', 'right', 'lights', 'high_beam', 'interior' or None."""
    if event.type != pygame.KEYDOWN:
        return None
    if event.key == K_l:
        return 'high_beam' if pygame.key.get_mods() & KMOD_SHIFT else 'lights'
    return {K_z: 'left', K_x: 'right', K_i: 'interior'}.get(event.key)


class KeyboardInput(object):
    """WASD / arrow keys."""

    def __init__(self):
        self._steer_cache = 0.0

    def reset(self):
        self._steer_cache = 0.0

    def is_takeover_event(self, event):
        return event.type == pygame.KEYDOWN and event.key in DRIVE_KEYS

    def is_reverse_event(self, event):
        return False

    def light_event(self, event):
        """Light switch the event asks for (see keyboard_light_event), else None."""
        return keyboard_light_event(event)

    def driver_active(self, keys):
        return any(keys[k] for k in DRIVE_KEYS)

    def hand_brake(self):
        return False

    def force_feedback(self, speed_kmh):
        pass

    def horn_event(self, event):
        return False

    def close(self):
        pass

    def peek(self, keys):
        """(steer, throttle, brake) the driver is asking for right now."""
        return (float((keys[K_RIGHT] or keys[K_d]) - (keys[K_LEFT] or keys[K_a])),
                float(keys[K_UP] or keys[K_w]), float(keys[K_DOWN] or keys[K_s]))

    def update(self, control, keys, milliseconds):
        control.throttle = min(control.throttle + 0.1, 1.0) if (keys[K_UP] or keys[K_w]) else 0.0
        control.brake = min(control.brake + 0.2, 1.0) if (keys[K_DOWN] or keys[K_s]) else 0.0

        steer_increment = 5e-4 * milliseconds
        if keys[K_LEFT] or keys[K_a]:
            self._steer_cache = 0.0 if self._steer_cache > 0 else self._steer_cache - steer_increment
        elif keys[K_RIGHT] or keys[K_d]:
            self._steer_cache = 0.0 if self._steer_cache < 0 else self._steer_cache + steer_increment
        else:
            self._steer_cache = 0.0
        self._steer_cache = min(0.7, max(-0.7, self._steer_cache))
        control.steer = round(self._steer_cache, 1)


class _HapticDirection(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint8), ('dir', ctypes.c_int32 * 3)]


class _HapticCondition(ctypes.Structure):
    """SDL_HapticCondition (spring, damper, ...)."""
    _fields_ = [('type', ctypes.c_uint16), ('direction', _HapticDirection), ('length', ctypes.c_uint32),
                ('delay', ctypes.c_uint16), ('button', ctypes.c_uint16), ('interval', ctypes.c_uint16),
                ('right_sat', ctypes.c_uint16 * 3), ('left_sat', ctypes.c_uint16 * 3),
                ('right_coeff', ctypes.c_int16 * 3), ('left_coeff', ctypes.c_int16 * 3),
                ('deadband', ctypes.c_uint16 * 3), ('center', ctypes.c_int16 * 3)]


class _HapticEffect(ctypes.Union):
    """SDL_HapticEffect; the padding covers the union's larger members."""
    _fields_ = [('type', ctypes.c_uint16), ('condition', _HapticCondition), ('padding', ctypes.c_uint8 * 128)]


class WheelForceFeedback(object):
    """Resistance in the steering wheel: a centering spring that gets stiffer with speed, like the
    self-aligning torque of a real car, plus some damping so the wheel does not feel weightless.

    pygame has no force feedback, so this calls the haptic functions of the SDL2 library pygame
    ships with (the same library instance, so the joystick and haptic parts share their state).
    """

    INIT_HAPTIC = 0x1000
    SPRING, DAMPER, GAIN = 1 << 7, 1 << 8, 1 << 12
    INFINITY = 0xFFFFFFFF
    CARTESIAN, STEERING_AXIS = 1, 3  # SDL_HapticDirection types
    RAMP_SECONDS = 1.5      # the force fades in, so the wheel does not jerk to the center at the start
    UPDATE_SECONDS = 0.2    # each update goes through the wheel driver: not every frame

    def __init__(self, name, strength):
        self._sdl = None
        self._strength = max(0.0, min(strength, 100.0)) / 100.0
        self._start = time.monotonic()
        self._last_update = 0.0
        self._spring_coeff = None
        if self._strength <= 0.0:
            return
        try:
            sdl = ctypes.CDLL(os.path.join(os.path.dirname(pygame.__file__), 'SDL2.dll'))
        except OSError as error:
            logging.warning('No force feedback, SDL2.dll not found: %s', error)
            return
        sdl.SDL_GetError.restype = ctypes.c_char_p
        sdl.SDL_HapticName.restype = ctypes.c_char_p
        sdl.SDL_HapticOpen.restype = ctypes.c_void_p
        for function in ('SDL_HapticQuery', 'SDL_HapticClose', 'SDL_HapticStopAll'):
            getattr(sdl, function).argtypes = [ctypes.c_void_p]
        sdl.SDL_HapticQuery.restype = ctypes.c_uint
        sdl.SDL_HapticSetGain.argtypes = [ctypes.c_void_p, ctypes.c_int]
        sdl.SDL_HapticNewEffect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_HapticEffect)]
        sdl.SDL_HapticUpdateEffect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(_HapticEffect)]
        sdl.SDL_HapticRunEffect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
        if sdl.SDL_InitSubSystem(self.INIT_HAPTIC) != 0:
            logging.warning('No force feedback: %s', sdl.SDL_GetError().decode(errors='replace'))
            return
        index = next((i for i in range(sdl.SDL_NumHaptics())
                      if (sdl.SDL_HapticName(i) or b'').decode(errors='replace') == name), None)
        haptic = sdl.SDL_HapticOpen(index) if index is not None else None
        if not haptic:
            logging.warning('No force feedback for %s', name)
            return
        supported = sdl.SDL_HapticQuery(haptic)
        if not supported & self.SPRING:
            logging.warning('No force feedback: %s has no spring effect', name)
            sdl.SDL_HapticClose(haptic)
            return
        self._sdl, self._haptic = sdl, haptic
        if supported & self.GAIN:
            sdl.SDL_HapticSetGain(haptic, 100)
        # the default (polar) direction needs two axes; a wheel has one
        for self._direction in (self.STEERING_AXIS, self.CARTESIAN):
            self._spring = self._effect(self.SPRING, 0)
            self._spring_id = sdl.SDL_HapticNewEffect(haptic, ctypes.byref(self._spring))
            if self._spring_id >= 0:
                break
        self._damper_id = -1
        if self._spring_id >= 0 and supported & self.DAMPER:
            self._damper = self._effect(self.DAMPER, int(0x7FFF * WHEEL_DAMPING * self._strength))
            self._damper_id = sdl.SDL_HapticNewEffect(haptic, ctypes.byref(self._damper))
        if self._spring_id < 0:
            logging.warning('No force feedback: %s', sdl.SDL_GetError().decode(errors='replace'))
            self.close()
            return
        for effect_id in (self._spring_id, self._damper_id):
            if effect_id >= 0:
                sdl.SDL_HapticRunEffect(haptic, effect_id, self.INFINITY)
        logging.info('Force feedback on %s, strength %.0f%% (--wheel-force)', name, self._strength * 100)

    def _effect(self, kind, coeff):
        effect = _HapticEffect()
        condition = effect.condition
        condition.type = kind
        condition.direction.type = self._direction
        condition.direction.dir[0] = 1
        condition.length = self.INFINITY
        condition.right_sat[0] = condition.left_sat[0] = 0xFFFF
        condition.right_coeff[0] = condition.left_coeff[0] = coeff
        return effect

    def update(self, speed_kmh):
        """Spring stiffness for the current speed: WHEEL_SPRING_STANDSTILL of the full force when
        standing, rising to the full force at WHEEL_SPRING_FULL_SPEED km/h."""
        if self._sdl is None:
            return
        now = time.monotonic()
        if now - self._last_update < self.UPDATE_SECONDS:
            return
        self._last_update = now
        share = min(speed_kmh / WHEEL_SPRING_FULL_SPEED, 1.0)
        stiffness = WHEEL_SPRING_STANDSTILL + (1.0 - WHEEL_SPRING_STANDSTILL) * share
        ramp = min((now - self._start) / self.RAMP_SECONDS, 1.0)
        coeff = int(0x7FFF * self._strength * stiffness * ramp)
        if self._spring_coeff is not None and abs(coeff - self._spring_coeff) < 300:
            return
        self._spring_coeff = coeff
        self._spring.condition.right_coeff[0] = self._spring.condition.left_coeff[0] = coeff
        self._sdl.SDL_HapticUpdateEffect(self._haptic, self._spring_id, ctypes.byref(self._spring))

    def close(self):
        if self._sdl is not None:
            self._sdl.SDL_HapticStopAll(self._haptic)
            self._sdl.SDL_HapticClose(self._haptic)
            self._sdl = None


class WheelInput(object):
    """Steering wheel and pedals through pygame's joystick interface.

    Steering: axis value -1..1 maps straight to the CARLA steer value.
    Pedals:   released = --pedal-rest (1 for a Logitech G29), fully pressed is the
              opposite end; the travel maps linearly to 0..1.
    """

    def __init__(self, args):
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count == 0:
            raise RuntimeError('No steering wheel found. Connect it, then find its axis numbers with --wheel-test')
        if not 0 <= args.joystick < count:
            raise RuntimeError('--joystick %d is not valid, %d device(s) found' % (args.joystick, count))
        self._joystick = pygame.joystick.Joystick(args.joystick)
        self._joystick.init()
        self._steer_axis = args.steer_axis
        self._throttle_axis = args.throttle_axis
        self._brake_axis = args.brake_axis
        buttons = wheel_buttons(args, self._joystick.get_name())
        self._handbrake_button = buttons['handbrake']
        self._reverse_button = buttons['reverse']
        self._horn_button = buttons['horn']
        self._light_buttons = {buttons['left_blinker']: 'left', buttons['right_blinker']: 'right',
                               buttons['lights']: 'lights', buttons['high_beam']: 'high_beam',
                               buttons['interior']: 'interior'}
        self._light_buttons.pop(-1, None)
        self._keyboard = None  # the horn: the audio engine listens for the H key
        self._pedal_rest = 1.0 if args.pedal_rest > 0 else -1.0
        for axis in (self._steer_axis, self._throttle_axis, self._brake_axis):
            if not 0 <= axis < self._joystick.get_numaxes():
                raise RuntimeError('Axis %d does not exist, %s has %d axes. Check with --wheel-test' %
                                   (axis, self._joystick.get_name(), self._joystick.get_numaxes()))
        logging.info('Steering wheel: %s (steer axis %d, throttle axis %d, brake axis %d)',
                     self._joystick.get_name(), self._steer_axis, self._throttle_axis, self._brake_axis)
        self._steer_baseline = 0.0
        self.reset()
        self._force = WheelForceFeedback(self._joystick.get_name(), args.wheel_force)

    def force_feedback(self, speed_kmh):
        self._force.update(speed_kmh)

    def close(self):
        self._force.close()

    def reset(self):
        # The wheel is not necessarily centered when autonomous driving starts.
        pygame.event.pump()
        self._steer_baseline = self._steer()

    def _steer(self):
        return min(1.0, max(-1.0, self._joystick.get_axis(self._steer_axis)))

    def _pedal(self, axis):
        raw = self._joystick.get_axis(axis)
        pressed = min(1.0, max(0.0, (raw - self._pedal_rest) / (-2.0 * self._pedal_rest)))
        # A released pedal reads 0.99997 (pygame divides by 32768), not 1: the brake would stay at
        # 0.00002, and CARLA holds a car with any brake above 0, whatever the throttle.
        if pressed < PEDAL_DEADZONE:
            return 0.0
        return (pressed - PEDAL_DEADZONE) / (1.0 - PEDAL_DEADZONE)

    def is_takeover_event(self, event):
        return False

    def is_reverse_event(self, event):
        return (event.type == pygame.JOYBUTTONDOWN and self._reverse_button >= 0 and
                event.button == self._reverse_button)

    def horn_event(self, event):
        """Horn button: holds the H key down while pressed, because the audio engine (a separate
        process) reads the horn from the keyboard. True if the event was the horn button."""
        if event.type not in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP) or event.button != self._horn_button:
            return False
        if self._keyboard is None:
            try:
                import keyboard  # pylint: disable=import-outside-toplevel
                self._keyboard = keyboard
            except ImportError:
                logging.warning('The horn button needs the keyboard package: pip install keyboard')
                self._horn_button = -1
                return True
        if event.type == pygame.JOYBUTTONDOWN:
            self._keyboard.press('h')
        else:
            self._keyboard.release('h')
        return True

    def light_event(self, event):
        """Light switch the event asks for (wheel button or key, see keyboard_light_event), else None."""
        if event.type == pygame.JOYBUTTONDOWN:
            return self._light_buttons.get(event.button)
        return keyboard_light_event(event)

    def driver_active(self, keys):
        return (self._pedal(self._throttle_axis) > PEDAL_TAKEOVER or
                self._pedal(self._brake_axis) > PEDAL_TAKEOVER or
                abs(self._steer() - self._steer_baseline) > STEER_TAKEOVER)

    def hand_brake(self):
        return self._handbrake_button >= 0 and bool(self._joystick.get_button(self._handbrake_button))

    def peek(self, keys):
        """(steer, throttle, brake) the driver is asking for right now."""
        return self._steer(), self._pedal(self._throttle_axis), self._pedal(self._brake_axis)

    def update(self, control, keys, milliseconds):
        control.steer = self._steer()
        control.throttle = self._pedal(self._throttle_axis)
        control.brake = self._pedal(self._brake_axis)


WHEEL_BUTTONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wheel_buttons.json')
# (action, option, button suggested on a PlayStation wheel such as the Thrustmaster T300 RS, what it does)
WHEEL_ACTIONS = [
    ('reverse', 'reverse_button', 'R2', 'reverse on/off'),
    ('left_blinker', 'left_blinker_button', 'the LEFT paddle behind the wheel', 'left turn signal'),
    ('right_blinker', 'right_blinker_button', 'the RIGHT paddle behind the wheel', 'right turn signal'),
    ('horn', 'horn_button', 'CROSS (X)', 'horn'),
    ('lights', 'light_button', 'SQUARE', 'lights: position -> low beam -> fog -> off'),
    ('high_beam', 'high_beam_button', 'TRIANGLE', 'high beam on/off'),
    ('interior', 'interior_button', 'CIRCLE', 'interior light on/off'),
    ('handbrake', 'handbrake_button', 'L2', 'hand-brake (while held)'),
]


def wheel_buttons(args, wheel_name):
    """{action: button number, -1 = none}: the command line options, else wheel_buttons.json."""
    saved = {}
    try:
        with open(WHEEL_BUTTONS_FILE) as file:
            data = json.load(file)
        if data.get('wheel') == wheel_name:
            saved = data.get('buttons', {})
        else:
            logging.warning('%s was set up for "%s", not this wheel: run --wheel-setup',
                            WHEEL_BUTTONS_FILE, data.get('wheel'))
    except (OSError, ValueError):
        logging.warning('No wheel buttons set up yet: run --wheel-setup')
    buttons = {}
    for action, option, _, _ in WHEEL_ACTIONS:
        value = getattr(args, option)
        buttons[action] = value if value is not None else saved.get(action, -1)
    logging.info('Wheel buttons: %s', ', '.join('%s %d' % item for item in buttons.items() if item[1] >= 0) or 'none')
    return buttons


def wheel_setup(args):
    """Ask for each wheel button in turn and save the numbers to wheel_buttons.json."""
    pygame.init()
    pygame.joystick.init()
    if not 0 <= args.joystick < pygame.joystick.get_count():
        print('No steering wheel found.')
        return
    joystick = pygame.joystick.Joystick(args.joystick)
    joystick.init()
    name = joystick.get_name()
    print('\nWheel: %s (%d buttons)' % (name, joystick.get_numbuttons()))
    print('Press the button asked for. Wait %d s to skip one, Ctrl+C to cancel.\n' % WHEEL_SETUP_WAIT)
    buttons = {}

    def held():
        pygame.event.pump()
        return {i for i in range(joystick.get_numbuttons()) if joystick.get_button(i)}

    try:
        for action, _, suggested, description in WHEEL_ACTIONS:
            print('  %-42s press %s ... ' % (description, suggested), end='', flush=True)
            pressed, deadline, before = None, time.time() + WHEEL_SETUP_WAIT, held()
            while pressed is None and time.time() < deadline:
                new = held() - before - set(buttons.values())
                before &= held()
                if new:
                    pressed = min(new)
                time.sleep(0.01)
            if pressed is None:
                print('skipped')
                continue
            buttons[action] = pressed
            print('button %d' % pressed)
            while pressed in held():  # wait for the release
                time.sleep(0.01)
    except KeyboardInterrupt:
        print('\nCancelled, nothing saved.')
        return
    finally:
        pygame.quit()
    with open(WHEEL_BUTTONS_FILE, 'w') as file:
        json.dump({'wheel': name, 'buttons': buttons}, file, indent=2)
    print('\nSaved to %s' % WHEEL_BUTTONS_FILE)


def wheel_test(args):
    """Print live axis and button values to find the numbers for the wheel options."""
    pygame.init()
    pygame.joystick.init()
    count = pygame.joystick.get_count()
    if count == 0:
        print('No joystick or steering wheel found.')
        return
    for index in range(count):
        print('[%d] %s' % (index, pygame.joystick.Joystick(index).get_name()))
    joystick = pygame.joystick.Joystick(args.joystick)
    joystick.init()
    print('\nUsing [%d]. Turn the wheel and press each pedal and button, Ctrl+C to stop.' % args.joystick)
    print('Released pedals read about 1.00 (or -1.00 on some drivers, then use --pedal-rest -1).\n')
    try:
        while True:
            pygame.event.pump()
            axes = ' '.join('a%d=%+.2f' % (i, joystick.get_axis(i)) for i in range(joystick.get_numaxes()))
            buttons = ','.join(str(i) for i in range(joystick.get_numbuttons()) if joystick.get_button(i))
            print('\r%s | buttons: %-12s' % (axes, buttons or '-'), end='', flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        pygame.quit()


def _fmt(value, digits=3):
    return '' if value is None else round(value, digits)


class TrialRecorder(object):
    """CSV log of the takeover sequences.

    From the pre-alert on, one row per frame. When the trial ends (the takeover
    period is over, autonomous driving is re-engaged, or the program quits) a
    TRIAL_END row repeats the last frame and fills the summary columns:

      tot_s            takeover time: pre-alert -> autopilot deactivated
      tor_reaction_s   TOR -> autopilot deactivated (empty if taken over before the TOR
                       or forced)
      first_input_s    pre-alert -> first driver input
      malat / malon    max |lateral| / |longitudinal| acceleration in the takeover period
      sdlp, max_lane_offset, lane_changes, speed, TTC and collisions over the same period

    The takeover period is the POST_WINDOW seconds that follow the takeover.
    """

    COLUMNS = ['trial', 'wall_time', 't_prealert_s', 't_tor_s', 'phase', 'event',
               'x', 'y', 'speed_kmh', 'a_lon', 'a_lat', 'steer', 'throttle', 'brake',
               'driver_steer', 'driver_throttle', 'driver_brake', 'lane_id', 'lane_offset_m',
               'lead_gap_m', 'lead_speed_kmh', 'ttc_s', 'collisions', 'event_dist_m', 'fog_density',
               'scenario', 'input', 'lane', 'vehicles',
               'takeover_type', 'tot_s', 'tor_reaction_s', 'first_input_s',
               'speed_prealert_kmh', 'speed_takeover_kmh', 'window_complete',
               'malat', 'malon', 'sdlp', 'max_lane_offset', 'lane_changes',
               'speed_min_kmh', 'speed_mean_kmh', 'min_ttc_s', 'min_gap_m', 'collisions_window']

    def __init__(self, world, traffic, driver_input, args, started, window=POST_WINDOW):
        self._world = world
        self._traffic = traffic
        self._half_length = world.player.bounding_box.extent.x  # bounding_box is a server round trip
        self._input = driver_input
        self._window = window
        self._constant = {'scenario': args.scenario, 'input': args.input, 'lane': args.lane,
                          'vehicles': args.vehicles}
        self.dir = os.path.join(LOG_DIR, started.strftime('%y%m%d_%H%M%S'))
        self.path = os.path.join(self.dir, 'raw.csv')
        self._file = None
        self._writer = None
        self._trial = 0
        self._active = False
        self._event_dist = None
        self._fog = None
        self._enabled = not args.no_log

    # -- trial events ----------------------------------------------------------

    def start_trial(self, now):
        if not self._enabled:
            return
        self._trial += 1
        self._active = True
        self._t0 = now
        self._tor_time = None
        self._takeover_time = None
        self._takeover_type = None
        self._first_input = None
        self._pending = 'PRE_ALERT'
        self._last_row = None
        self._speed_prealert = None
        self._post = []
        self._collisions = 0
        self._collisions_at_takeover = 0
        self._collision_frames = len(self._world.collision_sensor.history)
        self._collision_time = -10.0
        self._lane_changes = 0
        self._last_lane = None

    def mark_tor(self, now):
        if self._active:
            self._tor_time = now
            self._pending = 'TOR'

    def mark_takeover(self, now, kind):
        """kind: 'before_tor', 'after_tor' or 'forced'."""
        if self._active and self._takeover_time is None:
            self._takeover_time = now
            self._takeover_type = kind
            self._pending = 'TAKEOVER_' + kind.upper()
            self._collisions_at_takeover = self._collisions
            self._last_lane = None

    def abort(self, now):
        """The trial ends early, e.g. autonomous driving was re-engaged."""
        if self._active:
            self._finish(complete=False)

    def close(self):
        if self._active:
            self._finish(complete=False)
        if self._file is not None:
            self._file.close()
            self._file = None

    def write_reports(self):
        """Write summary.csv and figure.png next to raw.csv once the run is over."""
        if self._writer is None:
            return
        try:
            import analyze_takeover  # in the same folder as this script
            analyze_takeover.report(self.dir, self._window)
        except Exception as error:  # the raw log is already safe on disk
            logging.error('Could not write summary.csv and figure.png: %s', error)

    # -- per frame -------------------------------------------------------------

    def sample(self, now, mode, event_dist=None, fog=None):
        if not self._active:
            return
        self._event_dist = event_dist
        self._fog = fog
        keys = pygame.key.get_pressed()
        if self._first_input is None and self._input.driver_active(keys):
            self._first_input = now - self._t0
        row, extra = self._snapshot(now, mode, keys)
        if self._speed_prealert is None:
            self._speed_prealert = row['speed_kmh']
        if self._takeover_time is not None:
            if extra['lane_id'] is not None:
                if self._last_lane is not None and extra['lane_id'] != self._last_lane:
                    self._lane_changes += 1
                self._last_lane = extra['lane_id']
            self._post.append((row['a_lon'], row['a_lat'], extra['lane_offset'], row['speed_kmh'],
                               extra['gap'], extra['ttc'], self._collisions))
        self._write(row)
        self._last_row = dict(row)
        if self._takeover_time is not None and now - self._takeover_time >= self._window:
            self._finish(complete=True)

    def _snapshot(self, now, mode, keys):
        player = self._world.player
        transform = player.get_transform()
        velocity = player.get_velocity()
        acceleration = player.get_acceleration()
        forward = transform.get_forward_vector()
        right = transform.get_right_vector()
        speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
        a_lon = acceleration.x * forward.x + acceleration.y * forward.y + acceleration.z * forward.z
        a_lat = acceleration.x * right.x + acceleration.y * right.y + acceleration.z * right.z
        control = player.get_control()
        steer_in, throttle_in, brake_in = self._input.peek(keys)

        lane_id = lane_offset = None
        waypoint = self._world.map.get_waypoint(transform.location, project_to_road=True,
                                                lane_type=carla.LaneType.Driving)
        if waypoint is not None:
            lane_id = waypoint.lane_id
            wp_right = waypoint.transform.get_right_vector()
            delta = transform.location - waypoint.transform.location
            lane_offset = delta.x * wp_right.x + delta.y * wp_right.y + delta.z * wp_right.z

        gap, lead_speed, ttc = self._lead(transform, forward, speed)

        frames = len(self._world.collision_sensor.history)
        if frames > self._collision_frames:
            self._collision_frames = frames
            if now - self._collision_time > 1.0:  # one contact = many frames
                self._collisions += 1
            self._collision_time = now

        row = {
            'trial': self._trial,
            'wall_time': datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3],
            't_prealert_s': _fmt(now - self._t0),
            't_tor_s': _fmt(None if self._tor_time is None else now - self._tor_time),
            'phase': mode, 'event': self._pending,
            'x': _fmt(transform.location.x), 'y': _fmt(transform.location.y),
            'speed_kmh': round(speed * 3.6, 3), 'a_lon': round(a_lon, 3), 'a_lat': round(a_lat, 3),
            'steer': _fmt(control.steer), 'throttle': _fmt(control.throttle), 'brake': _fmt(control.brake),
            'driver_steer': _fmt(steer_in), 'driver_throttle': _fmt(throttle_in), 'driver_brake': _fmt(brake_in),
            'lane_id': '' if lane_id is None else lane_id, 'lane_offset_m': _fmt(lane_offset),
            'lead_gap_m': _fmt(gap), 'lead_speed_kmh': _fmt(lead_speed), 'ttc_s': _fmt(ttc),
            'collisions': self._collisions, 'event_dist_m': _fmt(self._event_dist, 1),
            'fog_density': _fmt(self._fog, 1),
        }
        row.update(self._constant)
        self._pending = ''
        return row, {'lane_id': lane_id, 'lane_offset': lane_offset, 'gap': gap, 'ttc': ttc}

    def _lead(self, transform, forward, speed):
        """Gap (m), speed (km/h) and time-to-collision (s) of the closest traffic car ahead in this lane."""
        best = None
        location = transform.location
        for npc in self._traffic:
            other = npc.actor
            try:
                delta = other.get_location() - location
            except RuntimeError:  # destroyed this frame; prune_traffic drops it next frame
                continue
            ahead = delta.x * forward.x + delta.y * forward.y
            side = abs(-delta.x * forward.y + delta.y * forward.x)
            if 0.0 < ahead < 150.0 and side < 1.9 and abs(delta.z) < 3.0:
                if best is None or ahead < best[0]:
                    best = (ahead, npc)
        if best is None:
            return None, None, None
        ahead, npc = best
        other = npc.actor
        gap = max(ahead - self._half_length - npc.half_length, 0.0)
        velocity = other.get_velocity()
        lead_speed = velocity.x * forward.x + velocity.y * forward.y
        closing = speed - lead_speed
        return gap, lead_speed * 3.6, (gap / closing if closing > 0.1 else None)

    # -- output ----------------------------------------------------------------

    def _write(self, row):
        if self._writer is None:
            os.makedirs(self.dir, exist_ok=True)
            self._file = open(self.path, 'w', newline='', encoding='utf-8')
            self._writer = csv.DictWriter(self._file, fieldnames=self.COLUMNS, restval='')
            self._writer.writeheader()
            logging.info('Logging to %s', self.path)
        self._writer.writerow(row)

    def _finish(self, complete):
        self._active = False
        row = dict(self._last_row) if self._last_row else {'trial': self._trial}
        row['event'] = 'TRIAL_END'
        row.update(self._metrics(complete))
        self._write(row)
        self._file.flush()
        logging.info('Trial %d logged: %s takeover, TOT %s s, MAlat %s, MAlon %s m/s2',
                     self._trial, row['takeover_type'] or 'no', row.get('tot_s', '-'),
                     row.get('malat', '-'), row.get('malon', '-'))

    def _metrics(self, complete):
        metrics = {'takeover_type': self._takeover_type or '', 'window_complete': int(complete),
                   'speed_prealert_kmh': _fmt(self._speed_prealert)}
        if self._takeover_time is None:
            return metrics
        metrics['tot_s'] = _fmt(self._takeover_time - self._t0)
        if self._tor_time is not None and self._takeover_type == 'after_tor':
            metrics['tor_reaction_s'] = _fmt(self._takeover_time - self._tor_time)
        metrics['first_input_s'] = _fmt(self._first_input)
        post = self._post
        if post:
            offsets = [p[2] for p in post if p[2] is not None]
            speeds = [p[3] for p in post]
            gaps = [p[4] for p in post if p[4] is not None]
            ttcs = [p[5] for p in post if p[5] is not None]
            metrics.update({
                'speed_takeover_kmh': _fmt(speeds[0]),
                'malat': _fmt(max(abs(p[1]) for p in post)),
                'malon': _fmt(max(abs(p[0]) for p in post)),
                'sdlp': _fmt(statistics.pstdev(offsets) if len(offsets) > 1 else None),
                'max_lane_offset': _fmt(max((abs(o) for o in offsets), default=None)),
                'lane_changes': self._lane_changes,
                'speed_min_kmh': _fmt(min(speeds)),
                'speed_mean_kmh': _fmt(sum(speeds) / len(speeds)),
                'min_ttc_s': _fmt(min(ttcs, default=None)),
                'min_gap_m': _fmt(min(gaps, default=None)),
                'collisions_window': self._collisions - self._collisions_at_takeover,
            })
        return metrics


# ==============================================================================
# -- scenarios -----------------------------------------------------------------
# ==============================================================================


class Scenario(object):
    """What triggers the takeover: an event point on the loop, reached once per pass.

    The pre-alert starts automatically `lead` seconds before the car reaches
    `event_index` (a route index; None while there is no event yet).
    """

    manual_only = False  # True: the driver drives from the start, no autonomous mode

    def __init__(self, number, args):
        self.number = number
        self.name, self.message, lead = SCENARIOS[number]
        self.lead = lead if args.alert_lead is None else args.alert_lead
        self.event_index = None

    def tick(self, now, laps):
        pass

    def on_event(self, now):
        """The car got `lead` seconds from the event point. True: start the pre-alert now."""
        return True

    def alert_due(self):
        """True when the scenario wants the pre-alert now (for alerts not tied to a position)."""
        return False

    def on_alert(self, now):
        pass

    def on_takeover(self, now):
        pass

    def on_engage(self, now):
        pass

    def fog_density(self):
        return None

    def cleanup(self, client):
        pass


class PracticeScenario(Scenario):
    """0: practice drive, manual from the start. No event point, so no pre-alert and nothing logged."""

    manual_only = True

    def __init__(self, args):
        super(PracticeScenario, self).__init__(0, args)
        logging.info('Scenario 0, practice drive: manual driving, no takeover requests')


class ExitScenario(Scenario):
    """1: the car reaches the end of its autonomous stretch (an exit point)."""

    def __init__(self, args, route):
        super(ExitScenario, self).__init__(1, args)
        if args.exit_at is not None and args.exit_at < 0:
            return
        index = overpass_end_index(route) if args.exit_at is None else int(args.exit_at / ROUTE_RESOLUTION)
        if index is None:
            index = int(FALLBACK_EXIT / ROUTE_RESOLUTION)
        self.event_index = index % len(route)
        location = route[self.event_index].transform.location
        logging.info('Scenario 1, highway exit: exit point %.0f m from the start (x %.0f, y %.0f)',
                     self.event_index * ROUTE_RESOLUTION, location.x, location.y)


class WorkzoneScenario(Scenario):
    """2: after the first lap a work zone closes lanes 3 and 4 further ahead."""

    def __init__(self, args, sim_world, route, lane3_route):
        super(WorkzoneScenario, self).__init__(2, args)
        self._world = sim_world
        self._lane3 = lane3_route
        at = args.workzone_at if args.workzone_at is not None else WORKZONE_AT
        self._index = int(at / ROUTE_RESOLUTION) % len(route)
        self._actors = []
        # lane 3 centerline along the zone, from just before the first cone to past the last one
        first = self._index - int(20.0 / ROUTE_RESOLUTION)
        last = self._index + int((WORKZONE_TAPER + WORKZONE_LENGTH + WORKZONE_END_TAPER + 30.0) / ROUTE_RESOLUTION)
        self._zone_points = [lane3_route[i % len(lane3_route)].transform.location for i in range(first, last + 1)]
        self._due = None              # time the work zone became due (waiting for a clear road)
        logging.info('Scenario 2, work zone: appears after lap %d, %.0f m from the start',
                     WORKZONE_AFTER_LAPS, self._index * ROUTE_RESOLUTION)

    def _blocking_car(self):
        """A car within WORKZONE_CLEARANCE m of lane 3's centerline along the zone (lanes 2-4), or None.
        Spawning ~60 objects next to a passing car can clip it and throw it off the road."""
        for vehicle in self._world.get_actors().filter('vehicle.*'):
            location = vehicle.get_location()
            if any(location.distance(point) < WORKZONE_CLEARANCE for point in self._zone_points):
                return vehicle
        return None

    def tick(self, now, laps):
        if self.event_index is None and laps >= WORKZONE_AFTER_LAPS:
            if self._due is None:
                self._due = now
            blocking = self._blocking_car()
            if blocking is not None and now - self._due < WORKZONE_MAX_WAIT:
                return
            if blocking is not None:
                logging.warning('Work zone: car %d still next to it after %.0f s, spawning anyway',
                                blocking.id, WORKZONE_MAX_WAIT)
            elif now - self._due > 0.5:
                logging.info('Work zone: waited %.1f s for passing cars', now - self._due)
            self._actors = spawn_workzone(self._world, self._lane3, self._index)
            self.event_index = self._index

    def cleanup(self, client):
        if self._actors:
            destroy_actors(client, self._actors)
            self._actors = []


class FogScenario(Scenario):
    """3: fog thickens gradually from the fog point on.

    density 0 --(rise)--> threshold: pre-alert --> TOR --> takeover --> max, FOG_PEAK_AFTER s
    after the takeover. The rate up to the pre-alert is threshold / rise. From the pre-alert on
    it is scaled by PRE_ALERT_SECONDS / --pre-alert, so the density at the TOR is the same for
    any pre-alert duration (45 + 2.25 * 5 = 56.25 with the defaults). At the takeover it changes
    so the fog reaches its maximum exactly peak_after seconds later.
    """

    def __init__(self, args, sim_world, route):
        super(FogScenario, self).__init__(3, args)
        self._world = sim_world
        self._original = sim_world.get_weather()
        self._threshold = args.fog_threshold
        self._max = args.fog_max
        self._rise = max(args.fog_rise, 0.1)
        self._peak_after = max(args.fog_peak_after, 0.1)
        self._pre_alert = args.pre_alert
        at = args.fog_at if args.fog_at is not None else FOG_AT
        self.event_index = int(at / ROUTE_RESOLUTION) % len(route)
        self._state = 'idle'          # idle, rising, clearing
        self._density = 0.0
        self._rate = 0.0
        self._alerted = False
        self._last = None
        self._last_sent = None
        self._apply(None)             # no fog until the fog point
        logging.info('Scenario 3, sudden fog: fog point %.0f m from the start; density 0 -> %.0f in %.0f s '
                     '(pre-alert), %.0f %.0f s after the takeover', self.event_index * ROUTE_RESOLUTION,
                     self._threshold, self._rise, self._max, self._peak_after)

    def _apply(self, now):
        """Send the density to the server (at most 10 times a second)."""
        if now is not None and self._last_sent is not None and now - self._last_sent < 0.1:
            return
        self._last_sent = now
        weather = self._world.get_weather()
        weather.fog_density = self._density
        weather.fog_distance = 0.0
        weather.fog_falloff = FOG_FALLOFF
        self._world.set_weather(weather)

    def _start(self, now):
        self._state = 'rising'
        self._rate = self._threshold / self._rise
        self._alerted = False
        self._last = now
        logging.info('Fog starts to thicken')

    def on_event(self, now):
        if self._state != 'rising':
            self._start(now)
        return False  # the pre-alert waits for the threshold

    def alert_due(self):
        return self._state == 'rising' and not self._alerted and self._density >= self._threshold

    def on_alert(self, now):
        self._alerted = True
        if self._state != 'rising':  # P key before the fog point: start the fog too
            self._start(now)
        self._rate = self._threshold / self._rise * PRE_ALERT_SECONDS / self._pre_alert
        logging.info('Pre-alert at fog density %.1f: %.2f per s for the %.1f s pre-alert',
                     self._density, self._rate, self._pre_alert)

    def on_takeover(self, now):
        if self._state == 'rising':
            self._rate = max(self._max - self._density, 0.0) / self._peak_after
            logging.info('Takeover at fog density %.1f: %.0f in %.0f s', self._density, self._max, self._peak_after)

    def on_engage(self, now):
        if self._density > 0.0:
            self._state = 'clearing'
            self._rate = self._max / FOG_CLEAR
            self._last = now

    def tick(self, now, laps):
        if self._state == 'idle':
            return
        dt = 0.0 if self._last is None else max(now - self._last, 0.0)
        self._last = now
        if self._state == 'rising':
            self._density = min(self._density + self._rate * dt, self._max)
        else:
            self._density = max(self._density - self._rate * dt, 0.0)
            if self._density == 0.0:
                self._state = 'idle'
        self._apply(now)

    def fog_density(self):
        return self._density

    def cleanup(self, client):
        self._world.set_weather(self._original)


def make_scenario(args, sim_world, routes, route):
    if args.scenario == 0:
        return PracticeScenario(args)
    if args.scenario == 2:
        return WorkzoneScenario(args, sim_world, route, routes[3])
    if args.scenario == 3:
        return FogScenario(args, sim_world, route)
    return ExitScenario(args, route)


# ==============================================================================
# -- sound ---------------------------------------------------------------------
# ==============================================================================


class AlertSound(object):
    """Alert sounds made in code: a chime for the pre-alert, repeating beeps for the TOR."""

    def __init__(self, enabled=True):
        self._ok = False
        if not enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2)
            self._chime = self._sound([(880, 0.18), (0, 0.06), (1175, 0.30)], 0.5)
            self._beeps = self._sound([(1000, 0.15), (0, 0.08), (1000, 0.15), (0, 0.45)], 0.7)
            self._click = self._sound([(660, 0.10)], 0.4)
            self._ok = True
        except Exception as error:  # no audio device: run silently
            logging.warning('No sound: %s', error)

    @staticmethod
    def _sound(parts, volume):
        rate, _, channels = pygame.mixer.get_init()
        pieces = []
        for frequency, seconds in parts:
            t = numpy.arange(int(rate * seconds)) / float(rate)
            wave = numpy.sin(2.0 * math.pi * frequency * t) if frequency else numpy.zeros_like(t)
            edge = min(len(t) // 2, int(rate * 0.01))  # 10 ms fade in/out, no clicks
            if frequency and edge:
                ramp = numpy.linspace(0.0, 1.0, edge)
                wave[:edge] *= ramp
                wave[-edge:] *= ramp[::-1]
            pieces.append(wave)
        mono = (numpy.concatenate(pieces) * volume * 32767).astype(numpy.int16)
        return pygame.sndarray.make_sound(numpy.ascontiguousarray(numpy.repeat(mono[:, None], channels, axis=1)))

    def pre_alert(self):
        if self._ok:
            self._beeps.stop()
            self._chime.play()

    def tor(self):
        if self._ok:
            self._beeps.play(loops=-1)

    def stop(self, confirm=False):
        if self._ok:
            self._beeps.stop()
            if confirm:
                self._click.play()


class AudioEngine(object):
    """Vehicle sounds (cabin noise, crash, ...) from carla-audio-engine, run next to the experiment.

    fmain.py plays the sounds, cmain.py reads the hero vehicle and sends its state to fmain.py
    over UDP 127.0.0.1:5005. Their output goes to carla-audio-engine/logs/.
    """

    def __init__(self, enabled=True):
        self._processes = []
        if not enabled:
            return
        if not os.path.isdir(AUDIO_ENGINE_DIR):
            logging.warning('Audio engine not found at %s, running without vehicle sounds', AUDIO_ENGINE_DIR)
            return
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind(('127.0.0.1', 5005))
        except OSError:
            logging.warning('Another audio engine is already running (UDP 5005 in use), not starting one')
            return
        finally:
            probe.close()
        python = AUDIO_ENGINE_PYTHON if os.path.isfile(AUDIO_ENGINE_PYTHON) else sys.executable
        log_dir = os.path.join(AUDIO_ENGINE_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        for name, folder in (('fmain', 'FMOD'), ('cmain', 'CARLA')):
            log = open(os.path.join(log_dir, name + '.log'), 'w')
            self._processes.append(subprocess.Popen(
                [python, '-u', name + '.py'], cwd=os.path.join(AUDIO_ENGINE_DIR, 'src', folder),
                stdout=log, stderr=subprocess.STDOUT))
            log.close()  # the child keeps its own handle
        logging.info('Audio engine started (logs in %s)', log_dir)

    def stop(self):
        for process in self._processes:
            if process.poll() is None:
                # /T: the venv python.exe is a launcher, the interpreter runs as its child
                # full path: System32 is not on this PC's PATH
                taskkill = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe')
                subprocess.call([taskkill, '/T', '/F', '/PID', str(process.pid)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._processes = []


# ==============================================================================
# -- experiment ----------------------------------------------------------------
# ==============================================================================


class TakeoverExperiment(object):
    def __init__(self, world, follower, driver_input, recorder, route, scenario, sound, auto_alert=True,
                 pre_alert=PRE_ALERT_SECONDS):
        self._world = world
        self._pre_alert = pre_alert         # seconds from the pre-alert to the TOR
        # Lights the driver switched (int VehicleLightState flags), kept here because the state read
        # back from the server can lag behind quick presses. Brake/reverse lights are added per frame.
        self._lights = int(world.player.get_light_state()) & ~(BRAKE_LIGHT | REVERSE_LIGHT)
        self._sent_lights = None
        self._input = driver_input
        self._recorder = recorder
        self._follower = follower
        self._route = route
        self._scenario = scenario
        self._sound = sound
        self._auto_alert = auto_alert
        self._armed = True                  # one automatic pre-alert per pass of the event point
        self._index = self._nearest_index()
        self._progress = 0                  # route waypoints driven since the start
        self.laps = 0
        self._event_dist = None
        self._control = carla.VehicleControl()
        self._alert_time = 0.0
        self._tor_time = 0.0
        self.mode = AUTO
        if scenario.manual_only:
            self.mode = MANUAL
            self._input.reset()
            self._world.hud.notification('Practice drive: manual driving', seconds=4.0)
            logging.info('Manual driving (practice)')
        else:
            self._engage_autonomous()

    # -- mode changes ----------------------------------------------------------

    def _engage_autonomous(self):
        now = time.monotonic()
        self._recorder.abort(now)
        self._sound.stop()
        self._scenario.on_engage(now)
        self._follower.engage()
        self.mode = AUTO
        self._input.reset()
        self._world.hud.notification('Autonomous driving')
        logging.info('Autonomous driving engaged')

    def _start_alert(self, now):
        self.mode = PRE_ALERT
        self._alert_time = now
        self._recorder.start_trial(now)
        self._sound.pre_alert()
        self._scenario.on_alert(now)
        logging.info('Pre-alert issued')

    def _take_over(self, now, forced=False):
        if forced:
            reason = 'no input within %.0f s of TOR (forced)' % TOR_SECONDS
        elif self.mode == TOR:
            reason = 'driver input, %.2f s after TOR' % (now - self._tor_time)
        elif self.mode == PRE_ALERT:
            reason = 'driver input, %.2f s after pre-alert, before TOR' % (now - self._alert_time)
        else:
            reason = 'driver input'
        self._recorder.mark_takeover(now, 'forced' if forced else 'after_tor' if self.mode == TOR else 'before_tor')
        self._scenario.on_takeover(now)
        self.mode = MANUAL
        self._sound.stop(confirm=True)
        self._control = carla.VehicleControl()
        self._input.reset()
        self._world.hud.notification('Manual driving: ' + reason, seconds=4.0)
        logging.info('Manual driving: %s', reason)

    # -- per frame -------------------------------------------------------------

    def handle_event(self, event, now):
        if self._input.horn_event(event):
            return
        light = self._input.light_event(event)
        if light is not None:
            self._switch_light(light)
            return
        if self.mode in ALERT_MODES and self._input.is_takeover_event(event):
            self._take_over(now)
            return
        if self.mode == MANUAL and self._input.is_reverse_event(event):
            self._toggle_reverse()
            return
        if event.type != pygame.KEYDOWN:
            return
        if event.key == K_p and self.mode == AUTO:
            self._start_alert(now)
        elif event.key == K_e and self.mode == MANUAL and not self._scenario.manual_only:
            self._engage_autonomous()
        elif event.key == K_q and self.mode == MANUAL:
            self._toggle_reverse()
        elif event.key == K_m and self.mode == MANUAL:
            self._control.manual_gear_shift = not self._control.manual_gear_shift
            self._control.gear = self._world.player.get_control().gear
            self._world.hud.notification('%s transmission' %
                                         ('Manual' if self._control.manual_gear_shift else 'Automatic'))
        elif event.key == K_COMMA and self.mode == MANUAL and self._control.manual_gear_shift:
            self._control.gear = max(-1, self._control.gear - 1)
        elif event.key == K_PERIOD and self.mode == MANUAL and self._control.manual_gear_shift:
            self._control.gear = self._control.gear + 1

    def _switch_light(self, action):
        """Driver light switches, in every mode. The next frame sends the result (_update_lights).

        'left' / 'right'  turn signal on that side; again on the same side turns it off
        'lights'          off -> position -> low beam -> fog -> off (like manual_control's L key)
        'high_beam'       high beam on/off
        'interior'        interior light on/off
        """
        lights = self._lights
        if action in ('left', 'right'):
            wanted = LEFT_BLINKER if action == 'left' else RIGHT_BLINKER
            on = not lights & wanted
            lights &= ~(LEFT_BLINKER | RIGHT_BLINKER)
            if on:
                lights |= wanted
            message = 'Turn signal %s %s' % (action, 'on' if on else 'off')
        elif action == 'high_beam':
            lights ^= HIGH_BEAM
            message = 'High beam %s' % ('on' if lights & HIGH_BEAM else 'off')
        elif action == 'interior':
            lights ^= INTERIOR_LIGHT
            message = 'Interior light %s' % ('on' if lights & INTERIOR_LIGHT else 'off')
        elif lights & FOG_LIGHT:
            lights &= ~(POSITION_LIGHT | LOW_BEAM | FOG_LIGHT)
            message = 'Lights off'
        elif lights & LOW_BEAM:
            lights |= FOG_LIGHT
            message = 'Fog lights'
        elif lights & POSITION_LIGHT:
            lights |= LOW_BEAM
            message = 'Low beam lights'
        else:
            lights |= POSITION_LIGHT
            message = 'Position lights'
        self._lights = lights
        self._world.hud.notification(message)

    def _update_lights(self, control):
        """Send the driver's lights plus brake and reverse lights from the control just applied."""
        lights = self._lights
        if control.brake > 0.0:
            lights |= BRAKE_LIGHT
        if control.reverse:
            lights |= REVERSE_LIGHT
        if lights != self._sent_lights:
            self._world.player.set_light_state(carla.VehicleLightState(lights))
            self._sent_lights = lights

    def _toggle_reverse(self):
        self._control.gear = 1 if self._control.reverse else -1
        self._control.reverse = not self._control.reverse

    def _nearest_index(self, around=None):
        """Index of the route waypoint closest to the car (searched near `around` if given)."""
        location = self._world.player.get_location()
        count = len(self._route)
        if around is None:
            candidates = range(count)
        else:
            candidates = [(around + offset) % count for offset in range(-40, 41)]
        best = min(candidates, key=lambda i: self._route[i].transform.location.distance(location))
        if around is not None and self._route[best].transform.location.distance(location) > 20.0:
            return self._nearest_index()  # lost the route, search all of it
        return best

    def _track_event(self, now):
        """Laps, distance to the scenario's event point, and the automatic pre-alert."""
        previous = self._index
        self._index = self._nearest_index(self._index)
        count = len(self._route)
        self._progress += (self._index - previous + count // 2) % count - count // 2
        if self._progress // count > self.laps:
            self.laps = self._progress // count
            logging.info('Lap %d completed', self.laps)
        self._scenario.tick(now, self.laps)
        if self._auto_alert and self.mode == AUTO and self._scenario.alert_due():
            logging.info('%s: automatic pre-alert', self._scenario.message)
            self._start_alert(now)
        event = self._scenario.event_index
        if event is None:
            self._event_dist = None
            return
        self._event_dist = ((event - self._index) % count) * ROUTE_RESOLUTION
        velocity = self._world.player.get_velocity()
        speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
        threshold = max(speed * self._scenario.lead, 5.0)
        if self._armed:
            if self._auto_alert and self.mode == AUTO and speed > 5.0 and self._event_dist <= threshold:
                self._armed = False
                logging.info('%s: event point %.0f m ahead (%.1f s)',
                             self._scenario.message, self._event_dist, self._event_dist / speed)
                if self._scenario.on_event(now):
                    self._start_alert(now)
        elif self._event_dist > threshold + 100.0:
            self._armed = True  # the event point has been passed

    def tick(self, clock, now):
        keys = pygame.key.get_pressed()
        self._track_event(now)
        if self.mode in AUTONOMOUS_MODES:
            if self.mode in ALERT_MODES and self._input.driver_active(keys):
                self._take_over(now)
            elif self.mode == PRE_ALERT and now - self._alert_time >= self._pre_alert:
                self.mode = TOR
                self._tor_time = now
                self._recorder.mark_tor(now)
                self._sound.tor()
                logging.info('TOR issued')
            elif self.mode == TOR and now - self._tor_time >= TOR_SECONDS:
                self._take_over(now, forced=True)

        if self.mode in AUTONOMOUS_MODES:
            control = self._follower.run_step()
        else:
            self._parse_manual_keys(keys, clock.get_time())
            control = self._control
        self._world.player.apply_control(control)
        self._input.force_feedback(self._world.player.get_velocity().length() * 3.6)
        self._update_lights(control)
        self._recorder.sample(now, self.mode, self._event_dist, self._scenario.fog_density())

    def _parse_manual_keys(self, keys, milliseconds):
        self._input.update(self._control, keys, milliseconds)
        self._control.hand_brake = bool(keys[K_SPACE]) or self._input.hand_brake()
        self._control.reverse = self._control.gear < 0  # also when shifting down with the manual transmission

    # -- overlay ---------------------------------------------------------------

    def render(self, display, fonts, now):
        big, small = fonts
        width = display.get_width()

        if self.mode == AUTO:
            label, color = 'AUTONOMOUS - LOCKED', (40, 160, 70)
        elif self.mode in ALERT_MODES:
            label, color = 'AUTONOMOUS', (40, 160, 70)
        elif self._scenario.manual_only:
            label, color = 'PRACTICE - MANUAL', (40, 110, 200)
        else:
            label, color = 'MANUAL', (40, 110, 200)
        box_width = small.size(label)[0] + 36
        self._draw_box(display, small, label, (width // 2 - box_width // 2, 10, box_width, 34), color,
                       (255, 255, 255))

        if self.mode == PRE_ALERT:
            remaining = self._pre_alert - (now - self._alert_time)
            self._draw_banner(display, big, small, width, 'PRE-ALERT',
                              '%s - takeover request in %.1f s' % (self._scenario.message, max(remaining, 0.0)),
                              (240, 180, 20), (30, 30, 30), remaining / self._pre_alert)
        elif self.mode == TOR:
            remaining = TOR_SECONDS - (now - self._tor_time)
            flash = int(now * 4) % 2 == 0
            self._draw_banner(display, big, small, width, 'TAKE OVER NOW!',
                              'Manual driving in %.1f s' % max(remaining, 0.0),
                              (220, 30, 30) if flash else (150, 20, 20), (255, 255, 255),
                              remaining / TOR_SECONDS)

    @staticmethod
    def _draw_box(display, font, text, rect, background, foreground):
        surface = pygame.Surface(rect[2:])
        surface.set_alpha(220)
        surface.fill(background)
        display.blit(surface, rect[:2])
        label = font.render(text, True, foreground)
        display.blit(label, label.get_rect(center=(rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)))

    def _draw_banner(self, display, big, small, width, title, subtitle, background, foreground, fraction):
        banner_width = max(520, big.size(title)[0] + 60, small.size(subtitle)[0] + 60)
        rect = (width // 2 - banner_width // 2, 56, banner_width, 110)
        surface = pygame.Surface(rect[2:])
        surface.set_alpha(230)
        surface.fill(background)
        display.blit(surface, rect[:2])
        title_surface = big.render(title, True, foreground)
        display.blit(title_surface, title_surface.get_rect(center=(width // 2, rect[1] + 35)))
        subtitle_surface = small.render(subtitle, True, foreground)
        display.blit(subtitle_surface, subtitle_surface.get_rect(center=(width // 2, rect[1] + 72)))
        bar_width = int((rect[2] - 40) * min(max(fraction, 0.0), 1.0))
        pygame.draw.rect(display, foreground, (rect[0] + 20, rect[1] + 92, bar_width, 8))


# ==============================================================================
# -- game_loop() ---------------------------------------------------------------
# ==============================================================================


def game_loop(args):
    started = datetime.datetime.now()
    pygame.init()
    pygame.font.init()
    world = None
    traffic = []
    scenario = None
    recorder = None
    client = None
    audio = None
    driver_input = None

    try:
        driver_input = WheelInput(args) if args.input == 'wheel' else KeyboardInput()
        client = carla.Client(args.host, args.port)
        client.set_timeout(60.0)

        sim_world = client.get_world()
        if not sim_world.get_map().name.endswith(MAP_NAME):
            logging.info('Loading %s...', MAP_NAME)
            sim_world = client.load_world(MAP_NAME)
        audio = AudioEngine(not args.no_audio_engine)  # after the map change, so it connects to Town04

        remove_stale_actors(client, sim_world)

        flags = pygame.HWSURFACE | pygame.DOUBLEBUF
        if args.window_pos:
            # borderless window over the monitors, its top-left corner at --window-pos
            os.environ['SDL_VIDEO_WINDOW_POS'] = args.window_pos
            flags |= pygame.NOFRAME
        display = pygame.display.set_mode((args.width, args.height), flags)
        display.fill((0, 0, 0))
        pygame.display.flip()

        hud = HUD(args.width, args.height)
        world = World(sim_world, hud, args)
        add_driver_view(world, args)

        # Put the vehicle on the figure-8 highway.
        carla_map = world.map
        anchor = carla_map.get_waypoint(carla_map.get_spawn_points()[START_SPAWN_INDEX].location)
        routes = {lane: build_loop_route(carla_map, lane_waypoint(anchor, lane)) for lane in LANES}
        route = routes[args.lane]
        logging.info('Figure-8 route, lane %d: %d waypoints, ~%.0f m',
                     args.lane, len(route), len(route) * ROUTE_RESOLUTION)
        start = route[0].transform
        start.location.z += 0.5
        world.player.set_transform(start)
        sim_world.wait_for_tick()  # let the new position reach the client

        route_planner = GlobalRoutePlanner(carla_map, ROUTE_RESOLUTION)
        follower = LoopFollower(world.player, route, args.speed, carla_map, route_planner)
        # in scenario 2 cars driving the lane that gets closed would run into the work zone
        traffic_lanes = tuple(lane for lane in LANES if not (args.scenario == 2 and lane in WORKZONE_LANES))
        traffic = spawn_traffic(sim_world, routes, args, client.get_trafficmanager(), traffic_lanes)
        last_refresh = time.monotonic()
        recorder = TrialRecorder(world, traffic, driver_input, args, started, args.post_window)
        if args.scenario == 2 and args.lane in WORKZONE_LANES:
            logging.warning('The car drives in lane %d, which the work zone closes', args.lane)
        scenario = make_scenario(args, sim_world, routes, route)
        sound = AlertSound(not args.no_sound)
        experiment = TakeoverExperiment(world, follower, driver_input, recorder, route, scenario, sound,
                                        auto_alert=not args.no_auto_alert, pre_alert=args.pre_alert)
        fonts = (pygame.font.Font(pygame.font.get_default_font(), 40),
                 pygame.font.Font(pygame.font.get_default_font(), 24))

        sim_world.wait_for_tick()
        clock = pygame.time.Clock()
        while True:
            clock.tick_busy_loop(60)
            now = time.monotonic()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYUP and event.key == K_ESCAPE:
                    return
                if event.type == pygame.KEYDOWN:
                    if event.key == K_TAB:
                        next_view(world)
                    elif event.key == K_F1:
                        world.hud.toggle_info()
                experiment.handle_event(event, now)
            prune_traffic(traffic, sim_world)
            experiment.tick(clock, now)
            if traffic and now - last_refresh > NPC_PATH_REFRESH:
                last_refresh = now
                for npc in traffic:
                    npc.refresh_path()
            world.tick(clock)
            world.render(display)
            experiment.render(display, fonts, now)
            pygame.display.flip()

    finally:
        if driver_input is not None:
            driver_input.close()  # releases the wheel's force feedback
        if audio is not None:
            audio.stop()
        if recorder is not None:
            recorder.close()
        if traffic:
            destroy_actors(client, [npc.actor for npc in traffic])
        if scenario is not None:
            scenario.cleanup(client)
        if world is not None:
            if getattr(world.camera_manager, 'side_views', None):
                destroy_side_views(world.camera_manager)
            world.destroy()
        pygame.quit()
        if recorder is not None:
            recorder.write_reports()


# ==============================================================================
# -- main() --------------------------------------------------------------------
# ==============================================================================


def main():
    argparser = argparse.ArgumentParser(description='Takeover (TOR) experiment on the Town04 figure-8 highway')
    argparser.add_argument('--host', metavar='H', default='127.0.0.1', help='IP of the host server (default: 127.0.0.1)')
    argparser.add_argument('-p', '--port', metavar='P', default=2000, type=int, help='TCP port (default: 2000)')
    argparser.add_argument('--res', metavar='WIDTHxHEIGHT', default='7680x1440',
                           help='window resolution (default: 7680x1440, three 2560x1440 monitors)')
    argparser.add_argument('--window-pos', metavar='X,Y', default='-2560,0',
                           help='top-left corner of a borderless window on the desktop, "" for a normal window '
                                '(default: -2560,0, the left edge of the left monitor)')
    argparser.add_argument('--screens', metavar='N', type=int, default=3,
                           help='monitors side by side in the window, one camera each (default: 3)')
    argparser.add_argument('--screen-fov', metavar='DEG', type=float, default=60.0,
                           help='horizontal field of view per monitor in the driver views; the side cameras '
                                'are turned by this much (default: 60)')
    argparser.add_argument('--no-mirrors', action='store_true',
                           help='do not show the camera images in the car\'s side and rear-view mirrors')
    argparser.add_argument('--render-scale', metavar='F', type=float, default=1.0,
                           help='cameras render at F x the monitor resolution and are scaled up, '
                                'e.g. 0.5 for more FPS (default: 1.0)')
    argparser.add_argument('--filter', metavar='PATTERN', default=DEFAULT_VEHICLE,
                           help='vehicle blueprint (default: "%s")' % DEFAULT_VEHICLE)
    argparser.add_argument('--view', choices=['driver', 'chase'], default='driver',
                           help='start in the driver\'s seat or behind the car; TAB switches (default: driver)')
    argparser.add_argument('--speed', metavar='KMH', default=80.0, type=float,
                           help='autonomous target speed in km/h (default: 80)')
    argparser.add_argument('--gamma', default=2.2, type=float, help='camera gamma correction (default: 2.2)')
    argparser.add_argument('--lane', type=int, choices=LANES, default=DEFAULT_LANE,
                           help='lane to drive in, 1 = next to the median (default: %d)' % DEFAULT_LANE)
    argparser.add_argument('--vehicles', metavar='N', type=int, default=0,
                           help='number of traffic vehicles to place on the highway (default: 0)')
    argparser.add_argument('--npc-speed', metavar='KMH', type=float, default=70.0,
                           help='traffic vehicle speed in km/h (default: 70)')
    argparser.add_argument('--scenario', type=int, choices=sorted(SCENARIOS), default=1,
                           help='0 practice (manual driving only), 1 highway exit, 2 work zone after the '
                                'first lap, 3 sudden fog (default: 1)')
    argparser.add_argument('--alert-lead', metavar='SEC', type=float, default=None,
                           help='seconds before the event point at which the pre-alert starts '
                                '(default: 10 / 20 / 0 for scenario 1 / 2 / 3)')
    argparser.add_argument('--exit-at', metavar='METERS', type=float, default=None,
                           help='scenario 1: exit point, m from the start (default: end of the overpass; '
                                '-1: no exit point)')
    argparser.add_argument('--workzone-at', metavar='METERS', type=float, default=None,
                           help='scenario 2: where the work zone taper starts, m from the start '
                                '(default: %d)' % WORKZONE_AT)
    argparser.add_argument('--fog-at', metavar='METERS', type=float, default=None,
                           help='scenario 3: where the fog starts to thicken, m from the start (default: %d)' % FOG_AT)
    argparser.add_argument('--fog-threshold', metavar='DENSITY', type=float, default=FOG_THRESHOLD,
                           help='scenario 3: fog density that starts the pre-alert (default: %g)' % FOG_THRESHOLD)
    argparser.add_argument('--fog-max', metavar='DENSITY', type=float, default=FOG_MAX,
                           help='scenario 3: densest fog, 0-100 (default: %g)' % FOG_MAX)
    argparser.add_argument('--fog-rise', metavar='SEC', type=float, default=FOG_RISE,
                           help='scenario 3: seconds from the fog point to the threshold (default: %g)' % FOG_RISE)
    argparser.add_argument('--fog-peak-after', metavar='SEC', type=float, default=FOG_PEAK_AFTER,
                           help='scenario 3: the fog is densest this many seconds after the takeover '
                                '(default: %g)' % FOG_PEAK_AFTER)
    argparser.add_argument('--pre-alert', metavar='SEC', type=float, default=PRE_ALERT_SECONDS,
                           help='seconds from the pre-alert to the TOR; scenario 3 scales the fog rate after the '
                                'pre-alert so the density at the TOR stays the same (default: %g)' % PRE_ALERT_SECONDS)
    argparser.add_argument('--no-sound', action='store_true', help='no alert sounds')
    argparser.add_argument('--no-audio-engine', action='store_true',
                           help='do not start the vehicle sounds of carla-audio-engine')
    argparser.add_argument('--no-auto-alert', action='store_true',
                           help='do not start the pre-alert automatically, only with the P key')
    argparser.add_argument('--post-window', metavar='SEC', type=float, default=POST_WINDOW,
                           help='seconds after the takeover that are scored as the takeover period (default: %g)' % POST_WINDOW)
    argparser.add_argument('--no-log', action='store_true', help='do not write the Data/*.csv log')
    argparser.add_argument('--input', choices=['auto', 'keyboard', 'wheel'], default='auto',
                           help='driver input device; auto: the wheel if one is connected, else the keyboard '
                                '(default: auto)')
    argparser.add_argument('--wheel-force', metavar='PERCENT', default=80.0, type=float,
                           help='force feedback: how hard the wheel pulls back to the center, 0 = off '
                                '(default: 80)')
    argparser.add_argument('--joystick', metavar='N', default=0, type=int,
                           help='wheel device index, see --wheel-test (default: 0)')
    argparser.add_argument('--steer-axis', metavar='N', default=0, type=int,
                           help='steering wheel axis number (default: 0)')
    argparser.add_argument('--throttle-axis', metavar='N', default=2, type=int,
                           help='throttle pedal axis number (default: 2)')
    argparser.add_argument('--brake-axis', metavar='N', default=1, type=int,
                           help='brake pedal axis number (default: 1, Thrustmaster T300 RS; 3 on a Logitech G29)')
    argparser.add_argument('--pedal-rest', metavar='1|-1', default=1, type=int, choices=[1, -1],
                           help='axis value of a released pedal (default: 1, pressed = -1)')
    # Wheel buttons: --wheel-setup saves them to wheel_buttons.json; these options override the file.
    argparser.add_argument('--handbrake-button', metavar='N', type=int,
                           help='wheel button for the hand-brake (default: from --wheel-setup)')
    argparser.add_argument('--reverse-button', metavar='N', type=int,
                           help='wheel button that toggles reverse (default: from --wheel-setup)')
    argparser.add_argument('--left-blinker-button', metavar='N', type=int,
                           help='wheel button for the left turn signal (default: from --wheel-setup, Z key always works)')
    argparser.add_argument('--right-blinker-button', metavar='N', type=int,
                           help='wheel button for the right turn signal (default: from --wheel-setup, X key always works)')
    argparser.add_argument('--light-button', metavar='N', type=int,
                           help='wheel button that switches the lights, position -> low beam -> fog -> off '
                                '(default: from --wheel-setup, L key always works)')
    argparser.add_argument('--high-beam-button', metavar='N', type=int,
                           help='wheel button for the high beam (default: from --wheel-setup, SHIFT+L always works)')
    argparser.add_argument('--interior-button', metavar='N', type=int,
                           help='wheel button for the interior light (default: from --wheel-setup, I key always works)')
    argparser.add_argument('--horn-button', metavar='N', type=int,
                           help='wheel button for the horn (default: from --wheel-setup, H key always works)')
    argparser.add_argument('--wheel-test', action='store_true',
                           help='print live wheel axis and button values, then exit')
    argparser.add_argument('--wheel-setup', action='store_true',
                           help='press the wheel buttons one by one when asked (reverse, turn signals, horn, ...); '
                                'saves them to wheel_buttons.json next to this script, then exits')
    args = argparser.parse_args()
    if args.pre_alert <= 0:
        argparser.error('--pre-alert must be greater than 0')

    args.width, args.height = [int(x) for x in args.res.split('x')]
    if os.name == 'nt':
        try:
            # real pixels: without this, Windows display scaling would enlarge the window past the monitors
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
    # Options the stock World class expects.
    args.sync = False
    args.generation = 'All'
    args.rolename = 'hero'

    if args.wheel_test:
        wheel_test(args)
        return
    if args.wheel_setup:
        wheel_setup(args)
        return

    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)
    logging.info('listening to server %s:%s', args.host, args.port)
    print(__doc__)

    if args.input == 'auto':
        pygame.joystick.init()
        args.input = 'wheel' if pygame.joystick.get_count() > 0 else 'keyboard'
    logging.info('Driver input: %s', args.input)

    try:
        game_loop(args)
    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')


if __name__ == '__main__':
    main()
