#!/usr/bin/env python

"""
Takeover (TOR) experiment on the Town04 figure-8 highway.

The vehicle starts in autonomous mode in lane 3 (the third lane from the median)
and loops the figure-8 highway forever, with 10 traffic cars (--vehicles N).
--scenario 0 is a practice drive: manual driving from the start.

    Driver input      : steering wheel + pedals if one is connected, else keyboard
                        (--input wheel / keyboard to choose). Wheel buttons (reverse,
                        turn signals, horn, lights, ...): set them up once with --wheel-setup.
                          keyboard : W/A/S/D or ARROWS
                          wheel    : steering wheel, throttle pedal, brake pedal
                        Autonomous driving is locked until the TOR: input is
                        ignored, also during the pre-alert. From the TOR on, new driver input (a move from
                        where the wheel and pedals were at the TOR) switches
                        to manual driving immediately.
    P                 : start a takeover sequence (autonomous mode only)
                          0 s   pre-alert shown, chime
                          60 s  TOR (takeover request) shown, repeating beeps (--pre-alert)
                          65 s  manual driving is forced if there was no input (TOR + 5 s)
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
    K                 : NDRT chat: the team's follow-up messages now (else after the takeover)

    TAB               : next camera position: driver's seat, windshield (no steering wheel),
                        left mirror, right mirror, behind the car, hood, ...
    F1                : toggle HUD
    ESC               : quit

Scenarios (--scenario N). Each has an event point on the loop; the TOR comes
--tor-lead seconds before the car reaches it, once per pass, so the pre-alert starts
--pre-alert seconds earlier still (--alert-lead: set the pre-alert's lead directly):
    0  practice       manual driving from the start, for getting used to the wheel and
                      pedals: no autonomous mode, no pre-alert (P and E do nothing),
                      nothing logged; clear noon weather
    1  highway exit   event: the exit point (end of the overpass, --exit-at)
                      TOR 5 s before it
    2  work zone      after the first lap, lanes 3 and 4 are closed further ahead
                      (cones, barriers, signs, work vehicles, --workzone-at);
                      TOR 5 s before the cones reach lane 3: no input until the forced
                      takeover, and the car runs into them
    3  sudden fog     at the fog point (--fog-at) the fog starts to thicken from 0;
                      pre-alert when it reaches --fog-threshold (45, after --fog-rise
                      20 s); it keeps thickening and reaches --fog-max (90)
                      --fog-peak-after (10) s after the takeover
    4  accident       a crash closes lanes 3 and 4 (crashed cars, police car, ambulance,
                      cones, signs, --accident-at); it appears on the second pass;
                      TOR 5 s before the cones reach lane 3, as in scenario 2

After the takeover cars drive next to the car (EscortCars). Scenario 3: beside it in the
lanes next to it for 30 s, so the driver keeps the lane (scenario 1: none, the driver leaves
at the exit). Scenarios 2 and 4: from the takeover on, cars in lanes 1 and 3 a little ahead; the lane 3 car
falls back out of view before the closure; the lane 1 car stays level with the car. 250 m past the
closure a broken-down van (hazard lights) stands in lane 2 only: with lane 1 taken, the driver has to
move over to lane 3. Past the van the lane 1 car drives off. Once the driver has taken over and is
150 m past the van, the scene is removed with its signs (no more pre-alerts for it).

In curves the autonomous car slows down below --speed (about 3 m/s^2 sideways at most).

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

--glasses PHONE_IP shows the pre-alert and the TOR on Meta Ray-Ban Display glasses
instead of the screen: TORApp on the phone (TORApp folder) receives the state over
Wi-Fi and puts it on the glasses. --glasses usb: over the USB cable with USB tethering
on in the phone, which finds the phone's address by itself. Its alert sounds (chime, beeps, click) come
from the glasses' speakers and from the simulator PC as well. The vehicle
sounds of the audio engine stay on the PC.

During the pre-alert the glasses also show an intervention text, chosen in
intervention_config.json next to this script (--intervention-config):
    "intervention"      none (control: the pre-alert only), driving (driving situation,
                        Endsley SA levels 1-3) or NDRT (ready-to-resume for the NDRT)
    "format"            summary (statements, read only) or question (questions);
                        both show one line at a time, each for "question_seconds"
    "delay_seconds"     from the pre-alert to the text
With the defaults (delay 5, question 10): 0-5 s pre-alert only, 5-15 / 15-25 /
25-35 s SA level or ready-to-resume step 1 / 2 / 3 (NDRT summary: 완료된 작업 ->
진행중이던 작업 -> 앞으로 남은 작업), 35-60 s nothing, 60 s TOR. The glasses show the PRE-ALERT
banner for the first 5 s only (TORApp), never the time left; after that only the
text and the mode box.
The text is NDRT_scripts/scenario<N>_<intervention>_<format>.txt: one line per
displayed line, # starts a comment line.

Test run: "test": true in the config (intervention_none.json): the pre-alert comes
"test_alert_after" (10) s after the start and lasts "test_pre_alert" (5) s, and the car starts
so far before the event point that the TOR still comes the scenario's TOR lead before it
(the work zone and the accident are there from the start):
    python _Experiment\\takeover_experiment.py --scenario 4 --intervention-config _Experiment\\intervention_none.json

The NDRT is a team group chat that looks like KakaoTalk, on the NDRT laptop: kakao_ndrt.py runs
there (started before the drive, with the same --scenario), the participant enters their name and
writes the room's notice from what the team said (kakao_sets/scenario<N>.json). --ndrt <laptop IP>
connects this program to it: after the takeover the team adds more messages, silently, which the
notice has to take in: once the car is past the scene (scenarios 2 and 4; at the latest
NDRT_FOLLOWUP_LATEST s after the takeover), else NDRT_FOLLOWUP_AFTER s after the takeover; K: now.
The pre-alert, the TOR and the takeover are logged in the laptop's ndrt.jsonl too, on its clock.
During the pre-alert and the TOR the team presses for the notice (kakao_sets "nudges", each "after"
s after the pre-alert): the message goes to the chat and the KakaoTalk sound plays on this PC
(kakao_app/kakao.mp3; the chat page itself stays silent for these).

NDRT + summary: the text is the participant's own ready-to-resume summary instead: kakao_ndrt.py on
the laptop sends the notice draft to ChatGPT (OpenAI API key there: OPENAI_API_KEY or
_Experiment/openai_api_key.txt).
The summary is requested RTR_LEAD (5) s before the pre-alert (scenario 1/2/4: from the distance
and speed, 3: from the fog rate; P key: right away, always a new one), and also by the RtR button
in TORApp. When the text is due, the newest summary requested since then is shown; if none has
arrived, the NDRT_scripts file is shown instead (logged). Requests and results go to rtr.jsonl.
(The Gmail extension that did this before is in legacy/gmailextension.)

Run from the CARLA_0.9.16 root folder:

    python _Experiment\\takeover_experiment.py
    python _Experiment\\takeover_experiment.py --input wheel
    python _Experiment\\takeover_experiment.py --lane 1 --vehicles 15
    python _Experiment\\takeover_experiment.py --glasses 192.168.0.23
    python _Experiment\\takeover_experiment.py --glasses usb   (USB tethering)
    python _Experiment\\takeover_experiment.py --scenario 4 --wireless   (phone and NDRT laptop over Wi-Fi, devices.json)
    python _Experiment\\takeover_experiment.py --phone-cluster   (gauges on a phone, phone_cluster.py)
    python _Experiment\\takeover_experiment.py --wheel-test   (find axis numbers)
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
import threading
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
    from pygame.locals import K_k
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

PYTHON_API = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'PythonAPI')
sys.path.append(os.path.join(PYTHON_API, 'carla'))
sys.path.append(os.path.join(PYTHON_API, 'examples'))  # manual_control
from agents.navigation.basic_agent import BasicAgent  # pylint: disable=import-error
from agents.navigation.global_route_planner import GlobalRoutePlanner  # pylint: disable=import-error
from agents.navigation.local_planner import RoadOption  # pylint: disable=import-error

# Reuse the world, HUD and camera of the stock manual_control example.
from manual_control import HUD, CameraManager, World  # pylint: disable=import-error

from road_signs import GREEN, ORANGE, ImageSign, RoadSigns, Sign, preload  # next to this script

# ==============================================================================
# -- constants -----------------------------------------------------------------
# ==============================================================================

MAP_NAME = 'Town04'
# Spawn point on the figure-8 highway (road 35). Following one of its lanes with
# the straightest choice at every junction closes the loop after ~3045 m. That
# works for lanes 1-3 (lane 1 is next to the median); lane 4 is the exit lane.
START_SPAWN_INDEX = 15
DEFAULT_LANE = 3
DEFAULT_VEHICLE = 'vehicle.lincoln.mkz_2020'  # detailed interior with an instrument cluster
DRIVER_VIEW_PITCH = 4.0    # degrees up, driver seat and windshield views (the car's own cluster is out of view;
                           # higher cuts off the bottom of the left mirror on 3 x 60 degree monitors)
WINDSHIELD_FORWARD = 0.55  # m in front of the driver's eyes: past the steering wheel (every car model has one)
MIRROR_FOV = 60.0          # degrees, side mirror views
DRIVER_VIEWS = (0, 1)      # driver seat, windshield: the views that use all monitors (--screens)
# Mirror glass, measured on the Lincoln MKZ 2020 from where its mirrors appear in the driver views.
# Side mirrors, per driver view (driver seat, windshield): (glass center, glass size, glass outline).
# Center: x and z as shares of the car's half length / height, y m outside the car. Size: m, as seen
# from that view (the glass is seen at an angle). Outline: (x, y) shares of the glass's bounding box;
# in the windshield view the window pillar hides the left part of the right glass.
LEFT_MIRROR = {
    0: ((0.2800, 0.0512, 1.3944), (0.234, 0.121),
        [(0.0, 0.42), (0.14, 0.11), (0.26, 0.02), (0.36, 0.0), (0.8, 0.02), (0.87, 0.08), (0.93, 0.17),
         (0.95, 0.23), (1.0, 0.54), (0.99, 0.73), (0.97, 0.86), (0.92, 0.99), (0.64, 0.92), (0.05, 0.72)]),
    1: ((0.2802, 0.0506, 1.3889), (0.1359, 0.1279),
        [(0.0, 0.39), (0.0, 0.33), (0.12, 0.09), (0.2, 0.02), (0.25, 0.0), (0.51, 0.0), (0.77, 0.04),
         (0.85, 0.09), (0.91, 0.18), (1.0, 0.53), (1.0, 0.78), (0.94, 1.0), (0.07, 0.63), (0.03, 0.56)]),
}
RIGHT_MIRROR = {
    # measured again at DRIVER_VIEW_PITCH 4 from the bare glass in the window
    0: ((0.2786, 0.0535, 1.3983), (0.168, 0.1185),
        [(0.0, 0.5), (0.07, 0.19), (0.16, 0.06), (0.22, 0.01), (0.7, 0.03), (0.76, 0.07), (0.86, 0.18),
         (0.98, 0.42), (1.0, 0.58), (0.97, 0.75), (0.94, 0.81), (0.5, 0.93), (0.28, 0.99), (0.05, 0.99), (0.0, 0.76)]),
    1: ((0.2782, 0.0540, 1.3990), (0.1024, 0.1105),
        [(0.11, 0.05), (0.18, 0.0), (0.76, 0.0), (0.87, 0.07), (0.97, 0.22), (1.0, 0.36), (0.99, 0.57),
         (0.97, 0.77), (0.93, 0.83), (0.59, 0.92), (0.21, 0.99), (0.0, 1.0)]),
}
MIRROR_INSET_FOV = 40.0            # degrees, side mirror images on the glass
# Rear-view mirror glass, m from the driver's eyes (forward, right, up). The windshield view is in
# front of it, so there its image stays where the driver's seat view shows the glass.
REAR_MIRROR = (0.571, 0.007, 0.1085)
REAR_MIRROR_SIZE = (0.249, 0.0795)  # m
# Its outline bends where the glass crosses from the middle monitor to the right one. Measured at
# DRIVER_VIEW_PITCH 4 from the bare glass in the window (3 x 2560 x 1440, 60 degrees per monitor).
REAR_MIRROR_OUTLINE = [(0.0, 0.58), (0.02, 0.19), (0.04, 0.06), (0.1, 0.01), (0.34, 0.0), (0.94, 0.4), (0.98, 0.46),
                       (0.99, 0.57), (1.0, 0.91), (0.99, 0.98), (0.94, 1.0), (0.34, 0.76), (0.08, 0.76), (0.01, 0.72),
                       (0.0, 0.62)]
REAR_MIRROR_FOV = 45.0             # degrees
MIRROR_FPS = 15.0  # images per second of the mirror cameras: each camera is a full render pass on the server
# The gauges (throttle pedal, speed) on a tablet standing at the bottom middle of the middle monitor,
# where a car's instrument cluster sits (the car's own cluster is below the view, DRIVER_VIEW_PITCH).
CLUSTER_PANEL = (0.40, 0.21)   # tablet width, height: shares of the monitor; on the bottom edge
CLUSTER_BEZEL = (22, 23, 26)   # the tablet's frame
CLUSTER_EDGE = (78, 80, 86)    # its rim catching the light
CLUSTER_SCREEN = ((24, 29, 38), (9, 11, 15))  # screen, top and bottom of its gradient
BLINKER_ON = (40, 220, 90)     # turn signal arrow, lit
BLINKER_DIM = (46, 54, 66)     # its outline while off (and the dark half of its blink)
BLINKER_HZ = 1.5               # blinks per second, as a car's turn signal
MODE_BOX_MARGIN = 20           # px from the window's right and bottom edges: AUTONOMOUS / MANUAL box
CLUSTER_TEXT = (235, 240, 245)
CLUSTER_DIM = (120, 130, 140)
CLUSTER_NEEDLE = (235, 60, 40)
# Round gauges: throttle pedal (left, %) and speed (right, km/h); 0 at the lower left, full scale
# GAUGE_SWEEP degrees clockwise. The needles follow the value like real ones, a share per frame.
GAUGE_START = 210.0
GAUGE_SWEEP = 240.0
GAUGE_MAX_SPEED = 200.0
GAUGE_FOLLOW = 0.25
# --screens 1: the side mirrors are out of the single monitor's view, so they are drawn as
# insets at its lower left and right edges instead (height and center as shares of the monitor).
SIDE_INSET_HEIGHT = 0.18
SIDE_INSET_Y = 0.70
SIDE_INSET_MARGIN = 20             # px from the monitor edge
WHEEL_SETUP_WAIT = 10         # seconds --wheel-setup waits for each button
PEDAL_DEADZONE = 0.02        # pedal travel below this reads 0 (released pedals are not exactly at rest)
# The MKZ's engine brakes with the throttle released (damping_rate_zero_throttle_clutch_engaged
# 2.0: from 80 km/h to a stop in 10 s). With this it slows down like an electric car's regenerative
# braking when the throttle pedal is released: measured 1.8 m/s^2 at 82 km/h, 1.9 at 58, 1.3 at
# 20 (Tesla Model 3, standard regen: about 0.19 g = 1.9 m/s^2, SAE 2020-01-0883; 0.35 gave 0.3).
ENGINE_DAMPING = 1.0
# Stronger brakes, so that the brake pedal fully pressed still stops the car as the default MKZ.
BRAKE_TORQUE_SCALE = 1.35
# brake pedal travel -> CARLA brake, (travel, brake): the default MKZ's deceleration from 80 km/h
# (2.9 m/s^2 at 5 % travel, 3.8 at 20 %, 6.0 at 50 %, 7.5 fully pressed). Refitted with ENGINE_DAMPING 1.0
# (its regen adds to the brake) so each travel brakes as hard as with the curve made for 0.35.
BRAKE_CURVE = [(0.0, 0.0), (0.05, 0.25), (0.1, 0.30), (0.2, 0.39), (0.3, 0.50), (0.5, 0.63), (1.0, 0.77)]
# CARLA's throttle is a share of the engine torque at any speed: a slightly pressed pedal would keep
# accelerating to well past 100 km/h. The wheel's throttle pedal instead asks for an acceleration
# that fades out at a settle speed, both growing with the pedal travel like in a real car, and a
# controller finds the CARLA throttle for it (see PedalThrottle).
# m/s^2 asked for with the pedal fully pressed, by speed (km/h, m/s^2), before the fade towards the
# settle speed (1 - (v / PEDAL_FULL_SPEED)^2), so that with it the car accelerates like a mid-size
# sedan at full throttle: 3.8 m/s^2 from standstill, 3.0 at 60 km/h, 2.3 at 80, 1.3 at 120; 0-100 km/h
# in about 9.5 s, 80-120 km/h in about 6.5 s. (Before: 4.0 at any speed, 0-100 in 7.6 s, 80-120 in 3.7 s.)
PEDAL_ACCEL_FULL = [(0.0, 3.8), (30.0, 3.68), (60.0, 3.3), (80.0, 2.74), (100.0, 2.4), (120.0, 2.03), (150.0, 1.6), (180.0, 1.05)]
PEDAL_ACCEL_CURVE = 1.2      # acceleration asked for grows with travel ** this: gentle at small travel
PEDAL_FULL_SPEED = 200.0     # km/h the car settles at with the pedal fully pressed, proportionally less with less
# CARLA throttle that holds the MKZ 2020 (with ENGINE_DAMPING) at a speed on level road, (km/h, throttle),
# measured on the loop's flat straight at 1900-2300 m (not monotonic: the automatic shifts up)
HOLD_THROTTLE = [(0.0, 0.20), (8.0, 0.23), (33.0, 0.29), (53.0, 0.28), (80.0, 0.25), (112.0, 0.39), (130.0, 0.50),
                 (190.0, 0.90)]
# After the takeover the car keeps the speed it had (like the autopilot's engine power) until the driver
# presses the throttle or the brake: throttle = HOLD_THROTTLE + PI on the speed error (SpeedHold).
SPEED_HOLD_GAIN_P = 0.03     # throttle per km/h below the takeover speed
SPEED_HOLD_GAIN_I = 0.01     # throttle per km/h per second (hills)
# Pedal released: like an automatic, the car creeps forward at a walking pace unless the brake is pressed.
CREEP_SPEED = 7.0            # km/h
CREEP_ACCEL = 0.5            # m/s^2 creeping off from standstill
PEDAL_GAIN_P = 0.10         # throttle per m/s^2 of acceleration missing
PEDAL_GAIN_I = 0.30          # throttle per m/s^2 per second (makes up for hills and HOLD_THROTTLE's error)
PEDAL_ACCEL_FILTER = 0.3     # seconds, smoothing of the measured acceleration
WHEEL_SPRING_STANDSTILL = 0.6  # force feedback: centering force when standing, share of --wheel-force
WHEEL_SPRING_FULL_SPEED = 80.0  # km/h at which the centering force reaches --wheel-force
WHEEL_DAMPING = 0.7            # damping: resists turning the wheel quickly, share of --wheel-force
WHEEL_FRICTION = 0.5           # friction: resists turning the wheel at all, share of --wheel-force
# The spring's force grows with the wheel angle, so it is next to nothing over the first few degrees
# (and the wheel's motor does not even start for very small forces). A constant force pushes the
# wheel back to the center as well, building up over the first WHEEL_CENTER_RAMP of the axis.
WHEEL_CENTER_FORCE = 0.3       # share of --wheel-force (and of the spring's speed scaling)
WHEEL_CENTER_RAMP = 0.03       # axis travel to the full push: ~15 degrees on a 900 degree wheel
WHEEL_CENTER_SIGN = 1          # -1 if the wheel pushes away from the center instead
CURVE_LATERAL_ACCEL = 3.0      # m/s^2 autonomous driving keeps to in curves: slows down before them
CURVE_DECEL = 0.8              # m/s^2 it slows down at before a curve
AUTO_ACCEL = 2.0               # m/s^2 at most it speeds up at (from standstill, out of a curve)
AUTO_BRAKE_OVER = 8.0          # km/h over its target speed at which it brakes (below: less throttle)
AUTO_GAIN_P = 0.02             # throttle per km/h off the target speed
AUTO_GAIN_I = 0.005            # throttle per km/h per second (hills, HOLD_THROTTLE's error)
AUTO_I_RANGE = 5.0             # km/h: the I part adds up only this close to the target (no wind-up while speeding up)
AUTO_THROTTLE_RATE = 0.3       # throttle change per second at most: the engine sound changes slowly
# manual_control's camera positions, in its order (they come after the experiment's views)
STOCK_VIEW_NAMES = ['Behind the car', 'Hood', 'Front side', 'Far behind', 'Low side']
LANES = (1, 2, 3)
NPC_SLOT_SPACING = 40.0   # meters between possible traffic positions in a lane
NPC_CLEARANCE = 60.0      # no traffic closer than this to the start position
NPC_NEAR_RANGE = 300.0    # traffic fills this stretch around the start first
NPC_EXCLUDED = ('vehicle.micro.microlino',)  # base_type car, but drives badly in Traffic Manager traffic
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
# Signs (road_signs.py) on the right shoulder: (m before the event point, text lines, arrow)
SIGN_SHOULDER = 1.5 * LANE_WIDTH + 2.5  # m right of lane 3's center: past the edge of lane 4
SIGN_HEIGHT = 2.5                       # m from the road to the bottom of the board
SIGN_IMAGE_WIDTH = 2.4                  # m: image signs (WORKZONE_SIGNS)
SIGN_PLATE_LETTER = 0.6                 # m: letters on the plate under an image sign
# where lanes 3 and 4 start to close (scenarios 2 and 4): a square orange board with a white arrow to
# the left, over the line between lanes 3 and 4, so the start of the closure shows from afar
ARROW_BOARD_IMAGE = 'arrow_left.png'
ARROW_BOARD_WIDTH = 2.2                 # m (square)
ARROW_BOARD_PIXELS = 24                 # across: thick lines, so it shows from 150 m+
ARROW_BOARD_HEIGHT = 1.0                # m from the road to the bottom of the board
ARROW_BOARD_OFFSET = 0.5 * LANE_WIDTH   # m right of lane 3's center: the line between lanes 3 and 4
EXIT_SIGNS = ((1000.0, ['EXIT', '1 km'], None), (500.0, ['EXIT', '500 m'], None), (0.0, ['EXIT'], 'up_right'))
# (m before the event point, text lines, arrow[, image]): with an image (in SIGN_IMAGE_DIR) the
# lines go on a small plate under the picture, e.g. a triangular warning sign above "1 km"
# One triangular warning sign before the scene, no distances and no arrows (an arrow ahead of time
# makes drivers change lanes early; the one arrow is the arrow board where the lanes start to close).
SCENE_SIGN_BEFORE = 200.0     # m before the scene
WORKZONE_SIGNS = ((SCENE_SIGN_BEFORE, [], None, 'roadwork.png'),)
ACCIDENT_AT = 880.0           # scenario 4: the crashed cars, m from the start (straight, 4 lanes, 180 m+
                              # from the rest of the loop: not in view from the overpass before it)
ACCIDENT_SPAWN_AHEAD = 2300.0  # m ahead of the ego car at which the scene appears: beyond view, and
                               # farther than the pre-alert comes (~1.7 km at 80 km/h)
ACCIDENT_MAX_WAIT = 15.0      # s it waits for traffic to pass the scene, as WORKZONE_MAX_WAIT
ACCIDENT_START = -120.0       # m: the scene from the warning sign before the crash ...
ACCIDENT_END = 60.0           # ... to the last cone after it
ACCIDENT_TAPER_FROM = -50.0   # m from the crashed cars where the cones start closing lane 3 ...
ACCIDENT_TAPER_TO = -10.0     # ... and where they reach the edge of lane 2
CAR_HALF_WIDTH = 1.0          # m: the ego car's right side, for where the cones reach it in lane 3
ACCIDENT_LANES = (3, 4)
SCENE_CLEAR_BEHIND = 150.0    # m the car is past the lane 2 obstacle after the takeover when the scene
                              # is removed with its signs (no more pre-alerts for it)
# After the work zone / accident a broken-down van with its hazard lights on stands in lane 2 only, while
# the escort car in lane 1 drives level with the ego car: the driver has to move over to lane 3.
LANE2_OBSTACLE = 'vehicle.mercedes.sprinter'  # its front doors open (VehicleDoor; CARLA has no trunk)
LANE2_TRIANGLE = 'warning_triangle.png'       # SIGN_IMAGE_DIR: a warning triangle on the road behind it ...
LANE2_TRIANGLE_BEHIND = 40.0                  # ... this many m behind the van
LANE2_TRIANGLE_WIDTH = 0.9                    # m (a real one is ~0.45: bigger, so it shows from afar)
LANE2_TRIANGLE_PIXELS = 24                    # across: thick lines
LANE2_OBSTACLE_AFTER = 250.0  # m after the end of the scene (scenario 4: on the straight after the curve)
LANE2_OBSTACLE_SPAWN = 500.0  # m ahead of the ego car (after the takeover) at which it appears ...
LANE2_OBSTACLE_LATEST = 250.0  # ... as soon as no car is near its place, but at this distance at the latest
ACCIDENT_SIGNS = ((SCENE_SIGN_BEFORE, [], None, 'caution.png'),)  # general danger: "!" in the triangle
# After the takeover cars drive level with the ego car in the lanes next to it, so the driver keeps
# the lane and the takeover period measures steady driving (EscortCars). Scenarios 2 and 4: from
# when the car is past the closed lanes; scenario 1: on the left only, the exit is on the right.
ESCORT_SECONDS = 30.0         # s they stay beside the ego car
ESCORT_APPROACH = 6.0         # s to come up from behind, and to drop back again at the end
ESCORT_BEHIND = -45.0         # m behind the ego car where they come from and go back to
ESCORT_OFFSET = {'left': 1.0, 'right': -1.5}  # m ahead of the ego car while beside it
ESCORT_GAP_GAIN = 0.5         # m/s faster than the ego car per m behind their place (they drive, not snap)
ESCORT_CATCH_UP = 8.0         # m/s at most faster or slower than the ego car
ESCORT_SPEED_STEP = 0.12      # m/s their speed changes by at most per frame (about 3.5 m/s^2 at 30 FPS)
ESCORT_GONE = 70.0            # m behind (or ahead) at which one is out of view and removed
# merge plan (scenarios 2 and 4, lanes 3 and 4 closed): cars in lanes 1 and 3 from the takeover on
MERGE_AHEAD = 3.0             # m ahead of the ego car (center to center): a little in front of the driver
MERGE_BEHIND = -25.0          # m behind the ego car where they come from
MERGE_SIDE_CLEAR = 2.6        # m between the ego car's and a lane's centers below which the ego car is
                              # (partly) in that lane: the escort car there gives way
MERGE_AHEAD_CLEAR = 5.5       # m ahead of the ego car (center to center) an escort car keeps ahead from;
                              # one less far ahead falls back behind it instead
MERGE_LANE3_ROOM = 60.0       # m to the closure at least for the lane 3 car to come up at all
MERGE_YIELD = -20.0           # m behind the ego car at most while it is in their lane
MERGE_SLOW = 1.5              # m/s^2 the lane 3 car falls back at (and the lane 1 car pulls away at, at the end)
MERGE_BRAKE = 3.0             # m/s^2 the lane 3 car brakes at, at the latest, to stop before the closure
MERGE_STOP_BEFORE = 15.0      # m before the closure where it stops at the latest
MERGE_CLEAR_AFTER = 20.0      # m the ego car has to be past the lane 2 obstacle before the lane 1 car drives off
# After the pre-alert the traffic leaves (TrafficClearance)
TRAFFIC_CLEAR_RAMP = 10.0        # s over which the traffic cars change speed
TRAFFIC_CLEAR_SPEED = 60.0       # km/h faster (cars ahead) or slower (cars behind, at least 20 km/h) than the ego car
TRAFFIC_CLEAR_DISTANCE = 250.0   # m from the ego car at which a traffic car is removed
TRAFFIC_CLEAR_BEFORE_TOR = 10.0  # s before the TOR at which the cars still there are removed
NPC_PATH_STEP = 5         # use every 5th route waypoint (10 m) for traffic paths
NPC_PATH_LAPS = 2         # laps handed to the Traffic Manager at a time
NPC_PATH_REFRESH = 30.0   # seconds between path refreshes (keeps traffic looping)
ROUTE_RESOLUTION = 2.0  # meters between route waypoints
REFILL_BELOW = 200      # extend the agent's plan when fewer waypoints are left

PRE_ALERT_SECONDS = 60.0  # pre-alert -> TOR
TOR_SECONDS = 5.0        # TOR -> forced manual driving
RTR_LEAD = 5.0           # NDRT summary: request the RtR summary this many seconds before the pre-alert
# Test run ("test": true in the intervention config, e.g. intervention_none.json): the pre-alert comes
# "test_alert_after" s after the start instead of at a place, and lasts "test_pre_alert" s. The car
# starts so far before the event point that the TOR still comes the scenario's TOR lead before it.
NDRT_FOLLOWUP_AFTER = 40.0    # s after the takeover the team's follow-up messages start (scenarios 1, 3)
NDRT_FOLLOWUP_LATEST = 120.0  # ... at the latest, in scenarios 2 and 4 (else: once past the scene)
TEST_ALERT_AFTER = 10.0
SERVER_RETRY = 5.0       # s per try while the CARLA server is not ready yet
COLLISION_LOG_GAP = 2.0  # s: a collision with the same object is logged again only after this
TEST_PRE_ALERT = 5.0

EXPERIMENT_DIR = os.path.dirname(os.path.abspath(__file__))
SIGN_IMAGE_DIR = os.path.join(EXPERIMENT_DIR, 'sign_images')  # pictures for image signs
ROOT = os.path.abspath(os.path.join(EXPERIMENT_DIR, '..'))
LOG_DIR = os.path.join(ROOT, 'Data')
AUDIO_ENGINE_DIR = os.path.join(ROOT, 'carla-audio-engine')  # vehicle sounds, --no-audio-engine
AUDIO_ENGINE_PYTHON = os.path.join(ROOT, 'venv_carla', 'Scripts', 'python.exe')     # has pyfmodex installed
GLASSES_DIR = os.path.join(ROOT, 'TORApp', 'pc')  # tor_glasses.py, --glasses
KAKAO_SOUND = os.path.join(EXPERIMENT_DIR, 'kakao_app', 'kakao.mp3')  # NDRT nudges, played on this PC
KAKAO_VOLUME = 0.8         # of the file's own loudness
POST_WINDOW = 10.0  # seconds after the takeover that count as the takeover period
FALLBACK_EXIT = 1000.0  # exit point (m from the start) if the route has no overpass
FOG_AT = 700.0          # scenario 3: where the fog starts to thicken, m from the start
FOG_THRESHOLD = 45.0    # fog density at which the pre-alert starts
FOG_MAX = 90.0          # densest fog
PRACTICE_WEATHER = 'ClearNoon'  # scenario 0: a carla.WeatherParameters preset
PRACTICE_ISO = 400              # scenario 0: manual exposure of the driver view cameras (brighter than automatic)
FOG_RISE = 20.0         # seconds from the start of the fog to the threshold
FOG_PEAK_AFTER = 10.0   # the fog is densest this many seconds after the takeover
FOG_PRE_ALERT = 5.0     # pre-alert duration the fog rate is set for: longer ones thicken it more slowly
FOG_CLEAR = 5.0         # seconds for the fog to clear when autonomous driving is re-engaged
FOG_FALLOFF = 0.2       # fog stays close to the ground

# Scenario number -> name, pre-alert message, seconds before the event point at which
# the TOR comes (the pre-alert starts PRE_ALERT_SECONDS / --pre-alert before that).
SCENARIOS = {
    0: ('practice', 'Practice drive', 0.0),  # manual driving only, no alerts
    1: ('exit', 'Highway exit ahead', 5.0),
    2: ('workzone', 'Work zone ahead', 5.0),  # from the cones in lane 3 (block_index): = TOR_SECONDS
    3: ('fog', 'Low visibility', None),  # the fog starts at the fog point; the pre-alert follows its density
    4: ('accident', 'Accident ahead', 5.0),
}
CLOSED_LANES = {2: WORKZONE_LANES, 4: ACCIDENT_LANES}  # scenario -> lanes its obstacle closes (no traffic there)
INTERVENTION_CONFIG = os.path.join(EXPERIMENT_DIR, 'intervention_config.json')
DEVICES_FILE = os.path.join(EXPERIMENT_DIR, 'devices.json')  # Wi-Fi addresses: --wireless, --glasses phone, --ndrt laptop
INTERVENTION_DIR = os.path.join(EXPERIMENT_DIR, 'NDRT_scripts')
INTERVENTIONS = ('none', 'driving', 'NDRT')
INTERVENTION_FORMATS = ('summary', 'question')

AUTO = 'AUTO'
PRE_ALERT = 'PRE_ALERT'
TOR = 'TOR'
MANUAL = 'MANUAL'
AUTONOMOUS_MODES = (AUTO, PRE_ALERT, TOR)
ALERT_MODES = (PRE_ALERT, TOR)
TAKEOVER_MODES = (TOR,)  # driver input takes over only in these: locked until TAKE OVER NOW

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
STEER_TAKEOVER = 0.01  # wheel axis travel: 4.5-5.4 degrees on a 900-1080 degree wheel

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
    whose car is gone (the audio engine's collision sensor: its process is killed, not closed).

    In synchronous mode the client sees no actors until a step: one step first (a run that was
    killed leaves the server in synchronous mode, and its work zone would stay)."""
    if sim_world.get_settings().synchronous_mode:
        sim_world.tick()
    actors = sim_world.get_actors()
    stale = [a for a in actors.filter('vehicle.*')
             if a.attributes.get('role_name') in ('hero', 'npc', 'workzone', 'escort')]
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
        ('Driver seat', carla.Transform(carla.Location(x=eye_x, y=-0.36, z=eye_z),
                                        carla.Rotation(pitch=DRIVER_VIEW_PITCH)),
         None, False),
        ('Windshield (no steering wheel)',
         carla.Transform(carla.Location(x=eye_x + WINDSHIELD_FORWARD, y=-0.36, z=eye_z),
                         carla.Rotation(pitch=DRIVER_VIEW_PITCH)),
         None, False),
        ('Left mirror', carla.Transform(carla.Location(x=mirror_x, y=-mirror_y, z=mirror_z),
                                        carla.Rotation(pitch=-5.0, yaw=-165.0)), MIRROR_FOV, True),
        ('Right mirror', carla.Transform(carla.Location(x=mirror_x, y=mirror_y, z=mirror_z),
                                         carla.Rotation(pitch=-5.0, yaw=165.0)), MIRROR_FOV, True),
    ]


def car_mirrors(extent, view):
    """The car's mirrors in driver view `view` as (glass center, glass width and height in m, glass
    outline or None, camera transform, fov, view the glass is seen from).

    CARLA does not render reflections, so the mirrors of the car model stay empty. Each mirror gets
    a camera looking back, and its image is drawn over the glass where the glass appears in the
    driver views (see _mirror_rect), cut to the glass outline. Fitted to the Lincoln MKZ 2020.
    """
    eye_x, eye_z = -0.04 * extent.x, 1.6 * extent.z
    side_x, side_y, side_z = 0.25 * extent.x, extent.y + 0.1, 1.35 * extent.z

    def side_glass(fits, side):
        (share_x, outside, share_z), size, outline = fits[view]
        return carla.Location(x=share_x * extent.x, y=side * (extent.y + outside), z=share_z * extent.z), size, outline
    return [
        side_glass(LEFT_MIRROR, -1) + (
            carla.Transform(carla.Location(x=side_x, y=-side_y, z=side_z), carla.Rotation(pitch=-3.0, yaw=-170.0)),
            MIRROR_INSET_FOV, view),
        side_glass(RIGHT_MIRROR, 1) + (
            carla.Transform(carla.Location(x=side_x, y=side_y, z=side_z), carla.Rotation(pitch=-3.0, yaw=170.0)),
            MIRROR_INSET_FOV, view),
        (carla.Location(x=eye_x + REAR_MIRROR[0], y=REAR_MIRROR[1], z=eye_z + REAR_MIRROR[2]), REAR_MIRROR_SIZE,
         REAR_MIRROR_OUTLINE,
         carla.Transform(carla.Location(x=-extent.x - 0.2, z=eye_z + 0.1), carla.Rotation(pitch=-2.0, yaw=180.0)),
         REAR_MIRROR_FOV, 0),
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


def _side_inset_rect(manager, center, size):
    """--screens 1: window rectangle of a side mirror drawn as an inset at the lower left (left
    mirror) or right edge of the monitor, with the glass's proportions."""
    width, height = manager.screen_size
    inset_height = int(height * SIDE_INSET_HEIGHT)
    inset_width = int(inset_height * size[0] / size[1])
    x = SIDE_INSET_MARGIN if center.y < 0 else width - SIDE_INSET_MARGIN - inset_width
    return pygame.Rect(x, int(height * SIDE_INSET_Y - inset_height / 2), inset_width, inset_height)


def add_driver_view(world, args):
    """Add the experiment's camera positions in front of manual_control's; start in the view --view
    names. TAB (next_view) cycles through all of them and shows the name.

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
    extent = world.player.bounding_box.extent
    manager.mirrors = {} if args.no_mirrors else {view: car_mirrors(extent, view) for view in DRIVER_VIEWS}
    manager.latest_image = None  # newest RGB image, converted when it is drawn
    # cameras render at --render-scale of a monitor, the client scales them up
    manager.render_size = (int(manager.screen_width * args.render_scale), int(args.height * args.render_scale))
    manager.screen_size = (manager.screen_width, args.height)
    for sensor in manager.sensors:
        if sensor[0].startswith('sensor.camera'):
            sensor[-1].set_attribute('image_size_x', str(manager.render_size[0]))
            sensor[-1].set_attribute('image_size_y', str(manager.render_size[1]))
        if sensor[0] == 'sensor.camera.rgb' and args.scenario == 0:
            # practice drive in bright daylight: the automatic exposure keeps the view dim
            sensor[-1].set_attribute('exposure_mode', 'manual')
            sensor[-1].set_attribute('iso', str(PRACTICE_ISO))

    def render(display):
        _, mirrored = manager.view_options.get(manager.transform_index, (None, False))
        middle = manager.screens // 2
        image, manager.latest_image = manager.latest_image, None
        if image is not None:
            manager.surface, manager.surface_image = _camera_surface(manager, image), image
        if manager.surface is not None:
            surface = pygame.transform.flip(manager.surface, True, False) if mirrored else manager.surface
            display.blit(surface, (middle * manager.screen_width, 0))
        shown = {middle}
        for screen, _, view in manager.side_views:
            image, view['image'] = view['image'], None
            if image is not None:
                view['surface'], view['surface_image'] = _camera_surface(manager, image), image
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

    manager.transform_index = {'driver': 0, 'windshield': 1, 'chase': len(views)}[args.view]  # chase: behind the car
    _respawn_view(manager)


def _camera_surface(manager, image):
    """carla.Image (BGRA) -> surface the size of one monitor; manual_control's numpy path is too
    slow for 2560x1440 images. Unscaled, the surface is the image's own pixels, not a copy (the
    caller keeps the image while the surface is drawn): the display has the same pixel layout, so
    drawing it opaque is a plain copy, twice as fast as converting it first."""
    surface = pygame.image.frombuffer(image.raw_data, (image.width, image.height), 'BGRA')
    if surface.get_size() != manager.screen_size:
        surface = pygame.transform.scale(surface, manager.screen_size)
    surface.set_alpha(None)  # opaque: CARLA's alpha channel is not blended in
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
        library = manager._parent.get_world().get_blueprint_library()
        mirrors = manager.mirrors.get(manager.transform_index, [])
        for index, (center, size, outline, transform, fov, seen_from) in enumerate(mirrors):
            if manager.screens == 1 and index < 2:  # side mirror (car_mirrors: left, right, rear-view)
                rect = _side_inset_rect(manager, center, size)
            else:
                rect = _mirror_rect(manager, manager._camera_transforms[seen_from][0], center, size)
            if rect is None:
                continue
            blueprint = library.find('sensor.camera.rgb')
            blueprint.set_attribute('image_size_x', str(rect.width))
            blueprint.set_attribute('image_size_y', str(rect.height))
            blueprint.set_attribute('fov', str(fov))
            blueprint.set_attribute('sensor_tick', str(1.0 / MIRROR_FPS))
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


def soften_engine_braking(vehicle):
    """With the pedal released the MKZ's engine brakes like a brake pedal (80 km/h to a stop in
    10 s, it shifts down to first gear); ENGINE_DAMPING makes that an electric car's regenerative
    braking, and BRAKE_TORQUE_SCALE keeps its full braking."""
    physics = vehicle.get_physics_control()
    physics.damping_rate_zero_throttle_clutch_engaged = ENGINE_DAMPING
    wheels = physics.wheels
    for wheel in wheels:
        wheel.max_brake_torque *= BRAKE_TORQUE_SCALE
    physics.wheels = wheels
    vehicle.apply_physics_control(physics)


def hold_loop_lights_green(sim_world, routes):
    """Green for the loop at the junction where it crosses a road with traffic lights (Town04,
    ~944 m from the start), red for the crossing road, held there: the autonomous mode and the
    traffic cars ignore traffic lights and would drive through red. Returns the lights for
    release_lights()."""
    loop = {}
    for route in routes.values():
        for waypoint in route:
            for light in sim_world.get_traffic_lights_from_waypoint(waypoint, 3.0):
                loop[light.id] = light
    held = []
    for light in loop.values():
        for member in light.get_group_traffic_lights():
            member.set_state(carla.TrafficLightState.Green if member.id in loop else carla.TrafficLightState.Red)
            member.freeze(True)
            held.append(member)
    if loop:
        logging.info('Traffic lights %s on the loop held green', sorted(loop))
    return held


def release_lights(lights):
    """Back to the normal light cycle after hold_loop_lights_green."""
    for light in lights:
        light.freeze(False)
    if lights:
        lights[0].reset_group()


class LoopFollower(object):
    """Drives a vehicle around a closed route forever with a BasicAgent.

    The agent steers (and stops for hazards); the speed is this class's own: the cruise speed, or
    less before and in curves (CURVE_LATERAL_ACCEL), reached gently (AUTO_ACCEL, CURVE_DECEL) with
    the throttle that holds a speed plus a PI correction, changing slowly (AUTO_THROTTLE_RATE),
    so the engine sound stays even. The agent's own speed PID
    gives full throttle 1 km/h below its target and none above it: on and off in every curve.
    """

    def __init__(self, vehicle, route, target_speed, carla_map, route_planner, quiet=False):
        self._vehicle = vehicle
        self._route = route
        self._cruise = target_speed
        self._agent = BasicAgent(_FixedBoundingBox(vehicle), target_speed=target_speed, opt_dict={},
                                 map_inst=carla_map, grp_inst=route_planner)
        self._agent.ignore_traffic_lights(True)
        self._agent.ignore_stop_signs(True)
        self._limits = curve_speed_limits(route)
        self._target = 0.0      # km/h, ramped towards the speed wanted here
        self._integral = 0.0
        self._throttle = 0.0
        self._index = 0
        self._last = None
        self._plan = []
        if not quiet:
            logging.info('Autonomous speed: %.0f km/h, down to %.0f km/h in the tightest curve', target_speed,
                         min(target_speed, min(self._limits)))
        self.engage()

    def engage(self):
        """(Re)start following the route from the point closest to the vehicle."""
        location = self._vehicle.get_location()
        nearest = min(range(len(self._route)),
                      key=lambda i: self._route[i].transform.location.distance(location))
        rotated = self._route[nearest:] + self._route[:nearest]
        self._plan = [(wp, RoadOption.LANEFOLLOW) for wp in rotated]
        self._agent.set_global_plan(self._plan, stop_waypoint_creation=True, clean_queue=True)
        self._index = nearest
        self._target = self._vehicle.get_velocity().length() * 3.6
        self._integral = 0.0
        self._throttle = self._vehicle.get_control().throttle
        self._last = None

    def _wanted_speed(self):
        """km/h: the cruise speed, or the curve limit at the route point nearest the car."""
        location = self._vehicle.get_location()
        count = len(self._route)
        candidates = [(self._index + offset) % count for offset in range(-20, 41)]
        self._index = min(candidates, key=lambda i: self._route[i].transform.location.distance(location))
        return min(self._cruise, self._limits[self._index])

    def run_step(self):
        planner = self._agent.get_local_planner()
        if len(planner._waypoints_queue) < REFILL_BELOW:  # pylint: disable=protected-access
            self._agent.set_global_plan(self._plan, stop_waypoint_creation=True, clean_queue=False)
        control = self._agent.run_step()
        now = time.monotonic()
        dt = 0.0 if self._last is None else min(now - self._last, 0.2)
        self._last = now
        if control.brake >= self._agent._max_brake:  # pylint: disable=protected-access
            # hazard ahead: the agent's emergency stop
            self._target = self._vehicle.get_velocity().length() * 3.6
            self._integral = self._throttle = 0.0
            return control
        wanted = self._wanted_speed()
        step = (AUTO_ACCEL if wanted > self._target else CURVE_DECEL) * 3.6 * dt
        self._target += max(-step, min(wanted - self._target, step))
        speed_kmh = self._vehicle.get_velocity().length() * 3.6
        error = self._target - speed_kmh
        if abs(error) < AUTO_I_RANGE:
            self._integral = min(0.2, max(-0.2, self._integral + AUTO_GAIN_I * error * dt))
        # the throttle that holds the target speed, plus a correction, changing slowly
        wanted_throttle = min(1.0, max(0.0, _interpolate(HOLD_THROTTLE, self._target) + AUTO_GAIN_P * error
                                       + self._integral))
        step = AUTO_THROTTLE_RATE * dt
        self._throttle += max(-step, min(wanted_throttle - self._throttle, step))
        control.throttle = self._throttle
        # brakes only when far too fast (downhill): coasting does the rest
        control.brake = min(0.3, 0.03 * (-error - AUTO_BRAKE_OVER)) if -error > AUTO_BRAKE_OVER else 0.0
        return control


class TestDriver(object):
    """--test-driver, for checking the scenarios without a participant: takes over TEST_DRIVER_REACTION
    s after the TOR and drives on with the autopilot's controller in the lane a driver would pick:
    scenarios 2 and 4 lane 2 past the closure, lane 3 from LANE_CHANGE_BEFORE m before the lane 2
    obstacle; else the lane it was in."""

    REACTION = 1.0              # s after the TOR
    LANE_CHANGE_BEFORE = 90.0   # m before the lane 2 obstacle it moves over to lane 3

    def __init__(self, vehicle, routes, speed, carla_map, route_planner, scenario):
        self._followers = {lane: LoopFollower(vehicle, route, speed, carla_map, route_planner, quiet=True)
                           for lane, route in routes.items()}
        self._scenario = scenario
        self._lane = None

    def _wanted_lane(self):
        scenario = self._scenario
        if not scenario.has_scene or scenario.ego_index is None or scenario.scene_cleared:
            return self._lane
        count = scenario._count  # pylint: disable=protected-access
        to_obstacle = ((scenario._obstacle_index - scenario.ego_index) % count) * ROUTE_RESOLUTION  # pylint: disable=protected-access
        if to_obstacle < self.LANE_CHANGE_BEFORE or to_obstacle > count * ROUTE_RESOLUTION - 300.0:
            return 3  # just before the van, or past it
        return 2

    def run_step(self):
        lane = self._wanted_lane() or 3
        if lane != self._lane:
            logging.info('Test driver: lane %d', lane)
            self._lane = lane
            self._followers[lane].engage()
        return self._followers[lane].run_step()


def log_collisions(sim_world, vehicle):
    """A collision sensor that logs what the car hits, once per object per COLLISION_LOG_GAP s (the
    world's own sensor reports every frame of contact). Returns the sensor and the list of hits."""
    hits = []
    last = {}

    def on_collision(event):
        other = event.other_actor
        now = time.monotonic()
        if now - last.get(other.id, -1e9) < COLLISION_LOG_GAP:
            return
        last[other.id] = now
        impulse = event.normal_impulse
        hits.append(other.type_id)
        logging.warning('Collision with %s (role %s), impulse %.0f N s', other.type_id,
                        other.attributes.get('role_name', '-'), math.sqrt(impulse.x ** 2 + impulse.y ** 2 + impulse.z ** 2))
    sensor = sim_world.spawn_actor(sim_world.get_blueprint_library().find('sensor.other.collision'),
                                   carla.Transform(), attach_to=vehicle)
    sensor.listen(on_collision)
    return sensor, hits


def curve_speed_limits(route):
    """km/h the car can drive at each point of the closed `route` with CURVE_LATERAL_ACCEL sideways,
    lowered before curves so it slows down at CURVE_DECEL at most."""
    count = len(route)
    half = 5  # route points on either side: the curvature over 20 m
    limits = []
    for i in range(count):
        a = route[(i - half) % count].transform.rotation.yaw
        b = route[(i + half) % count].transform.rotation.yaw
        turn = abs((b - a + 180.0) % 360.0 - 180.0)
        curvature = math.radians(turn) / (2 * half * ROUTE_RESOLUTION)
        limits.append(math.sqrt(CURVE_LATERAL_ACCEL / curvature) * 3.6 if curvature > 1e-4 else 1000.0)
    # backwards around the loop twice, so the slowing down before a curve also reaches past route[0]
    for k in range(2 * count, 0, -1):
        i, after = (k - 1) % count, k % count
        reachable = math.sqrt((limits[after] / 3.6) ** 2 + 2.0 * CURVE_DECEL * ROUTE_RESOLUTION) * 3.6
        limits[i] = min(limits[i], reachable)
    return limits


def _route_placer(sim_world, route, start_index, actors):
    """put(name, distance, offset, ...): spawn `name` at route `distance` m from start_index,
    `offset` m right of lane 3's center (`route` is lane 3), and add it to `actors`."""
    library = sim_world.get_blueprint_library()

    def put(name, distance, offset, yaw_add=0.0, lift=0.05, hold=False, lights=None):
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
        if lights is not None:
            actor.set_light_state(carla.VehicleLightState(lights))
        actors.append(actor)
        return actor
    return put


def spawn_accident(sim_world, route, start_index):
    """Scenario 4: a crash closes lanes 3 and 4 around `start_index` (the crashed cars). `route` is
    the lane 3 route of the loop.

    Layout, along the route: an accident warning sign on the shoulder, a police car with its
    emergency lights in lane 4, a taper of cones from the outer edge of lane 4 to the edge of
    lane 2, the two crashed cars (one askew in lane 3, one spun round across lanes 3 and 4, hazard
    lights on) with debris, an ambulance with its emergency lights in lane 4 behind them, and cones
    along lane 3's left edge past the scene.
    """
    actors = []
    put = _route_placer(sim_world, route, start_index, actors)
    inner = -0.5 * LANE_WIDTH + 0.55        # just inside lane 3, next to the lane 2 edge
    outer = 1.5 * LANE_WIDTH                # outer edge of lane 4 (offset from lane 3's center)
    emergency = int(carla.VehicleLightState.Special1 | carla.VehicleLightState.Special2 |
                    carla.VehicleLightState.Position | carla.VehicleLightState.LowBeam)
    hazards = int(carla.VehicleLightState.LeftBlinker | carla.VehicleLightState.RightBlinker |
                  carla.VehicleLightState.Position)

    put('static.prop.warningaccident', ACCIDENT_START, outer + 1.2, yaw_add=180.0)
    put('vehicle.dodge.charger_police_2020', -60.0, LANE_WIDTH, lift=0.3, hold=True, lights=emergency)
    # taper: from the outer edge of lane 4 (behind the police car) to the edge of lane 2
    taper_start, taper_end = ACCIDENT_TAPER_FROM, ACCIDENT_TAPER_TO
    count = 6
    for k in range(count + 1):
        put('static.prop.trafficcone01', taper_start + (taper_end - taper_start) * k / count,
            outer + (inner - outer) * k / count)
    # the crash
    put('vehicle.tesla.model3', 0.0, 0.4, yaw_add=32.0, lift=0.3, hold=True, lights=hazards)
    put('vehicle.toyota.prius', 7.0, 2.3, yaw_add=-145.0, lift=0.3, hold=True, lights=hazards)
    for distance, offset, name in ((-3.0, 1.4, 'static.prop.dirtdebris01'), (3.0, -0.6, 'static.prop.dirtdebris02'),
                                   (5.0, 1.8, 'static.prop.dirtdebris03'), (11.0, 0.8, 'static.prop.dirtdebris01')):
        put(name, distance, offset, lift=0.0)
    put('vehicle.ford.ambulance', 28.0, LANE_WIDTH, lift=0.3, hold=True, lights=emergency)
    # cones along lane 3's left edge from the crash to the end of the scene
    distance = 0.0
    while distance <= ACCIDENT_END:
        put('static.prop.trafficcone01', distance, inner)
        distance += CONE_SPACING

    logging.info('Accident: %d objects close lanes 3 and 4 around %.0f m', len(actors),
                 start_index * ROUTE_RESOLUTION)
    return actors


def spawn_workzone(sim_world, route, start_index):
    """Close lanes 3 and 4 from `start_index` on. `route` is the lane 3 route of the loop.

    Layout, along the route: two warning signs, a taper of cones that leads from the outer
    edge of lane 4 to the edge of lane 2, a row of barriers across both lanes, cones along
    the closed lanes with a work truck in lane 3 and a work van in lane 4, and a short
    taper that opens the lanes again.
    """
    actors = []
    put = _route_placer(sim_world, route, start_index, actors)

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

    def set_speed(self, kmh):
        self._tm.set_desired_speed(self._vehicle, kmh)

    def refresh_path(self):
        """Hand the next laps of the route, starting from where the car is now."""
        location = self._vehicle.get_location()
        nearest = min(range(len(self._route)),
                      key=lambda i: self._route[i].transform.location.distance(location))
        lap = self._route[nearest:] + self._route[:nearest]
        path = [wp.transform.location for wp in (lap * NPC_PATH_LAPS)[::NPC_PATH_STEP]]
        self._tm.set_path(self._vehicle, path)


class TrafficClearance(object):
    """After the pre-alert the traffic leaves, so the takeover happens on an empty road.

    Cars ahead of the ego car speed up to TRAFFIC_CLEAR_SPEED km/h above its speed, cars behind
    it slow down to as much below (gradually, over TRAFFIC_CLEAR_RAMP s): both move out of view
    without passing it. Each car is removed once it is TRAFFIC_CLEAR_DISTANCE m away, the rest
    TRAFFIC_CLEAR_BEFORE_TOR s before the TOR. The traffic stays gone for the rest of the run.
    """

    def __init__(self, client, traffic, npc_speed):
        self._client = client
        self._traffic = traffic      # shared with the recorder and the path refresh: changed in place
        self._npc_speed = npc_speed
        self._start = None
        self._deadline = None
        self._targets = {}           # actor id -> target speed, km/h
        self._ramped = False

    def start(self, now, ego, deadline):
        if self._start is not None or not self._traffic:
            return
        self._start = now
        self._deadline = deadline
        location = ego.get_location()
        forward = ego.get_transform().get_forward_vector()
        ego_kmh = ego.get_velocity().length() * 3.6
        ahead = 0
        for npc in self._traffic:
            offset = npc.actor.get_location() - location
            if offset.x * forward.x + offset.y * forward.y >= 0.0:
                self._targets[npc.actor.id] = ego_kmh + TRAFFIC_CLEAR_SPEED
                ahead += 1
            else:
                self._targets[npc.actor.id] = max(ego_kmh - TRAFFIC_CLEAR_SPEED, 20.0)
        logging.info('Traffic leaves: %d cars ahead speed up, %d behind slow down', ahead, len(self._traffic) - ahead)

    def tick(self, now, ego):
        if self._start is None or not self._traffic:
            return
        share = min((now - self._start) / TRAFFIC_CLEAR_RAMP, 1.0)
        location = ego.get_location()
        gone = []
        for npc in self._traffic:
            target = self._targets.get(npc.actor.id)
            if target is None:
                continue
            if now >= self._deadline or npc.actor.get_location().distance(location) > TRAFFIC_CLEAR_DISTANCE:
                gone.append(npc)
            elif not self._ramped:
                npc.set_speed(self._npc_speed + share * (target - self._npc_speed))
        self._ramped = share >= 1.0
        if gone:
            for npc in gone:
                self._traffic.remove(npc)
            destroy_actors(self._client, [npc.actor for npc in gone])
            logging.info('Traffic: %d car(s) removed, %d left', len(gone), len(self._traffic))


class EscortCars(object):
    """Cars next to the ego car after the takeover, so the takeover period measures how the
    driver handles traffic, not free driving. Two plans:

    beside (start): they come up from ESCORT_BEHIND m behind over ESCORT_APPROACH s, stay
    ESCORT_SECONDS beside the ego car (ESCORT_OFFSET ahead of it), drop back again and are removed.

    merge (start_merge; lanes 3 and 4 closed ahead): right after the takeover a car comes up in
    lane 1 and one in lane 3, MERGE_AHEAD m ahead of the ego car, and they keep to those lanes
    whatever lane the driver takes (in the driver's lane they stay MERGE_YIELD m behind it). The
    lane 3 car slows down
    gradually (MERGE_SLOW, and in time to stop before the closure) and is removed once it is
    ESCORT_GONE m behind, out of view. The lane 1 car stays level with the ego car (it blocks
    lane 1 at the lane 2 obstacle, so the driver has to move over to lane 3) until the ego car is
    MERGE_CLEAR_AFTER m past the obstacle (without one: past the closure); it then drives off ahead
    and is removed.

    They move with physics: a speed close to the ego car's, corrected by ESCORT_GAP_GAIN for the gap
    to their place and changing gradually, along their lane. So they follow the driver smoothly,
    a little late, instead of jumping each frame.
    """

    CENTERING = 0.8         # m/s sideways per m off the middle of the lane
    TURNING = 3.0           # deg/s turn rate per deg the car points away from the lane ahead

    def __init__(self, client, sim_world, carla_map):
        self._client = client
        self._world = sim_world
        self._map = carla_map
        self._blueprints = [bp for bp in sim_world.get_blueprint_library().filter('vehicle.*')
                            if bp.has_attribute('base_type') and bp.get_attribute('base_type').as_str() == 'car'
                            and bp.id not in NPC_EXCLUDED
                            and not any(word in bp.id for word in ('police', 'ambulance', 'firetruck'))]
        self._cars = {}       # name ('left', 'right', 'lane1', 'lane3') -> actor
        self._speed = {}      # name -> m/s it drives at
        self._plan = None     # 'beside', 'merge'; None while there are none
        self._sides = ()      # beside: 'left' and/or 'right'
        self._closure = None  # merge: (start, end) carla.Location in lane 3 of the closed stretch
        self._start = None    # time they set off; None while they have not (merge: waiting for lane 2)
        self._done = set()    # merge: cars that have been removed
        self._slow = None     # merge: time the lane 3 car starts falling back (once it is beside)
        self._passed = None   # merge: passed() -> True once the ego car is past the lane 2 obstacle
        self._leave = None    # merge: time the lane 1 car starts driving off
        self._ego_location = self._ego_forward = None

    def start(self, now, sides):
        if self._plan is not None or not sides:
            return
        self._plan, self._start, self._sides = 'beside', now, tuple(sides)
        logging.info('Escort cars come up beside the car (%s) for %.0f s', ' and '.join(self._sides), ESCORT_SECONDS)

    def start_merge(self, now, closure, passed=None):
        """The merge plan. passed(): True once the ego car is MERGE_CLEAR_AFTER m past the lane 2
        obstacle, along the road (None: no obstacle, past the closure instead)."""
        if self._plan is not None:
            return
        self._plan, self._closure, self._passed, self._start = 'merge', closure, passed, now
        self._done, self._slow, self._leave = set(), None, None
        logging.info('Escort cars come up in lanes 1 and 3')

    @staticmethod
    def _approach(elapsed, target, behind=ESCORT_BEHIND):
        """m ahead of the ego car, coming up from `behind` to `target` over ESCORT_APPROACH s."""
        share = min(max(elapsed / ESCORT_APPROACH, 0.0), 1.0)
        share = share * share * (3.0 - 2.0 * share)  # smooth start and stop
        return behind + (target - behind) * share

    def _beside_offset(self, now, side):
        elapsed = now - self._start
        leave = ESCORT_APPROACH + ESCORT_SECONDS
        if elapsed < leave:
            return self._approach(elapsed, ESCORT_OFFSET[side])
        return self._approach(ESCORT_APPROACH - (elapsed - leave), ESCORT_OFFSET[side])

    def _gap(self, location):
        """m ahead of the ego car (< 0: behind)."""
        return ((location.x - self._ego_location.x) * self._ego_forward.x
                + (location.y - self._ego_location.y) * self._ego_forward.y)

    def tick(self, now, ego):
        if self._plan is None:
            return
        self._ego_location = ego.get_location()
        self._ego_forward = ego.get_transform().get_forward_vector()
        ego_waypoint = self._map.get_waypoint(self._ego_location)
        if self._plan == 'merge':
            self._merge_tick(now, ego, ego_waypoint)
            return
        if now - self._start >= ESCORT_SECONDS + 2 * ESCORT_APPROACH:
            self.remove()
            return
        for side in self._sides:
            lane = ego_waypoint.get_left_lane() if side == 'left' else ego_waypoint.get_right_lane()
            if (lane is None or lane.lane_type != carla.LaneType.Driving
                    or lane.lane_id * ego_waypoint.lane_id <= 0):
                lane = None
            self._place(side, self._lane_path(side, lane), self._beside_offset(now, side), ego)

    def _merge_tick(self, now, ego, ego_waypoint):
        closure_start, closure_end = self._closure
        elapsed = now - self._start
        try:
            lanes = {n: lane_waypoint(ego_waypoint, n) for n in (1, 2, 3)}
        except RuntimeError:
            return  # not on the 3-lane highway here (a junction): next frame
        # lane 3: up beside the ego car, then gradually slower, stopping before the closure at the latest;
        # none if the takeover came too close to the closure for it to come up
        if 'lane3' not in self._done and 'lane3' not in self._cars and self._gap(closure_start) < MERGE_LANE3_ROOM:
            self._done.add('lane3')
            logging.info('No escort car in lane 3: the closure is %.0f m ahead', self._gap(closure_start))
        if 'lane3' not in self._done:
            offset = self._approach(elapsed, MERGE_AHEAD, MERGE_BEHIND)
            car = self._cars.get('lane3')
            limit = None
            if car is not None:
                gap = self._gap(car.get_location())
                if self._slow is None and (gap > MERGE_AHEAD - 1.0 or elapsed > 2 * ESCORT_APPROACH):
                    self._slow = now
                if self._slow is not None:
                    offset = MERGE_AHEAD - 0.5 * MERGE_SLOW * (now - self._slow) ** 2
                limit = math.sqrt(2.0 * MERGE_BRAKE * max(self._gap(closure_start) - gap - MERGE_STOP_BEFORE, 0.0))
                if gap < -ESCORT_GONE:
                    self._drop('lane3')
            offset, cap = self._give_way('lane3', lanes[3], offset, ego)
            if cap is not None:
                limit = cap if limit is None else min(limit, cap)
            if 'lane3' not in self._done:
                self._place('lane3', self._lane_path('lane3', lanes[3]), offset, ego, max_speed=limit)
        # lane 1: up beside the ego car, level with it past the lane 2 obstacle, then drives off
        if 'lane1' not in self._done:
            car = self._cars.get('lane1')
            offset = self._approach(elapsed, MERGE_AHEAD, MERGE_BEHIND)
            passed = self._passed() if self._passed is not None else self._gap(closure_end) < -MERGE_CLEAR_AFTER
            if self._leave is None and car is not None and passed:
                self._leave = now
                logging.info('Escort car in lane 1 drives off')
            if self._leave is not None:
                offset += 0.5 * MERGE_SLOW * (now - self._leave) ** 2
                if car is not None and self._gap(car.get_location()) > ESCORT_GONE:
                    self._drop('lane1')
            offset, cap = self._give_way('lane1', lanes[1], offset, ego)
            if 'lane1' not in self._done:
                self._place('lane1', self._lane_path('lane1', lanes[1]), offset, ego, max_speed=cap)
        if self._done >= {'lane1', 'lane3'}:
            self.remove()

    def _give_way(self, name, lane, offset, ego):
        """(offset, speed cap or None) for the escort car `name` driving `lane` (a waypoint level with
        the ego car) while the ego car is in that lane or partly in it (changing lanes): a car well
        ahead stays ahead, any other falls back MERGE_YIELD m behind, slower than the ego car, so it
        never runs into it."""
        right = lane.transform.get_right_vector()
        middle = lane.transform.location
        lateral = ((self._ego_location.x - middle.x) * right.x + (self._ego_location.y - middle.y) * right.y)
        if abs(lateral) >= MERGE_SIDE_CLEAR:
            return offset, None
        car = self._cars.get(name)
        if car is None:
            return min(offset, MERGE_YIELD), None
        gap = self._gap(car.get_location())
        if gap > MERGE_AHEAD_CLEAR:
            return max(offset, gap), None
        return min(offset, MERGE_YIELD), max(ego.get_velocity().length() - 2.0, 0.0)

    # -- paths: where a car should be at `gap` m ahead of the ego car --------------------------

    @staticmethod
    def _at(waypoint, gap):
        points = waypoint.next(gap) if gap > 0.1 else waypoint.previous(max(-gap, 0.1))
        return points[0].transform if points else None

    def _lane_path(self, name, lane):
        """In `lane` (a waypoint level with the ego car), else (None) in the car's own lane."""
        if lane is not None:
            return lambda gap: self._at(lane, gap)
        car = self._cars.get(name)
        if car is None:
            return lambda gap: None
        own = self._map.get_waypoint(car.get_location())
        here = self._gap(car.get_location())
        return lambda gap: self._at(own, gap - here)

    # -- one car -----------------------------------------------------------------------------

    def _place(self, name, path, offset, ego, max_speed=None, sideways=1.5):
        """Spawns the car `name` at `offset` m ahead of the ego car on `path`, or drives it there;
        `sideways`: m/s at most towards the path."""
        car = self._cars.get(name)
        if car is None:
            transform = path(offset)
            if transform is None:
                return
            transform = carla.Transform(transform.location + carla.Location(z=0.3), transform.rotation)
            blueprint = random.choice(self._blueprints)
            blueprint.set_attribute('role_name', 'escort')
            if blueprint.has_attribute('color'):
                blueprint.set_attribute('color', random.choice(blueprint.get_attribute('color').recommended_values))
            car = self._world.try_spawn_actor(blueprint, transform)
            if car is None:
                return  # the place is taken: next frame
            car.set_target_velocity(ego.get_velocity())
            self._cars[name] = car
            self._speed[name] = ego.get_velocity().length()
            return
        transform = car.get_transform()
        location = transform.location
        gap = self._gap(location)
        catch_up = min(max(ESCORT_GAP_GAIN * (offset - gap), -ESCORT_CATCH_UP), ESCORT_CATCH_UP)
        # the speed changes gradually towards the ego car's plus the catch-up
        goal = ego.get_velocity().length() + catch_up
        if max_speed is not None:
            goal = min(goal, max_speed)
        wanted = self._speed[name]
        wanted = max(wanted + min(max(goal - wanted, -ESCORT_SPEED_STEP), ESCORT_SPEED_STEP), 0.0)
        self._speed[name] = wanted
        here = path(gap)
        if here is None:
            return
        # velocity and turn rate are set directly (tyres and gear shifts would let it wander):
        # along the path, drawn back to it, turning towards a point ahead on it
        lane_forward = here.get_forward_vector()
        lane_right = here.get_right_vector()
        middle = here.location
        drift = (middle.x - location.x) * lane_right.x + (middle.y - location.y) * lane_right.y
        side_speed = min(max(self.CENTERING * drift * sideways / 1.5, -sideways), sideways)
        ahead = path(gap + max(8.0, wanted * 0.8))
        target = ahead.location if ahead is not None else middle + lane_forward * 10.0
        heading = math.degrees(math.atan2(target.y - location.y, target.x - location.x))
        turn = (heading - transform.rotation.yaw + 180.0) % 360.0 - 180.0
        car.set_target_velocity(carla.Vector3D(lane_forward.x * wanted + lane_right.x * side_speed,
                                               lane_forward.y * wanted + lane_right.y * side_speed,
                                               car.get_velocity().z))
        car.set_target_angular_velocity(carla.Vector3D(0.0, 0.0, self.TURNING * turn))

    def _drop(self, name):
        """The car `name` is out of view: removed."""
        self._done.add(name)
        car = self._cars.pop(name, None)
        if car is not None:
            destroy_actors(self._client, [car])
            logging.info('Escort car in %s removed (out of view)', name.replace('lane', 'lane '))

    def remove(self):
        """Gone at once (the end, autonomous driving re-engaged, the program quits)."""
        if self._cars:
            destroy_actors(self._client, list(self._cars.values()))
            logging.info('Escort cars removed')
        self._cars = {}
        self._plan = self._start = None


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


def advance(sim_world, args):
    """Next simulation step: the client makes it in synchronous mode (--fps), else waits for it."""
    if args.sync:
        sim_world.tick()
    else:
        sim_world.wait_for_tick()


class LatencyMeter(object):
    """Control-to-display latency, synchronous mode only: from the moment a frame's controls (read
    from the wheel or keyboard) go to the server, to the moment the first camera image of the step
    they drive is on the screen (after the display flip). The monitor's own delay comes on top."""

    def __init__(self):
        self._pending = []  # [(simulation frame the controls drive, time sent)]
        self.latest = None  # ms, last measured

    def sent(self, frame, now):
        self._pending.append((frame, now))

    def shown(self, image, now):
        """`image`: the carla.Image just shown (None: no image yet)."""
        if image is None:
            return
        while self._pending and self._pending[0][0] <= image.frame:
            _, sent = self._pending.pop(0)
            self.latest = (now - sent) * 1000.0


def _free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class SimTicker(object):
    """Makes the synchronous simulation's steps in a thread, so the server computes the next step
    while the client draws this one (tick() releases the GIL)."""

    def __init__(self, sim_world):
        self._world = sim_world
        self._thread = None
        self._error = None
        self.frame = sim_world.get_snapshot().frame  # frame number of the last finished step

    def start(self):
        def run():
            try:
                self.frame = self._world.tick()
            except RuntimeError as error:  # e.g. the server stopped answering
                self._error = error
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def wait(self):
        """Wait for the step started last; raises its error."""
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        error, self._error = self._error, None
        if error is not None:
            raise error


def spawn_traffic(sim_world, routes, args, traffic_manager, lanes, start=0):
    """Place args.vehicles cars on the highway, each driving the loop in one of the given lanes.
    `start`: the ego car's index on its route."""
    if args.vehicles <= 0:
        return []
    ego_location = routes[args.lane][start].transform.location
    share = float(start) / len(routes[args.lane])  # where the start is along the loop, for every lane
    step = int(NPC_SLOT_SPACING / ROUTE_RESOLUTION)
    slots = [(lane, i) for lane in routes if lane in lanes for i in range(0, len(routes[lane]), step)
             if routes[lane][i].transform.location.distance(ego_location) > NPC_CLEARANCE]
    count = min(args.vehicles, len(slots))
    if count < args.vehicles:
        logging.warning('Only %d traffic positions are available, placing %d vehicles', len(slots), count)
    # Positions within NPC_NEAR_RANGE of the start (ahead or behind) are used first.
    def from_start(lane, i):
        count = len(routes[lane])
        offset = (i - int(share * count)) % count
        return min(offset, count - offset) * ROUTE_RESOLUTION
    near = [slot for slot in slots if from_start(*slot) <= NPC_NEAR_RANGE]
    far = [slot for slot in slots if slot not in near]
    chosen = random.sample(near, min(count, len(near)))
    chosen += random.sample(far, count - len(chosen))
    # Passenger cars only: they handle the highway curves at traffic speed.
    blueprints = [bp for bp in sim_world.get_blueprint_library().filter('vehicle.*')
                  if bp.has_attribute('base_type') and bp.get_attribute('base_type').as_str() == 'car'
                  and bp.id not in NPC_EXCLUDED]
    spawned = []
    for lane, index in chosen:
        blueprint = random.choice(blueprints)
        blueprint.set_attribute('role_name', 'npc')
        if blueprint.has_attribute('color'):
            blueprint.set_attribute('color', random.choice(blueprint.get_attribute('color').recommended_values))
        transform = routes[lane][index].transform
        transform.location.z += 0.5
        vehicle = sim_world.try_spawn_actor(blueprint, transform)
        if vehicle is not None:
            spawned.append((vehicle, lane))
    # Each car's path starts where the car is: before a tick the client does not know new cars'
    # positions yet, and a path from the wrong place sends cars into the guardrail.
    advance(sim_world, args)
    traffic = [TrafficVehicle(vehicle, routes[lane], traffic_manager, args.npc_speed) for vehicle, lane in spawned]
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

    def mark_input(self, keys):
        """At the TOR: keys held now do not take over, only keys pressed from now on."""
        self._held = {k for k in DRIVE_KEYS if keys[k]}

    def is_takeover_event(self, event):
        return event.type == pygame.KEYDOWN and event.key in DRIVE_KEYS

    def is_reverse_event(self, event):
        return False

    def light_event(self, event):
        """Light switch the event asks for (see keyboard_light_event), else None."""
        return keyboard_light_event(event)

    def driver_active(self, keys):
        return any(keys[k] for k in DRIVE_KEYS if k not in getattr(self, '_held', ()))

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

    def update(self, control, keys, milliseconds, speed_kmh, incline):
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


class _HapticConstant(ctypes.Structure):
    """SDL_HapticConstant."""
    _fields_ = [('type', ctypes.c_uint16), ('direction', _HapticDirection), ('length', ctypes.c_uint32),
                ('delay', ctypes.c_uint16), ('button', ctypes.c_uint16), ('interval', ctypes.c_uint16),
                ('level', ctypes.c_int16), ('attack_length', ctypes.c_uint16), ('attack_level', ctypes.c_uint16),
                ('fade_length', ctypes.c_uint16), ('fade_level', ctypes.c_uint16)]


class _HapticEffect(ctypes.Union):
    """SDL_HapticEffect; the padding covers the union's larger members."""
    _fields_ = [('type', ctypes.c_uint16), ('constant', _HapticConstant), ('condition', _HapticCondition),
                ('padding', ctypes.c_uint8 * 128)]


class WheelForceFeedback(object):
    """Resistance in the steering wheel: a centering spring that gets stiffer with speed, like the
    self-aligning torque of a real car, plus damping and friction so the wheel does not turn as
    lightly as a bare game wheel (WHEEL_DAMPING, WHEEL_FRICTION), and a constant force towards the
    center that is felt from the first degrees on (WHEEL_CENTER_FORCE).

    pygame has no force feedback, so this calls the haptic functions of the SDL2 library pygame
    ships with (the same library instance, so the joystick and haptic parts share their state).
    """

    INIT_HAPTIC = 0x1000
    CONSTANT, SPRING, DAMPER, FRICTION, GAIN = 1 << 0, 1 << 7, 1 << 8, 1 << 10, 1 << 12
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
        self._center_id = -1
        self._center_level = 0
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
        self._damper_id = self._friction_id = -1
        if self._spring_id >= 0 and supported & self.DAMPER:
            self._damper = self._effect(self.DAMPER, int(0x7FFF * WHEEL_DAMPING * self._strength))
            self._damper_id = sdl.SDL_HapticNewEffect(haptic, ctypes.byref(self._damper))
        if self._spring_id >= 0 and supported & self.FRICTION:
            self._friction = self._effect(self.FRICTION, int(0x7FFF * WHEEL_FRICTION * self._strength))
            self._friction_id = sdl.SDL_HapticNewEffect(haptic, ctypes.byref(self._friction))
        if self._spring_id >= 0 and supported & self.CONSTANT:
            self._center = _HapticEffect()
            self._center.constant.type = self.CONSTANT
            self._center.constant.direction.type = self._direction
            self._center.constant.direction.dir[0] = 1
            self._center.constant.length = self.INFINITY
            self._center_id = sdl.SDL_HapticNewEffect(haptic, ctypes.byref(self._center))
        if self._spring_id < 0:
            logging.warning('No force feedback: %s', sdl.SDL_GetError().decode(errors='replace'))
            self.close()
            return
        for effect_id in (self._spring_id, self._damper_id, self._friction_id, self._center_id):
            if effect_id >= 0:
                sdl.SDL_HapticRunEffect(haptic, effect_id, self.INFINITY)
        logging.info('Force feedback on %s, strength %.0f%% (--wheel-force): spring, %s, %s, %s', name,
                     self._strength * 100, 'damper' if self._damper_id >= 0 else 'no damper',
                     'friction' if self._friction_id >= 0 else 'no friction',
                     'centering force' if self._center_id >= 0 else 'no centering force')

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

    def update(self, speed_kmh, steer):
        """Spring stiffness for the current speed: WHEEL_SPRING_STANDSTILL of the full force when
        standing, rising to the full force at WHEEL_SPRING_FULL_SPEED km/h. The centering force
        follows `steer` (the wheel's axis, -1..1) every frame, so it does not lag behind the wheel."""
        if self._sdl is None:
            return
        now = time.monotonic()
        share = min(speed_kmh / WHEEL_SPRING_FULL_SPEED, 1.0)
        stiffness = WHEEL_SPRING_STANDSTILL + (1.0 - WHEEL_SPRING_STANDSTILL) * share
        ramp = min((now - self._start) / self.RAMP_SECONDS, 1.0)
        if self._center_id >= 0:
            push = max(-1.0, min(steer / WHEEL_CENTER_RAMP, 1.0))
            level = int(0x7FFF * self._strength * WHEEL_CENTER_FORCE * stiffness * ramp * push) * WHEEL_CENTER_SIGN
            if abs(level - self._center_level) >= 150 or (level == 0) != (self._center_level == 0):
                self._center_level = level
                self._center.constant.level = level
                self._sdl.SDL_HapticUpdateEffect(self._haptic, self._center_id, ctypes.byref(self._center))
        if now - self._last_update < self.UPDATE_SECONDS:
            return
        self._last_update = now
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
        self._throttle = PedalThrottle()
        self.reset()
        self._force = WheelForceFeedback(self._joystick.get_name(), args.wheel_force)

    def force_feedback(self, speed_kmh):
        self._force.update(speed_kmh, self._steer())

    def close(self):
        self._force.close()

    def reset(self):
        # The wheel is not necessarily centered when autonomous driving starts.
        pygame.event.pump()
        self._steer_baseline = self._steer()
        self._pedal_baseline = (0.0, 0.0)

    def mark_input(self, keys):
        """At the TOR: the wheel and pedals as they are now are the baseline; only a move from here
        takes over (a wheel held turned or a pedal held down through the pre-alert does not)."""
        pygame.event.pump()
        self._steer_baseline = self._steer()
        self._pedal_baseline = (self._pedal(self._throttle_axis), self._pedal(self._brake_axis))

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
        throttle, brake = self._pedal_baseline
        return (self._pedal(self._throttle_axis) > throttle + PEDAL_TAKEOVER or
                self._pedal(self._brake_axis) > brake + PEDAL_TAKEOVER or
                abs(self._steer() - self._steer_baseline) > STEER_TAKEOVER)

    def hand_brake(self):
        return self._handbrake_button >= 0 and bool(self._joystick.get_button(self._handbrake_button))

    def peek(self, keys):
        """(steer, throttle, brake) the driver is asking for right now."""
        return self._steer(), self._pedal(self._throttle_axis), self._pedal(self._brake_axis)

    def update(self, control, keys, milliseconds, speed_kmh, incline):
        control.steer = self._steer()
        control.brake = _interpolate(BRAKE_CURVE, self._pedal(self._brake_axis))
        control.throttle = self._throttle.step(self._pedal(self._throttle_axis), control.brake, speed_kmh, incline,
                                               milliseconds / 1000.0)


class PedalThrottle(object):
    """CARLA throttle for the throttle pedal (see PEDAL_ACCEL_FULL): the pedal travel asks for an
    acceleration, fading out at the settle speed (on level road); the throttle is what holds the
    current speed (HOLD_THROTTLE) plus a PI correction on the measured acceleration. With the pedal
    released (or pressed less than the speed needs) the car rolls on with throttle 0 and creeps at
    CREEP_SPEED, until the brake is pressed. The road's slope is taken off the acceleration asked
    for, as it would be with a real engine: uphill the car slows down and settles slower, downhill
    it speeds up."""

    def __init__(self):
        self._speed = None   # m/s, last step
        self._accel = 0.0    # m/s^2, filtered
        self._integral = 0.0

    def step(self, pedal, brake, speed_kmh, incline, dt):
        speed = speed_kmh / 3.6
        if self._speed is not None and dt > 0:
            share = min(1.0, dt / PEDAL_ACCEL_FILTER)
            self._accel += share * ((speed - self._speed) / dt - self._accel)
        self._speed = speed
        wanted = CREEP_ACCEL * (1.0 - speed_kmh / CREEP_SPEED)  # < 0 above the creep speed
        if pedal > 0.0:
            settle_speed = PEDAL_FULL_SPEED * pedal
            wanted = max(wanted, _interpolate(PEDAL_ACCEL_FULL, speed_kmh) * pedal ** PEDAL_ACCEL_CURVE
                         * (1.0 - (speed_kmh / settle_speed) ** 2))
        rolling = speed_kmh > 2 * CREEP_SPEED
        if brake > 0.0 or (rolling and wanted <= 0.0):  # roll on
            self._integral = 0.0
            return 0.0
        wanted -= 9.81 * incline
        error = wanted - self._accel
        hold = _interpolate(HOLD_THROTTLE, speed_kmh)
        throttle = hold + PEDAL_GAIN_P * error + self._integral
        if 0.0 < throttle < 1.0 or (throttle >= 1.0) != (error > 0):  # no wind-up while the throttle is at a limit
            self._integral += PEDAL_GAIN_I * error * dt
        return min(1.0, max(0.0, throttle))


class SpeedHold(object):
    """Throttle that keeps `target_kmh` (the speed at the takeover) on any slope."""

    def __init__(self, target_kmh):
        self.target = target_kmh
        self._integral = 0.0

    def step(self, speed_kmh, dt):
        error = self.target - speed_kmh
        throttle = _interpolate(HOLD_THROTTLE, speed_kmh) + SPEED_HOLD_GAIN_P * error + self._integral
        if 0.0 < throttle < 1.0:  # no wind-up while the throttle is at a limit
            self._integral = min(0.3, max(-0.3, self._integral + SPEED_HOLD_GAIN_I * error * dt))
        return min(1.0, max(0.0, throttle))


def _interpolate(table, x):
    """Linear interpolation in a [(x, y)] table sorted by x, clamped at its ends."""
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


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

    Per frame, frame_ms is the time since the last frame and latency_ms the last measured
    control-to-display latency (see LatencyMeter; empty in asynchronous mode).

    The takeover period is the POST_WINDOW seconds that follow the takeover.
    """

    COLUMNS = ['trial', 'wall_time', 't_prealert_s', 't_tor_s', 'phase', 'event',
               'x', 'y', 'speed_kmh', 'a_lon', 'a_lat', 'steer', 'throttle', 'brake',
               'driver_steer', 'driver_throttle', 'driver_brake', 'lane_id', 'lane_offset_m',
               'lead_gap_m', 'lead_speed_kmh', 'ttc_s', 'collisions', 'event_dist_m', 'fog_density',
               'frame_ms', 'latency_ms', 'scenario', 'intervention', 'input', 'lane', 'vehicles',
               'takeover_type', 'tot_s', 'tor_reaction_s', 'first_input_s',
               'speed_prealert_kmh', 'speed_takeover_kmh', 'window_complete',
               'malat', 'malon', 'sdlp', 'max_lane_offset', 'lane_changes',
               'speed_min_kmh', 'speed_mean_kmh', 'min_ttc_s', 'min_gap_m', 'collisions_window']

    def __init__(self, world, traffic, driver_input, args, started, window=POST_WINDOW, latency=None):
        self._world = world
        self._latency = latency
        self._last_sample = None
        self._traffic = traffic
        self._half_length = world.player.bounding_box.extent.x  # bounding_box is a server round trip
        self._input = driver_input
        self._window = window
        self._constant = {'scenario': args.scenario, 'intervention': args.intervention, 'input': args.input,
                          'lane': args.lane, 'vehicles': args.vehicles}
        self.dir = os.path.join(LOG_DIR, started.strftime('%y%m%d_%H%M%S'))
        self.path = os.path.join(self.dir, 'raw.csv')
        self._file = None
        self._writer = None
        self._trial = 0
        self._active = False
        self._event_dist = None
        self._fog = None
        self._enabled = not args.no_log

    @property
    def trial(self):
        """Number of the current (or last) trial, 0 before the first one."""
        return self._trial

    # -- trial events ----------------------------------------------------------

    def start_trial(self, now):
        if not self._enabled:
            return
        self._trial += 1
        self._active = True
        self._t0 = now
        self._last_sample = None
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
            import analyze_takeover  # next to this script
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
            'frame_ms': _fmt(None if self._last_sample is None else (now - self._last_sample) * 1000.0, 1),
            'latency_ms': _fmt(self._latency and self._latency.latest, 1),
        }
        self._last_sample = now
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
    escort_sides = ('left', 'right')  # EscortCars after the takeover: lanes next to the car to fill
    closure = None                    # (start, end) in lane 3 where lanes 3 and 4 are closed: EscortCars' merge plan
    obstacle = None                   # carla.Location of the lane 2 obstacle after the closure (EscortCars)
    has_scene = False                 # objects on the road that are removed once passed (SceneScenario)
    scene_cleared = False             # ... and they have been: the NDRT follow-up messages can come
    ego_index = None                  # the car's route index, set by TakeoverExperiment every frame

    def __init__(self, number, args):
        self.number = number
        self.name, self.message, tor_lead = SCENARIOS[number]
        if args.alert_lead is not None:
            self.lead = args.alert_lead
        elif tor_lead is None:  # the event point starts the fog, the pre-alert follows its density
            self.lead = 0.0
        else:
            self.lead = (tor_lead if args.tor_lead is None else args.tor_lead) + args.pre_alert
        self.event_index = None
        self._new_signs = []
        self._placed = []        # every sign placed, for clear_scene()
        self._old_signs = []     # signs to take off the road
        self._taken_over = False

    def take_signs(self):
        """Signs placed since the last call (road_signs.Sign), for RoadSigns to draw."""
        signs, self._new_signs = self._new_signs, []
        self._placed.extend(signs)
        return signs

    def take_old_signs(self):
        """Signs removed since the last call, for RoadSigns to stop drawing."""
        signs, self._old_signs = self._old_signs, []
        return signs

    def test_event_index(self):
        """Route index of the event point, known from the start (the test run places the car before it)."""
        return self.event_index

    def _place_signs(self, route, index, signs, color):
        """Signs on the right shoulder before route `index`; route: lane 3."""
        for distance, lines, arrow, *image in signs:
            waypoint = route[(index - int(round(distance / ROUTE_RESOLUTION))) % len(route)]
            if not image:
                self._new_signs.append(Sign(waypoint, SIGN_SHOULDER, SIGN_HEIGHT, lines, color, arrow=arrow))
                continue
            if not lines:  # the picture alone, on its post
                self._new_signs.append(ImageSign(waypoint, SIGN_SHOULDER, SIGN_HEIGHT,
                                                 os.path.join(SIGN_IMAGE_DIR, image[0]), SIGN_IMAGE_WIDTH))
                continue
            plate = Sign(waypoint, SIGN_SHOULDER, SIGN_HEIGHT, lines, color, letter=SIGN_PLATE_LETTER)
            self._new_signs.append(plate)
            self._new_signs.append(ImageSign(waypoint, SIGN_SHOULDER, plate.top + 0.2,
                                             os.path.join(SIGN_IMAGE_DIR, image[0]), SIGN_IMAGE_WIDTH,
                                             post_from=plate.top))

    def _place_arrow_board(self, route, index):
        """The arrow board where lanes 3 and 4 start to close, at route `index`; route: lane 3."""
        self._new_signs.append(ImageSign(route[index % len(route)], ARROW_BOARD_OFFSET, ARROW_BOARD_HEIGHT,
                                         os.path.join(SIGN_IMAGE_DIR, ARROW_BOARD_IMAGE), ARROW_BOARD_WIDTH,
                                         pixels=ARROW_BOARD_PIXELS))

    def tick(self, now, laps):
        pass

    def on_event(self, now):
        """The car got `lead` seconds from the event point. True: start the pre-alert now."""
        return True

    def alert_due(self):
        """True when the scenario wants the pre-alert now (for alerts not tied to a position)."""
        return False

    def seconds_to_alert(self, event_dist, speed):
        """Estimated seconds until the automatic pre-alert (None: none coming). event_dist: m to
        the event point while the pre-alert for it is still to come, else None; speed in m/s."""
        if event_dist is None or speed <= 5.0:
            return None
        return event_dist / speed - self.lead

    def on_alert(self, now):
        pass

    def on_takeover(self, now):
        self._taken_over = True

    def on_engage(self, now):
        self._taken_over = False

    def fog_density(self):
        return None

    def cleanup(self, client):
        pass


class PracticeScenario(Scenario):
    """0: practice drive, manual from the start. No event point, so no pre-alert and nothing logged.
    In bright daylight (PRACTICE_WEATHER); the server's weather comes back afterwards."""

    manual_only = True
    escort_sides = ()

    def __init__(self, args, sim_world):
        super(PracticeScenario, self).__init__(0, args)
        self._world = sim_world
        self._original = sim_world.get_weather()
        sim_world.set_weather(getattr(carla.WeatherParameters, PRACTICE_WEATHER))
        logging.info('Scenario 0, practice drive: manual driving, no takeover requests, %s', PRACTICE_WEATHER)

    def cleanup(self, client):
        self._world.set_weather(self._original)


class ExitScenario(Scenario):
    """1: the car reaches the end of its autonomous stretch (an exit point). Signs 1 km and 500 m
    before it and at it; the exit lane is lane 4, the ramp leaves at the junction after it."""

    escort_sides = ()  # the driver leaves the highway at the exit

    def __init__(self, args, route, lane3_route):
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
        self._place_signs(lane3_route, self.event_index, EXIT_SIGNS, GREEN)


class SceneScenario(Scenario):
    has_scene = True
    """A scenario with objects on the road (work zone, accident). After the takeover a van stands in
    lane 2 LANE2_OBSTACLE_AFTER m past the end of the scene (_spawn_obstacle). Once the driver has
    driven SCENE_CLEAR_BEHIND m past it, the scene, the van and the signs are removed for good: no
    more pre-alerts for it on later laps.

    Subclasses set _index (route index of the scene) and call _plan_obstacle(m from _index to the
    scene's end)."""

    def __init__(self, number, args, client, route):
        super(SceneScenario, self).__init__(number, args)
        self._client = client
        self._count = len(route)
        self._test = args.test
        self._actors = []
        self._end_index = None       # route index where the scene is removed from behind (the obstacle)
        self._obstacle_index = None
        self._obstacle_spawned = False
        self._van = None             # the obstacle, until its doors are opened (the frame after it appears)
        # the pictures of the image signs, traced now rather than when they appear while driving
        preload(os.path.join(SIGN_IMAGE_DIR, ARROW_BOARD_IMAGE), ARROW_BOARD_PIXELS)
        preload(os.path.join(SIGN_IMAGE_DIR, LANE2_TRIANGLE), LANE2_TRIANGLE_PIXELS)
        for _, _, _, *image in WORKZONE_SIGNS + ACCIDENT_SIGNS:
            if image:
                preload(os.path.join(SIGN_IMAGE_DIR, image[0]))
        self._done = False

    def _plan_obstacle(self, scene_length):
        self._obstacle_index = (self._index + int((scene_length + LANE2_OBSTACLE_AFTER) / ROUTE_RESOLUTION)) % self._count
        self._end_index = self._obstacle_index
        waypoint = self._lane3[self._obstacle_index % len(self._lane3)].transform
        right = waypoint.get_right_vector()
        self.obstacle = waypoint.location - carla.Location(right.x, right.y, 0.0) * LANE_WIDTH

    @property
    def scene_cleared(self):
        return self._done

    def obstacle_passed(self):
        """True once the car is MERGE_CLEAR_AFTER m past the lane 2 obstacle, along the route."""
        if self.ego_index is None or self._obstacle_index is None:
            return False
        behind = ((self.ego_index - self._obstacle_index) % self._count) * ROUTE_RESOLUTION
        return MERGE_CLEAR_AFTER <= behind < MERGE_CLEAR_AFTER + 500.0

    def test_event_index(self):
        return self._block_index

    def _plan_block(self, taper_from, taper_to):
        """The event point: where the taper of cones (from the outer edge of lane 4 at `taper_from` m to
        lane 3's left edge at `taper_to` m from _index) reaches a car driving in the middle of lane 3.
        With the TOR TOR_SECONDS before it, a car still in lane 3 at the forced takeover hits the cones."""
        outer, inner = 1.5 * LANE_WIDTH, -0.5 * LANE_WIDTH + 0.55
        at = taper_from + (taper_to - taper_from) * (outer - CAR_HALF_WIDTH) / (outer - inner)
        self._block_index = (self._index + int(math.floor(at / ROUTE_RESOLUTION))) % self._count

    def _spawn_obstacle(self):
        """The van in lane 2, once the driver has taken over and is near (traffic is gone by then;
        none may drive into it), as soon as no car is close to its place: hazard lights on, doors
        open, a warning triangle behind it."""
        if self._van is not None:
            self._van.open_door(carla.VehicleDoor.All)  # not in the frame it is spawned: it would not open
            self._van = None
        if self._obstacle_spawned or not self._taken_over or not self._actors or self.ego_index is None:
            return
        ahead = ((self._obstacle_index - self.ego_index) % self._count) * ROUTE_RESOLUTION
        if ahead > LANE2_OBSTACLE_SPAWN:
            return
        if ahead > LANE2_OBSTACLE_LATEST and _car_near(self._world, [self.obstacle], 30.0) is not None:
            return
        self._obstacle_spawned = True
        hazards = int(carla.VehicleLightState.LeftBlinker | carla.VehicleLightState.RightBlinker |
                      carla.VehicleLightState.Position)
        put = _route_placer(self._world, self._lane3, self._obstacle_index, self._actors)
        self._van = put(LANE2_OBSTACLE, 0.0, -LANE_WIDTH, lift=0.3, hold=True, lights=hazards)
        if self._van is None:
            logging.warning('Lane 2 obstacle: could not spawn it %.0f m ahead', ahead)
            return
        waypoint = self._lane3[(self._obstacle_index - int(LANE2_TRIANGLE_BEHIND / ROUTE_RESOLUTION)) % len(self._lane3)]
        self._new_signs.append(ImageSign(waypoint, -LANE_WIDTH, 0.02, os.path.join(SIGN_IMAGE_DIR, LANE2_TRIANGLE),
                                         LANE2_TRIANGLE_WIDTH, post_from=None, pixels=LANE2_TRIANGLE_PIXELS))
        logging.info('Lane 2 obstacle: a van with hazard lights and open doors %.0f m ahead', ahead)

    def _clear_when_passed(self):
        if not self._actors or not self._taken_over or self.ego_index is None:
            return
        behind = ((self.ego_index - self._end_index) % self._count) * ROUTE_RESOLUTION
        if not SCENE_CLEAR_BEHIND <= behind < SCENE_CLEAR_BEHIND + 500.0:
            return
        destroy_actors(self._client, self._actors)
        logging.info('%s: the car is %.0f m past it, %d objects and %d signs removed', self.message, behind,
                     len(self._actors), len(self._placed))
        self._actors = []
        self._old_signs, self._placed = self._placed, []
        self.event_index = None
        self.closure = self.obstacle = None
        self._done = True

    def cleanup(self, client):
        if self._actors:
            destroy_actors(client, self._actors)
            self._actors = []


class WorkzoneScenario(SceneScenario):
    """2: after the first lap a work zone closes lanes 3 and 4 further ahead."""

    def __init__(self, args, client, sim_world, route, lane3_route):
        super(WorkzoneScenario, self).__init__(2, args, client, route)
        self._world = sim_world
        self._lane3 = lane3_route
        at = args.workzone_at if args.workzone_at is not None else WORKZONE_AT
        self._index = int(at / ROUTE_RESOLUTION) % len(route)
        self._plan_obstacle(WORKZONE_TAPER + WORKZONE_LENGTH + WORKZONE_END_TAPER)
        self._plan_block(0.0, WORKZONE_TAPER)
        # lane 3 centerline along the zone, from just before the first cone to past the last one
        first = self._index - int(20.0 / ROUTE_RESOLUTION)
        last = self._index + int((WORKZONE_TAPER + WORKZONE_LENGTH + WORKZONE_END_TAPER + 30.0) / ROUTE_RESOLUTION)
        self._zone_points = [lane3_route[i % len(lane3_route)].transform.location for i in range(first, last + 1)]
        self._due = None              # time the work zone became due (waiting for a clear road)
        logging.info('Scenario 2, work zone: appears after lap %d, %.0f m from the start',
                     0 if self._test else WORKZONE_AFTER_LAPS, self._index * ROUTE_RESOLUTION)

    def tick(self, now, laps):
        self._spawn_obstacle()
        self._clear_when_passed()
        if self.event_index is None and not self._done and (self._test or laps >= WORKZONE_AFTER_LAPS):
            if self._due is None:
                self._due = now
            blocking = None if self._test else _car_near(self._world, self._zone_points)
            if blocking is not None and now - self._due < WORKZONE_MAX_WAIT:
                return
            if blocking is not None:
                logging.warning('Work zone: car %d still next to it after %.0f s, spawning anyway',
                                blocking.id, WORKZONE_MAX_WAIT)
            elif now - self._due > 0.5:
                logging.info('Work zone: waited %.1f s for passing cars', now - self._due)
            self._actors = spawn_workzone(self._world, self._lane3, self._index)
            self._place_signs(self._lane3, self._index, WORKZONE_SIGNS, ORANGE)
            self._place_arrow_board(self._lane3, self._index)
            self.event_index = self._block_index
            zone = WORKZONE_TAPER + WORKZONE_LENGTH + WORKZONE_END_TAPER
            self.closure = (self._lane3[self._index].transform.location,
                            self._lane3[(self._index + int(zone / ROUTE_RESOLUTION)) % len(self._lane3)].transform.location)


def _car_near(sim_world, points, clearance=WORKZONE_CLEARANCE):
    """A car within `clearance` m of any of `points` (lane 3's centerline along an obstacle, so lanes
    2-4), or None. Spawning dozens of objects next to a passing car can clip it off the road."""
    for vehicle in sim_world.get_actors().filter('vehicle.*'):
        location = vehicle.get_location()
        if any(location.distance(point) < clearance for point in points):
            return vehicle
    return None


class AccidentScenario(SceneScenario):
    """4: a crash closes lanes 3 and 4 ahead (spawn_accident), on a straight ACCIDENT_AT (880) m from the start.

    The scene appears once the car is ACCIDENT_SPAWN_AHEAD m from it (so on its second pass, out of
    view and before the pre-alert is due), as soon as no car is next to it or after ACCIDENT_MAX_WAIT s.
    From then on the pre-alert and the TOR come like the work zone's. Test run: it appears at the start."""

    def __init__(self, args, client, sim_world, route, lane3_route):
        super(AccidentScenario, self).__init__(4, args, client, route)
        self._world = sim_world
        self._lane3 = lane3_route
        at = args.accident_at if args.accident_at is not None else ACCIDENT_AT
        self._index = int(at / ROUTE_RESOLUTION) % len(route)
        self._plan_obstacle(ACCIDENT_END)
        self._plan_block(ACCIDENT_TAPER_FROM, ACCIDENT_TAPER_TO)
        first = self._index + int((ACCIDENT_START - 10.0) / ROUTE_RESOLUTION)
        last = self._index + int((ACCIDENT_END + 20.0) / ROUTE_RESOLUTION)
        self._zone_points = [lane3_route[i % len(lane3_route)].transform.location for i in range(first, last + 1)]
        self._due = None
        logging.info('Scenario 4, accident: lanes 3 and 4 closed %.0f m from the start; the scene appears '
                     '%.0f m ahead of the car', self._index * ROUTE_RESOLUTION, ACCIDENT_SPAWN_AHEAD)

    def tick(self, now, laps):
        self._spawn_obstacle()
        self._clear_when_passed()
        if self.event_index is not None or self.ego_index is None or self._done:
            return
        ahead = ((self._index - self.ego_index) % len(self._lane3)) * ROUTE_RESOLUTION
        # a window that the car crosses once per lap (the scene is closer than this at the start)
        if not self._test and not ACCIDENT_SPAWN_AHEAD - 400.0 < ahead <= ACCIDENT_SPAWN_AHEAD:
            self._due = None
            return
        if self._due is None:
            self._due = now
        blocking = None if self._test else _car_near(self._world, self._zone_points)
        if blocking is not None and now - self._due < ACCIDENT_MAX_WAIT:
            return
        if blocking is not None:
            logging.warning('Accident: car %d still next to the scene after %.0f s, spawning anyway',
                            blocking.id, ACCIDENT_MAX_WAIT)
        self._actors = spawn_accident(self._world, self._lane3, self._index)
        self._place_signs(self._lane3, self._index, ACCIDENT_SIGNS, ORANGE)
        self._place_arrow_board(self._lane3, self._index + int(ACCIDENT_TAPER_FROM / ROUTE_RESOLUTION))
        self.event_index = self._block_index
        self.closure = tuple(self._lane3[(self._index + int(at / ROUTE_RESOLUTION)) % len(self._lane3)].transform.location
                             for at in (ACCIDENT_TAPER_FROM, ACCIDENT_END))


class FogScenario(Scenario):
    """3: fog thickens gradually from the fog point on.

    density 0 --(rise)--> threshold: pre-alert --> TOR --> takeover --> max, FOG_PEAK_AFTER s
    after the takeover. The rate up to the pre-alert is threshold / rise. From the pre-alert on
    it is scaled by FOG_PRE_ALERT / --pre-alert, so the density at the TOR is the same for
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
        # test run: the fog thickens from the start so it is at the threshold at the (timed) pre-alert
        self._test_after = getattr(args, 'test_alert_after', None) if args.test else None
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

    def seconds_to_alert(self, event_dist, speed):
        """The pre-alert follows the fog density, not the position."""
        if self._state != 'rising' or self._alerted or self._rate <= 0.0:
            return None
        return max(self._threshold - self._density, 0.0) / self._rate

    def on_alert(self, now):
        self._alerted = True
        if self._state != 'rising':  # P key before the fog point: start the fog too
            self._start(now)
        self._rate = self._threshold / self._rise * FOG_PRE_ALERT / self._pre_alert
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
        if self._test_after is not None:
            self._start(now)
            self._rate = self._threshold / self._test_after
            self._test_after = None
            logging.info('Test run: fog from the start, at %.0f when the pre-alert comes', self._threshold)
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


def test_start_index(scenario, route, args, alert_after):
    """Test run: the route index to start at, so that with the pre-alert `alert_after` s after the start
    the TOR still comes the scenario's TOR lead before the event point (speeding up from standstill
    at AUTO_ACCEL, then at --speed). Scenario 3: the fog starts with the pre-alert, at the fog point."""
    event = scenario.test_event_index()
    if event is None:
        return 0
    tor_lead = SCENARIOS[scenario.number][2]
    if tor_lead is not None and args.tor_lead is not None:
        tor_lead = args.tor_lead
    seconds = alert_after + (0.0 if tor_lead is None else args.pre_alert + tor_lead)
    speed = args.speed / 3.6
    distance = max(speed * seconds - speed ** 2 / (2.0 * AUTO_ACCEL), 50.0)
    index = (event - int(distance / ROUTE_RESOLUTION)) % len(route)
    logging.info('Test run: the car starts %.0f m before the event point (%.0f m from the route start)',
                 distance, index * ROUTE_RESOLUTION)
    return index


def connect_server(host, port):
    """A client of the CARLA server, once it answers: a server that has just been started takes a
    while, and a call made too early can hang (retried every SERVER_RETRY s, with a log line)."""
    client = carla.Client(host, port)
    started = time.monotonic()
    while True:
        client.set_timeout(SERVER_RETRY)
        try:
            version = client.get_server_version()
            client.get_world().get_map().name
            break
        except RuntimeError:
            logging.info('Waiting for the CARLA server at %s:%d (%.0f s)...', host, port, time.monotonic() - started)
            client = carla.Client(host, port)
    client.set_timeout(60.0)
    logging.info('CARLA server %s ready', version)
    return client


def device_address(value, name, key):
    """`value` as given, or the address recorded under `key` in devices.json when it is `name`."""
    if value is None or value.lower() != name:
        return value
    try:
        with open(DEVICES_FILE, encoding='utf-8') as handle:
            address = (json.load(handle).get(key) or '').strip()
    except (OSError, ValueError) as error:
        raise RuntimeError('%s: %s' % (DEVICES_FILE, error))
    if not address:
        raise RuntimeError('no "%s" address in %s yet: put it there or give the IP' % (key, DEVICES_FILE))
    return address


def make_scenario(args, client, sim_world, routes, route):
    if args.scenario == 0:
        return PracticeScenario(args, sim_world)
    if args.scenario == 2:
        return WorkzoneScenario(args, client, sim_world, route, routes[3])
    if args.scenario == 3:
        return FogScenario(args, sim_world, route)
    if args.scenario == 4:
        return AccidentScenario(args, client, sim_world, route, routes[3])
    return ExitScenario(args, route, routes[3])


class Intervention(object):
    """Text the glasses show during the pre-alert, set in intervention_config.json.

    Its lines come from NDRT_scripts/scenario<N>_<intervention>_<format>.txt. From delay_seconds
    after the pre-alert on, one line at a time, each for question_seconds (summary and question
    alike). Then the text goes away until the TOR. With the defaults:
        0-5 s pre-alert only, 5-15 / 15-25 / 25-35 s SA level or ready-to-resume step 1 / 2 / 3,
        35-60 s pre-alert only again, 60 s TOR
    """

    def __init__(self, path, scenario_number):
        with open(path, encoding='utf-8-sig') as handle:
            config = json.load(handle)
        self.kind = config.get('intervention', 'none')
        self.format = config.get('format', 'summary')
        self.delay = float(config.get('delay_seconds', 5.0))
        self.question_seconds = float(config.get('question_seconds', 10.0))
        # test run (see TEST_ALERT_AFTER): None, or (s from the start to the pre-alert, s pre-alert)
        self.test = None
        if config.get('test'):
            self.test = (float(config.get('test_alert_after', TEST_ALERT_AFTER)),
                         float(config.get('test_pre_alert', TEST_PRE_ALERT)))
        if self.kind not in INTERVENTIONS:
            raise ValueError('%s: "intervention" must be one of %s' % (path, ', '.join(INTERVENTIONS)))
        if self.format not in INTERVENTION_FORMATS:
            raise ValueError('%s: "format" must be one of %s' % (path, ', '.join(INTERVENTION_FORMATS)))
        self.lines = []
        # the participant's own RtR summary (kakao_ndrt.py); self.lines is the fallback
        self.live = self.kind == 'NDRT' and self.format == 'summary' and scenario_number != 0
        if self.kind == 'none' or scenario_number == 0:
            self.name = 'none'
            logging.info('Intervention: none (pre-alert only)')
            return
        self.name = '%s_%s' % (self.kind, self.format)
        script = os.path.join(INTERVENTION_DIR, 'scenario%d_%s.txt' % (scenario_number, self.name))
        with open(script, encoding='utf-8-sig') as handle:
            self.lines = [line.strip() for line in handle if line.strip() and not line.lstrip().startswith('#')]
        if not self.lines:
            raise ValueError('%s has no text' % script)
        logging.info('Intervention: %s, %s (%d lines, after %.1f s)', self.name, os.path.basename(script),
                     len(self.lines), self.delay)

    def due(self, elapsed):
        """True while a text is shown `elapsed` seconds after the pre-alert."""
        page = int((elapsed - self.delay) // self.question_seconds) if self.lines else -1
        return 0 <= page < len(self.lines)

    def text(self, elapsed, lines=None):
        """Line to show `elapsed` seconds after the pre-alert, as a list ([] for none). lines: the
        summary to show instead of the file's (the same number of lines)."""
        if not self.due(elapsed):
            return []
        lines = lines or self.lines
        page = int((elapsed - self.delay) // self.question_seconds)
        return [lines[page]] if page < len(lines) else []


# ==============================================================================
# -- sound ---------------------------------------------------------------------
# ==============================================================================


class AlertSound(object):
    """Alert sounds made in code: a chime for the pre-alert, repeating beeps for the TOR. With
    `glasses` (GlassesLink) TORApp plays them on the glasses instead, while their display runs;
    when it does not, they play here, so an alert is never silent."""

    def __init__(self, enabled=True, glasses=None):
        self._ok = False
        self._glasses = glasses
        self._warned = False
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
            return
        try:
            self._kakao = pygame.mixer.Sound(KAKAO_SOUND)
        except Exception as error:  # pylint: disable=broad-except
            logging.warning('No KakaoTalk sound (%s: %s): the NDRT nudges play two tones', KAKAO_SOUND, error)
            self._kakao = self._sound([(1318.5, 0.12), (1046.5, 0.22)], 0.5)  # "카톡", as kakao_app
        self._kakao.set_volume(KAKAO_VOLUME)

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

    def _here(self):
        """Play on the PC: no glasses, or their display is not running."""
        if self._glasses is None or self._glasses.display_ready:
            return self._glasses is None
        if not self._warned:
            self._warned = True
            logging.warning('Glasses display not running: the alert sounds play on the PC')
        return True

    def pre_alert(self):
        if self._ok and self._here():
            self._beeps.stop()
            self._chime.play()

    def tor(self):
        if self._ok and self._here():
            self._beeps.play(loops=-1)

    def kakao(self):
        """A KakaoTalk message (NDRT nudge): always on the PC, even with the glasses."""
        if self._ok:
            self._kakao.play()

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
                 pre_alert=PRE_ALERT_SECONDS, glasses=None, intervention=None, clearance=None, cruise_kmh=None,
                 escort=None, rtr=None, test_alert_after=None, ndrt=None, phone_cluster=None, test_driver=None):
        self._world = world
        self._test_driver = test_driver      # TestDriver: drives after the takeover (--test-driver)
        self._phone_cluster = phone_cluster  # PhoneCluster: the gauges on a phone instead of the monitor
        self._ndrt = ndrt                   # KakaoNdrtLink: the NDRT chat on the NDRT laptop
        self._nudged = set()                # NDRT nudges posted (once each per run, _nudge_tick)
        self._takeover_time = None
        self._clearance = clearance         # TrafficClearance: the traffic leaves after the pre-alert
        self._escort = escort               # EscortCars: cars beside the car after the takeover
        self._escort_due = False            # the takeover happened, the escort cars still have to come
        self._cruise_kmh = cruise_kmh       # autonomous driving speed
        self._glasses = glasses             # GlassesLink: alerts on the glasses instead of the screen
        self._intervention = intervention   # Intervention: text on the glasses during the pre-alert
        self._shown_text = []
        self._rtr = rtr                     # RtrBridge: the NDRT summary is the participant's own RtR summary
        self._rtr_since = None              # time.monotonic() of this trial's summary request (None: not yet)
        self._rtr_lines = None              # the summary lines shown in this trial, fixed once shown
        self._speed_hold = None             # SpeedHold: after the takeover, until the driver presses a pedal
        self._speed_kmh = 0.0               # shown on the instrument cluster (_draw_cluster)
        self._pedal = 0.0                   # throttle pedal travel the driver gives, 0..1
        self._cluster = None                # the gauges' face, made for the monitor size (_cluster_face)
        self._needles = [0.0, 0.0]          # what the needles show: pedal %, km/h
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
        # test run: one automatic pre-alert at this time.monotonic(), none at the event point
        self._test_alert_at = None if test_alert_after is None else time.monotonic() + test_alert_after
        self._test = test_alert_after is not None
        if self._test:
            self._armed = False
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
        self._escort_due = False
        if self._escort is not None:
            self._escort.remove()
        self.mode = AUTO
        self._speed_hold = None
        self._rtr_since = None  # the next trial requests its own summary
        self._input.reset()
        self._world.hud.notification('Autonomous driving')
        logging.info('Autonomous driving engaged')

    def _start_alert(self, now, manual=False):
        """manual: the P key. It always requests a new RtR summary right away, from the draft as it is
        now; an automatic pre-alert uses the one requested RTR_LEAD s ahead."""
        self.mode = PRE_ALERT
        self._alert_time = now
        self._recorder.start_trial(now)
        self._sound.pre_alert()
        self._scenario.on_alert(now)
        self._mark('prealert')
        self._rtr_lines = None
        if self._rtr is not None and (manual or self._rtr_since is None):  # none requested ahead
            self._rtr_since = now
            self._rtr.request('p_key' if manual else 'prealert')
        if self._clearance is not None:
            self._clearance.start(now, self._world.player, now + self._pre_alert - TRAFFIC_CLEAR_BEFORE_TOR)
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
        self._takeover_time = now
        self._mark('takeover', forced=int(forced))
        self._scenario.on_takeover(now)
        self.mode = MANUAL
        self._escort_due = self._escort is not None and bool(self._scenario.escort_sides)
        self._sound.stop(confirm=True)
        self._control = carla.VehicleControl()
        self._input.reset()
        # the engine keeps pulling at the takeover speed until the driver presses a pedal (_parse_manual_keys)
        self._speed_hold = SpeedHold(self._world.player.get_velocity().length() * 3.6)
        self._world.hud.notification('Manual driving: ' + reason, seconds=4.0)
        logging.info('Manual driving: %s (holding %.0f km/h until a pedal)', reason, self._speed_hold.target)

    # -- per frame -------------------------------------------------------------

    def handle_event(self, event, now):
        if self._input.horn_event(event):
            return
        light = self._input.light_event(event)
        if light is not None:
            self._switch_light(light)
            return
        if self.mode in TAKEOVER_MODES and self._input.is_takeover_event(event):
            self._take_over(now)
            return
        if self.mode == MANUAL and self._input.is_reverse_event(event):
            self._toggle_reverse()
            return
        if event.type != pygame.KEYDOWN:
            return
        if event.key == K_k and self._ndrt is not None:
            if self._ndrt.release_followup('k_key'):
                self._world.hud.notification('NDRT: follow-up messages')
        elif event.key == K_p and self.mode == AUTO:
            self._start_alert(now, manual=True)
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

    def _escort_tick(self, now):
        """Start the escort cars after the takeover (the merge plan where lanes 3 and 4 are closed
        ahead, else beside the car), and move them."""
        if self._escort_due and self.mode == MANUAL:
            self._escort_due = False
            if self._scenario.closure is not None:
                self._escort.start_merge(now, self._scenario.closure,
                                         self._scenario.obstacle_passed if self._scenario.obstacle else None)
            else:
                self._escort.start(now, self._scenario.escort_sides)
        self._escort.tick(now, self._world.player)

    def _track_event(self, now):
        """Laps, distance to the scenario's event point, and the automatic pre-alert."""
        previous = self._index
        self._index = self._nearest_index(self._index)
        count = len(self._route)
        self._progress += (self._index - previous + count // 2) % count - count // 2
        if self._progress // count > self.laps:
            self.laps = self._progress // count
            logging.info('Lap %d completed', self.laps)
        self._scenario.ego_index = self._index
        self._scenario.tick(now, self.laps)
        if self._auto_alert and self.mode == AUTO and self._scenario.alert_due():
            logging.info('%s: automatic pre-alert', self._scenario.message)
            self._start_alert(now)
        if self._test_alert_at is not None and now >= self._test_alert_at and self.mode == AUTO:
            self._test_alert_at = None
            if self._auto_alert:
                logging.info('%s: test run, automatic pre-alert after the start', self._scenario.message)
                self._start_alert(now)
        event = self._scenario.event_index
        if event is None:
            self._event_dist = None
            return
        first = self._event_dist is None and self.laps == 0
        self._event_dist = ((event - self._index) % count) * ROUTE_RESOLUTION
        if first and not self._test and self._cruise_kmh and self._event_dist <= self._cruise_kmh / 3.6 * self._scenario.lead:
            # e.g. scenario 1: the exit point is 874 m from the start, the pre-alert 65 s (~1.4 km) before it
            self._armed = False
            logging.info('%s: event point %.0f m ahead at the start, closer than the pre-alert lead '
                         '(%.0f s): the pre-alert comes on the next pass', self._scenario.message,
                         self._event_dist, self._scenario.lead)
        velocity = self._world.player.get_velocity()
        speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
        self._request_rtr_ahead(now, speed)
        threshold = max(speed * self._scenario.lead, 5.0)
        if self._armed:
            if self._auto_alert and self.mode == AUTO and speed > 5.0 and self._event_dist <= threshold:
                self._armed = False
                logging.info('%s: event point %.0f m ahead (%.1f s)',
                             self._scenario.message, self._event_dist, self._event_dist / speed)
                if self._scenario.on_event(now):
                    self._start_alert(now)
        elif not self._test and self._event_dist > max(threshold, (self._cruise_kmh or 0.0) / 3.6 * self._scenario.lead) + 100.0:
            self._armed = True  # the event point has been passed (at cruise speed: not while starting off)

    def _mark(self, event, **fields):
        """The experiment's event in the NDRT laptop's log, on its clock."""
        if self._ndrt is not None:
            self._ndrt.mark(event, trial=self._recorder.trial, **fields)

    def _ndrt_tick(self, now):
        """The team's follow-up messages in the NDRT chat, once after the takeover: when the car is
        past the scene (scenarios 2 and 4), else NDRT_FOLLOWUP_AFTER s after the takeover."""
        if self._ndrt is None or self._ndrt.followup_released or self._takeover_time is None:
            return
        after = now - self._takeover_time
        if self._scenario.scene_cleared:
            reason = 'past the scene'
        elif after >= (NDRT_FOLLOWUP_LATEST if self._scenario.has_scene else NDRT_FOLLOWUP_AFTER):
            reason = '%.0f s after the takeover' % after
        else:
            return
        self._ndrt.release_followup(reason)

    def _nudge_tick(self, now):
        """The team pressing for the notice in the NDRT chat during the pre-alert and the TOR
        (kakao_sets "nudges": s after the pre-alert), each with the KakaoTalk sound on this PC."""
        if self._ndrt is None or self.mode not in (PRE_ALERT, TOR):
            return
        for index, after in enumerate(self._ndrt.nudge_times):
            if index not in self._nudged and now - self._alert_time >= after:
                self._nudged.add(index)
                self._ndrt.post_nudge(index, 'prealert')
                self._sound.kakao()
                logging.info('NDRT nudge %d (%.0f s after the pre-alert)', index, now - self._alert_time)

    def _request_rtr_ahead(self, now, speed):
        """NDRT summary: request the participant's RtR summary RTR_LEAD s before the automatic pre-alert."""
        if self._rtr is None or self._rtr_since is not None or not self._auto_alert or self.mode != AUTO:
            return
        eta = self._scenario.seconds_to_alert(self._event_dist if self._armed else None, speed)
        if eta is not None and eta <= RTR_LEAD:
            self._rtr_since = now
            logging.info('Pre-alert expected in %.1f s: requesting the RtR summary', eta)
            self._rtr.request('auto')

    def _summary_lines(self, now):
        """The RtR summary to show in this trial: the newest one requested since this trial's request,
        or the NDRT_scripts text if none has arrived."""
        result = self._rtr.result_since(self._rtr_since if self._rtr_since is not None else now)
        trial = self._recorder.trial
        if result is None:
            logging.warning('RtR summary not ready: showing the fixed text of NDRT_scripts')
            self._rtr.log({'event': 'shown', 'trial': trial, 'source': 'fallback', 'lines': self._intervention.lines})
            return list(self._intervention.lines)
        self._rtr.log({'event': 'shown', 'trial': trial, 'request_id': result['request_id'],
                       'source': result['source'], 'lines': result['lines']})
        return result['lines']

    def tick(self, clock, now):
        keys = pygame.key.get_pressed()
        self._track_event(now)
        if self._clearance is not None:
            self._clearance.tick(now, self._world.player)
        if self._escort is not None:
            self._escort_tick(now)
        self._ndrt_tick(now)
        self._nudge_tick(now)
        if self.mode in AUTONOMOUS_MODES:
            if self.mode in TAKEOVER_MODES and self._input.driver_active(keys):
                self._take_over(now)
            elif self.mode == PRE_ALERT and now - self._alert_time >= self._pre_alert:
                self.mode = TOR
                self._tor_time = now
                self._input.mark_input(keys)  # only input from now on takes over
                self._recorder.mark_tor(now)
                self._mark('tor')
                self._sound.tor()
                logging.info('TOR issued')
            elif self.mode == TOR and self._test_driver is not None and now - self._tor_time >= TestDriver.REACTION:
                self._take_over(now)
            elif self.mode == TOR and now - self._tor_time >= TOR_SECONDS:
                self._take_over(now, forced=True)

        speed_kmh = self._world.player.get_velocity().length() * 3.6
        self._speed_kmh, self._pedal = speed_kmh, self._input.peek(keys)[1]
        if self.mode in AUTONOMOUS_MODES:
            control = self._follower.run_step()
            self._pedal = control.throttle  # the cluster shows what the autopilot gives
        elif self._test_driver is not None and not self._scenario.manual_only:
            control = self._test_driver.run_step()
            self._pedal = control.throttle
        else:
            incline = self._world.player.get_transform().get_forward_vector().z  # sine of the road's slope, uphill > 0
            self._parse_manual_keys(keys, clock.get_time(), speed_kmh, incline)
            control = self._control
        self._world.player.apply_control(control)
        if self._phone_cluster is not None:
            blinker = 'left' if self._lights & LEFT_BLINKER else 'right' if self._lights & RIGHT_BLINKER else ''
            self._phone_cluster.update(self._speed_kmh, self._pedal, *self._mode_label(), blinker=blinker)
        self._input.force_feedback(speed_kmh)
        self._update_lights(control)
        self._recorder.sample(now, self.mode, self._event_dist, self._scenario.fog_density())
        if self._glasses is not None:
            self._update_glasses(now)

    def _update_glasses(self, now):
        """The overlay of render() on the glasses: the mode box label and the PRE-ALERT / TOR banner."""
        label = self._mode_label()[0]
        if self.mode == PRE_ALERT:
            elapsed = now - self._alert_time
            if self._rtr is not None and self._rtr_lines is None and self._intervention.due(elapsed):
                self._rtr_lines = self._summary_lines(now)
            text = self._intervention.text(elapsed, self._rtr_lines) if self._intervention is not None else []
            if text != self._shown_text:
                self._shown_text = text
                logging.info('Intervention text %.1f s after the pre-alert: %s', elapsed, ' / '.join(text))
            self._glasses.update(PRE_ALERT, self._scenario.message, self._pre_alert - elapsed, self._pre_alert,
                                 label, text)
        elif self.mode == TOR:
            self._glasses.update(TOR, self._scenario.message, TOR_SECONDS - (now - self._tor_time), TOR_SECONDS,
                                 label)
        else:
            self._glasses.update(self.mode, label=label)
        if self.mode != PRE_ALERT:
            self._shown_text = []

    def _parse_manual_keys(self, keys, milliseconds, speed_kmh, incline):
        self._input.update(self._control, keys, milliseconds, speed_kmh, incline)
        self._control.hand_brake = bool(keys[K_SPACE]) or self._input.hand_brake()
        self._control.reverse = self._control.gear < 0  # also when shifting down with the manual transmission
        if self._speed_hold is not None:
            # The throttle pedal takes over from the speed hold only once it asks for at least the
            # speed held (pedal travel speed / PEDAL_FULL_SPEED, see PedalThrottle): pressed less, the
            # hold keeps the speed (and the pedal does nothing yet), so there is no jump either way.
            # The brake ends the hold at once.
            pedal = self._input.peek(keys)[1]
            release_at = max(PEDAL_TAKEOVER, self._speed_hold.target / PEDAL_FULL_SPEED)
            if (pedal >= release_at or self._control.brake > 0.0 or self._control.hand_brake
                    or self._control.reverse):
                self._speed_hold = None
                logging.info('%s at %.0f km/h: the speed hold after the takeover is off',
                             'Throttle %.0f %%' % (pedal * 100) if pedal >= release_at else 'Brake', speed_kmh)
            else:
                self._control.throttle = self._speed_hold.step(speed_kmh, milliseconds / 1000.0)

    # -- overlay ---------------------------------------------------------------

    def _mode_label(self):
        """Text and color of the mode box at the top of the screen."""
        if self.mode == AUTO:
            return 'AUTONOMOUS - LOCKED', (40, 160, 70)
        if self.mode == PRE_ALERT:
            return 'AUTONOMOUS - LOCKED', (40, 160, 70)
        if self.mode in ALERT_MODES:
            return 'AUTONOMOUS', (40, 160, 70)
        if self._scenario.manual_only:
            return 'PRACTICE - MANUAL', (40, 110, 200)
        return 'MANUAL', (40, 110, 200)

    def render(self, display, fonts, now):
        big, small = fonts
        width = display.get_width()

        self._draw_cluster(display)
        # the mode at the lower right corner of the window (the right monitor): white on its color
        label, color = self._mode_label()
        box_width, box_height = small.size(label)[0] + 36, 34
        rect = (width - box_width - MODE_BOX_MARGIN, display.get_height() - box_height - MODE_BOX_MARGIN,
                box_width, box_height)
        self._draw_box(display, small, label, rect, color, (255, 255, 255), alpha=255)
        pygame.draw.rect(display, (255, 255, 255), rect, 2)

        if self._glasses is not None:
            return  # the pre-alert and the TOR are on the glasses
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

    def _draw_cluster(self, display):
        """Driver's seat view: a tablet at the bottom middle of the middle monitor with two round gauges
        whose needles turn, the throttle pedal travel (left) and the speed (right), the speed in
        digits between them, and a clock in its status bar."""
        manager = self._world.camera_manager
        if manager.transform_index != 0 or self._phone_cluster is not None:
            return
        if self._cluster is None or self._cluster['size'] != manager.screen_size:
            self._cluster = self._cluster_face(manager.screen_size)
        cluster = self._cluster
        for k, value in enumerate((min(max(self._pedal, 0.0), 1.0) * 100.0, self._speed_kmh)):
            self._needles[k] += GAUGE_FOLLOW * (value - self._needles[k])
        surface = cluster['face'].copy()
        for (center, radius, maximum), value in zip(cluster['dials'], self._needles):
            angle = math.radians(GAUGE_START - GAUGE_SWEEP * min(max(value / maximum, 0.0), 1.0))
            dx, dy = math.cos(angle), -math.sin(angle)
            tip = (center[0] + dx * radius * 0.84, center[1] + dy * radius * 0.84)
            tail = (center[0] - dx * radius * 0.14, center[1] - dy * radius * 0.14)
            pygame.draw.line(surface, CLUSTER_NEEDLE, tail, tip, max(2, int(radius * 0.045)))
            pygame.draw.circle(surface, CLUSTER_DIM, center, max(3, int(radius * 0.09)))
        digits = cluster['digits'].render('%d' % round(self._speed_kmh), True, CLUSTER_TEXT)
        surface.blit(digits, digits.get_rect(center=cluster['readout']))
        clock = cluster['status'].render(time.strftime('%H:%M'), True, CLUSTER_DIM)
        surface.blit(clock, clock.get_rect(topright=cluster['clock']))
        lit = int(time.monotonic() * 2.0 * BLINKER_HZ) % 2 == 0  # on half of each period
        for flag, points in ((LEFT_BLINKER, cluster['arrows'][0]), (RIGHT_BLINKER, cluster['arrows'][1])):
            if self._lights & flag:
                pygame.draw.polygon(surface, BLINKER_ON if lit else BLINKER_DIM, points)
            else:
                pygame.draw.polygon(surface, BLINKER_DIM, points, 2)
        surface.blit(cluster['glare'], (0, 0))
        surface.blit(cluster['mask'], (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        x = manager.screens // 2 * manager.screen_size[0] + cluster['origin'][0]
        display.blit(cluster['shadow'], (x - cluster['shadow_pad'], cluster['origin'][1] - cluster['shadow_pad']))
        display.blit(surface, (x, cluster['origin'][1]))

    @staticmethod
    def _cluster_face(size):
        """The tablet with the gauges but no needles, for one monitor size: face, mask (its rounded
        corners), glare (light on the glass, over the needles), shadow, origin on the monitor, dials
        [(center, radius, full scale)], fonts, readout and clock positions."""
        width, height = size
        panel_w, panel_h = int(CLUSTER_PANEL[0] * width), int(CLUSTER_PANEL[1] * height)
        x0, y0 = (width - panel_w) // 2, height - panel_h  # on the bottom edge
        corner = max(6, int(panel_h * 0.09))
        bezel = max(6, int(panel_h * 0.055))
        mask = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 0))
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=corner)

        # body: dark frame with a lighter rim, a front camera in the top bezel
        face = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        face.fill((0, 0, 0, 0))
        pygame.draw.rect(face, CLUSTER_BEZEL + (255,), face.get_rect(), border_radius=corner)
        pygame.draw.rect(face, CLUSTER_EDGE + (255,), face.get_rect(), width=2, border_radius=corner)
        pygame.draw.circle(face, (44, 46, 54), (panel_w // 2, bezel // 2), max(2, bezel // 5))
        # screen: a dark gradient, top to bottom
        screen = pygame.Rect(bezel, bezel, panel_w - 2 * bezel, panel_h - 2 * bezel)
        gradient = pygame.Surface(screen.size, pygame.SRCALPHA)
        top, bottom = CLUSTER_SCREEN
        for row in range(screen.height):
            share = row / max(1, screen.height - 1)
            gradient.fill(tuple(int(a + (b - a) * share) for a, b in zip(top, bottom)) + (255,),
                          pygame.Rect(0, row, screen.width, 1))
        screen_mask = pygame.Surface(screen.size, pygame.SRCALPHA)
        screen_mask.fill((0, 0, 0, 0))
        pygame.draw.rect(screen_mask, (255, 255, 255, 255), screen_mask.get_rect(), border_radius=max(3, corner - bezel // 2))
        gradient.blit(screen_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        face.blit(gradient, screen.topleft)

        default = pygame.font.get_default_font()
        status = pygame.font.Font(default, max(9, int(screen.height * 0.075)))
        status_h = int(screen.height * 0.11)  # the status bar: a clock at its right
        clock = (screen.right - int(screen.height * 0.06), screen.top + int(status_h * 0.25))

        # the gauges, laid out below the status bar (the dials reach a little below the area)
        rw, rh = screen.width * 0.94, (screen.height - status_h) / 1.3
        rx, ry = screen.left + (screen.width - rw) / 2.0, screen.top + status_h
        radius = int(rh * 0.56)
        cy = int(ry + rh * 0.66)
        dials = [((int(rx + rw * 0.24), cy), radius, 100.0), ((int(rx + rw * 0.76), cy), radius, GAUGE_MAX_SPEED)]
        small = pygame.font.Font(default, max(9, int(radius * 0.19)))
        # (minor tick step, labelled every, title)
        scales = ((10.0, 20.0, 'ACCEL %'), (10.0, 40.0, 'km/h'))
        for ((cx, cyy), r, maximum), (step, label_every, title) in zip(dials, scales):
            # a faint track along the sweep, as on a car's screen
            arc = pygame.Rect(cx - r, cyy - r, 2 * r, 2 * r)
            pygame.draw.arc(face, (46, 54, 66), arc, math.radians(GAUGE_START - GAUGE_SWEEP),
                            math.radians(GAUGE_START), max(2, int(r * 0.03)))
            value = 0.0
            while value <= maximum + 1e-6:
                angle = math.radians(GAUGE_START - GAUGE_SWEEP * value / maximum)
                dx, dy = math.cos(angle), -math.sin(angle)
                major = abs(value % (2 * step)) < 1e-6
                inner = r * (0.78 if major else 0.86)
                pygame.draw.line(face, CLUSTER_TEXT if major else CLUSTER_DIM, (cx + dx * inner, cyy + dy * inner),
                                 (cx + dx * r * 0.96, cyy + dy * r * 0.96), 2 if major else 1)
                if abs(value % label_every) < 1e-6:
                    text = small.render('%d' % value, True, CLUSTER_TEXT)
                    face.blit(text, text.get_rect(center=(cx + dx * r * 0.6, cyy + dy * r * 0.6)))
                value += step
            text = small.render(title, True, CLUSTER_DIM)
            face.blit(text, text.get_rect(center=(cx, cyy + r * 0.42)))
        digits = pygame.font.Font(default, int(radius * 0.6))
        readout = (int(rx + rw * 0.5), int(ry + rh * 0.22))  # at the top, between the dials

        # turn signal arrows, left and right of the speed digits
        size = radius * 0.32
        arrows = []
        for side in (-1, 1):
            tip_x = readout[0] + side * radius * 1.0
            base_x = tip_x - side * size
            y = readout[1]
            arrows.append([(tip_x, y), (base_x, y - size * 0.62), (base_x, y - size * 0.24),
                           (base_x - side * size * 0.8, y - size * 0.24), (base_x - side * size * 0.8, y + size * 0.24),
                           (base_x, y + size * 0.24), (base_x, y + size * 0.62)])

        # light on the glass: a faint band across the upper left of the screen
        glare = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        glare.fill((0, 0, 0, 0))
        band = [(screen.left, screen.top), (screen.left + screen.width * 0.42, screen.top),
                (screen.left + screen.width * 0.22, screen.bottom), (screen.left, screen.bottom)]
        pygame.draw.polygon(glare, (255, 255, 255, 10), band)
        # a soft shadow around the tablet on the picture
        pad = max(4, int(panel_h * 0.04))
        shadow = pygame.Surface((panel_w + 2 * pad, panel_h + 2 * pad), pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 0))
        for k in range(pad):
            pygame.draw.rect(shadow, (0, 0, 0, int(70 * (k + 1) / pad / pad) + 2),
                             shadow.get_rect().inflate(-2 * k, -2 * k), border_radius=corner + pad - k)
        return {'size': size, 'face': face, 'mask': mask, 'glare': glare, 'shadow': shadow, 'shadow_pad': pad,
                'origin': (x0, y0), 'dials': dials, 'digits': digits, 'readout': readout, 'status': status,
                'arrows': arrows,
                'clock': clock}

    @staticmethod
    def _draw_box(display, font, text, rect, background, foreground, alpha=220):
        surface = pygame.Surface(rect[2:])
        surface.set_alpha(alpha)
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
    escort = None
    green_lights = []
    recorder = None
    client = None
    audio = None
    driver_input = None
    sim_world = None
    async_settings = None
    ticker = None
    glasses = None
    rtr = None
    ndrt = None
    phone_cluster = None
    collision_sensor = None

    try:
        if args.glasses:
            sys.path.append(GLASSES_DIR)
            from tor_glasses import GlassesLink, resolve_host  # pylint: disable=import-error
            glasses = GlassesLink(resolve_host(args.glasses), args.glasses_port)
        intervention = Intervention(args.intervention_config, args.scenario)
        args.intervention = intervention.name  # logged with every trial
        args.test = intervention.test is not None and args.scenario != 0
        if args.test:
            args.pre_alert = intervention.test[1]
            args.test_alert_after = intervention.test[0]
            logging.info('Test run: pre-alert %.0f s after the start, TOR %.0f s after the pre-alert',
                         intervention.test[0], args.pre_alert)
        if intervention.lines and glasses is None:
            logging.warning('Intervention %s is shown only on the glasses (--glasses)', intervention.name)
        driver_input = WheelInput(args) if args.input == 'wheel' else KeyboardInput()
        client = connect_server(args.host, args.port)

        sim_world = client.get_world()
        if not sim_world.get_map().name.endswith(MAP_NAME):
            logging.info('Loading %s...', MAP_NAME)
            sim_world = client.load_world(MAP_NAME)
        # every run, since the server keeps the map (and trees hidden by a run before)
        trees = {tree.id for tree in sim_world.get_environment_objects(carla.CityObjectLabel.Vegetation)}
        sim_world.enable_environment_objects(trees, args.trees)
        if not args.trees:
            logging.info('Trees hidden (%d objects): quicker frames (--trees shows them)', len(trees))
        # A Traffic Manager of our own on a free port: the server still lists the one of the run
        # before (it lived in that process), and a synchronous tick that reaches it waits forever.
        traffic_manager = client.get_trafficmanager(_free_port())
        if args.sync:
            # The Traffic Manager drives traffic cars into the guardrails in asynchronous mode
            # when the server runs slowly (the monitor cameras): the client makes the steps
            # instead. Each step is as long as the time since the last one, so the simulation
            # keeps real time however many frames per second the computer draws.
            async_settings = sim_world.get_settings()
            async_settings.synchronous_mode = False  # also when a killed run left the server synchronous
            async_settings.fixed_delta_seconds = None
            settings = sim_world.get_settings()
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = None
            sim_world.apply_settings(settings)
            traffic_manager.set_synchronous_mode(True)
            ticker = SimTicker(sim_world)
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
        soften_engine_braking(world.player)

        # Put the vehicle on the figure-8 highway.
        carla_map = world.map
        anchor = carla_map.get_waypoint(carla_map.get_spawn_points()[START_SPAWN_INDEX].location)
        routes = {lane: build_loop_route(carla_map, lane_waypoint(anchor, lane)) for lane in LANES}
        route = routes[args.lane]
        logging.info('Figure-8 route, lane %d: %d waypoints, ~%.0f m',
                     args.lane, len(route), len(route) * ROUTE_RESOLUTION)
        green_lights = hold_loop_lights_green(sim_world, routes)
        scenario = make_scenario(args, client, sim_world, routes, route)
        start_index = test_start_index(scenario, route, args, intervention.test[0]) if args.test else 0
        start = route[start_index].transform
        start.location.z += 0.5
        world.player.set_transform(start)
        advance(sim_world, args)  # let the new position reach the client

        route_planner = GlobalRoutePlanner(carla_map, ROUTE_RESOLUTION)
        follower = LoopFollower(world.player, route, args.speed, carla_map, route_planner)
        # in scenarios 2 and 4 cars driving a lane that gets closed would run into the obstacle
        traffic_lanes = tuple(lane for lane in LANES if lane not in CLOSED_LANES.get(args.scenario, ()))
        traffic = spawn_traffic(sim_world, routes, args, traffic_manager, traffic_lanes, start_index)
        last_refresh = time.monotonic()
        latency = LatencyMeter()
        recorder = TrialRecorder(world, traffic, driver_input, args, started, args.post_window, latency)
        if args.lane in CLOSED_LANES.get(args.scenario, ()):
            logging.info('The car drives in lane %d, which the %s closes: the takeover includes '
                         'a lane change to the left', args.lane, SCENARIOS[args.scenario][0])
        road_signs = RoadSigns(sim_world)
        clearance = TrafficClearance(client, traffic, args.npc_speed)
        escort = EscortCars(client, sim_world, carla_map)
        # always on this PC too (with --glasses TORApp also plays them on the glasses)
        sound = AlertSound(not args.no_sound)
        if args.ndrt:
            from kakao_ndrt import KakaoNdrtLink  # next to this script
            ndrt = KakaoNdrtLink(args.ndrt, args.scenario, args.ndrt_port, None if args.no_log else recorder.dir,
                                 on_change=glasses.set_rtr if glasses is not None and intervention.live else None)
        elif args.scenario != 0:
            logging.warning('No NDRT laptop (--ndrt IP): no follow-up messages, no RtR summaries')
        if intervention.live and ndrt is None:
            logging.warning('Intervention NDRT_summary without the NDRT laptop (--ndrt): the fixed text only')
        elif intervention.live:
            rtr = ndrt  # the RtR summary of the notice draft
            if glasses is not None:
                glasses.set_rtr(rtr.status())  # TORApp shows its RtR button
                glasses.on_rtr_request = lambda: rtr.request('glasses')
        test_driver = None
        if args.test_driver:
            test_driver = TestDriver(world.player, routes, args.speed, carla_map, route_planner, scenario)
        if args.phone_cluster:
            from phone_cluster import PhoneCluster  # next to this script
            phone_cluster = PhoneCluster(args.phone_cluster_port)
        experiment = TakeoverExperiment(world, follower, driver_input, recorder, route, scenario, sound,
                                        auto_alert=not args.no_auto_alert, pre_alert=args.pre_alert,
                                        glasses=glasses, intervention=intervention, clearance=clearance,
                                        cruise_kmh=args.speed, escort=escort, rtr=rtr,
                                        test_alert_after=intervention.test[0] if args.test else None, ndrt=ndrt,
                                        phone_cluster=phone_cluster, test_driver=test_driver)
        fonts = (pygame.font.Font(pygame.font.get_default_font(), 40),
                 pygame.font.Font(pygame.font.get_default_font(), 24))

        advance(sim_world, args)
        collision_sensor, collisions = log_collisions(sim_world, world.player)
        run_start = time.monotonic()
        clock = pygame.time.Clock()
        while True:
            if args.duration and time.monotonic() - run_start >= args.duration:
                logging.info('--duration %.0f s: done, %d collision(s): %s', args.duration, len(collisions),
                             ', '.join(collisions) or 'none')
                return
            clock.tick_busy_loop(args.fps or 60)
            if ticker is not None:
                ticker.wait()
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
            for sign in scenario.take_signs():
                road_signs.add(sign)
            for sign in scenario.take_old_signs():
                road_signs.remove(sign)
            road_signs.tick(now, world.player.get_location())
            if traffic and now - last_refresh > NPC_PATH_REFRESH:
                last_refresh = now
                for npc in traffic:
                    npc.refresh_path()
            if ticker is not None:  # the next step, with this frame's controls, while this frame is drawn
                latency.sent(ticker.frame + 1, time.monotonic())
                ticker.start()
            world.tick(clock)
            world.render(display)
            experiment.render(display, fonts, now)
            pygame.display.flip()
            latency.shown(getattr(world.camera_manager, 'surface_image', None), time.monotonic())

    finally:
        if async_settings is not None:  # first: a server left in synchronous mode stops until someone ticks it
            try:
                ticker.wait()
            except RuntimeError:
                pass
            traffic_manager.set_synchronous_mode(False)
            sim_world.apply_settings(async_settings)
        if driver_input is not None:
            driver_input.close()  # releases the wheel's force feedback
        if audio is not None:
            audio.stop()
        if glasses is not None:
            glasses.close()
        if ndrt is not None:
            ndrt.close()
        if phone_cluster is not None:
            phone_cluster.close()
        if collision_sensor is not None:
            collision_sensor.stop()
            collision_sensor.destroy()
        if recorder is not None:
            recorder.close()
        if traffic:
            destroy_actors(client, [npc.actor for npc in traffic])
        if scenario is not None:
            scenario.cleanup(client)
        if escort is not None:
            escort.remove()
        release_lights(green_lights)
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
    argparser.add_argument('--fps', metavar='N', type=float, default=30.0,
                           help='most frames per second: the server runs in synchronous mode, one step per '
                                'frame, which keeps the traffic cars steady; each step is as long as the frame, '
                                'so the simulation keeps real time. 0 = asynchronous (default: 30)')
    argparser.add_argument('--filter', metavar='PATTERN', default=DEFAULT_VEHICLE,
                           help='vehicle blueprint (default: "%s")' % DEFAULT_VEHICLE)
    argparser.add_argument('--view', choices=['driver', 'windshield', 'chase'], default='driver',
                           help='start in the driver\'s seat, at the windshield (no steering wheel, wider view of '
                                'the road) or behind the car; TAB switches (default: driver)')
    argparser.add_argument('--speed', metavar='KMH', default=80.0, type=float,
                           help='autonomous target speed in km/h (default: 80)')
    argparser.add_argument('--gamma', default=2.2, type=float, help='camera gamma correction (default: 2.2)')
    argparser.add_argument('--lane', type=int, choices=LANES, default=DEFAULT_LANE,
                           help='lane to drive in, 1 = next to the median (default: %d)' % DEFAULT_LANE)
    argparser.add_argument('--vehicles', metavar='N', type=int, default=10,
                           help='number of traffic vehicles to place on the highway (default: 10; they '
                                'leave after the pre-alert)')
    argparser.add_argument('--npc-speed', metavar='KMH', type=float, default=70.0,
                           help='traffic vehicle speed in km/h (default: 70)')
    argparser.add_argument('--scenario', type=int, choices=sorted(SCENARIOS), default=1,
                           help='0 practice (manual driving only), 1 highway exit, 2 work zone after the '
                                'first lap, 3 sudden fog (default: 1)')
    argparser.add_argument('--tor-lead', metavar='SEC', type=float, default=None,
                           help='seconds before the event point at which the TOR comes; the pre-alert starts '
                                '--pre-alert seconds earlier (default: 5; scenarios 2 and 4: before the cones reach lane 3)')
    argparser.add_argument('--alert-lead', metavar='SEC', type=float, default=None,
                           help='seconds before the event point at which the pre-alert starts, instead of '
                                '--tor-lead + --pre-alert (scenario 3: the fog point, default 0)')
    argparser.add_argument('--intervention-config', metavar='FILE', default=INTERVENTION_CONFIG,
                           help='which intervention text the glasses show during the pre-alert '
                                '(default: intervention_config.json next to this script)')
    argparser.add_argument('--exit-at', metavar='METERS', type=float, default=None,
                           help='scenario 1: exit point, m from the start (default: end of the overpass; '
                                '-1: no exit point)')
    argparser.add_argument('--workzone-at', metavar='METERS', type=float, default=None,
                           help='scenario 2: where the work zone taper starts, m from the start '
                                '(default: %d)' % WORKZONE_AT)
    argparser.add_argument('--trees', action='store_true',
                           help='show the trees and bushes (hidden by default: about 26 -> 29 FPS, fewer slow frames)')
    argparser.add_argument('--accident-at', metavar='METERS', type=float, default=None,
                           help='scenario 4: where the crashed cars are, m from the start (default: %d)' % ACCIDENT_AT)
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
    argparser.add_argument('--glasses', metavar='PHONE_IP',
                           help='show the pre-alert and the TOR on Meta Ray-Ban Display glasses instead of the '
                                'screen, through TORApp on the phone at this IP (shown in the app); usb: over '
                                'the USB cable with USB tethering on in the phone; phone: the address in devices.json')
    argparser.add_argument('--glasses-port', metavar='P', type=int, default=5007,
                           help='UDP port of TORApp (default: 5007)')
    argparser.add_argument('--duration', metavar='SEC', type=float, default=None,
                           help='checking the scenarios: quit by itself after this many seconds')
    argparser.add_argument('--test-driver', action='store_true',
                           help='checking the scenarios: a scripted driver takes over 1 s after the TOR (TestDriver)')
    argparser.add_argument('--phone-cluster', action='store_true',
                           help='the gauges (throttle pedal, speed) on a phone instead of the monitor: open the '
                                'logged address in its browser (phone_cluster.py)')
    argparser.add_argument('--phone-cluster-port', metavar='P', type=int, default=5009,
                           help='HTTP port of the phone cluster page (default: 5009)')
    argparser.add_argument('--wireless', action='store_true',
                           help='over Wi-Fi: --glasses phone --ndrt laptop (addresses in devices.json), unless given')
    argparser.add_argument('--ndrt', metavar='IP[:PORT]', default=None,
                           help='the NDRT laptop running kakao_ndrt.py (follow-up messages, RtR summaries)')
    argparser.add_argument('--ndrt-port', '--rtr-port', dest='ndrt_port', metavar='P', type=int, default=5008,
                           help='kakao_ndrt.py\'s port on the NDRT laptop when --ndrt has none (default: 5008)')
    argparser.add_argument('--pc-sound', action='store_true',  # kept for old commands: the PC always plays them now
                           help='with --glasses: play the alert sounds on the PC too (default: only on the glasses)')
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
    if args.wireless:
        args.glasses = args.glasses or 'phone'
        args.ndrt = args.ndrt or 'laptop'
    try:
        args.glasses = device_address(args.glasses, 'phone', 'phone')
        args.ndrt = device_address(args.ndrt, 'laptop', 'ndrt_laptop')
    except RuntimeError as error:
        argparser.error(str(error))

    args.width, args.height = [int(x) for x in args.res.split('x')]
    if os.name == 'nt':
        try:
            # real pixels: without this, Windows display scaling would enlarge the window past the monitors
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
    # Options the stock World class expects.
    args.sync = args.fps > 0
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
