#!/usr/bin/env python

"""
Sends the gaze of a Tobii Pro Nano to takeover_experiment.py --gaze over UDP on this PC.

This runs apart from the experiment: the Tobii SDK (tobii-research on PyPI) only has a Windows
package for Python 3.10 and the CARLA client here is Python 3.12. Once, in the CARLA_0.9.16 folder:

    py -3.10 -m venv venv_gaze
    venv_gaze\\Scripts\\python -m pip install tobii-research

Before a participant: in Tobii Pro Eye Tracker Manager set the display area to the middle monitor
(its position relative to the tracker, also when the tracker is not attached to the monitor) and run
the calibration. Then, with or before the experiment:

    venv_gaze\\Scripts\\python _Experiment\\gaze_bridge.py

Without a tracker (any Python; a gaze that jumps around the middle of the monitor):

    python _Experiment\\gaze_bridge.py --mock

Packet: one JSON object per sample, x and y as shares of the monitor (0, 0 top left), null if invalid:
    {"t": device time in microseconds, "x": 0.5, "y": 0.4, "pupil": mm}
"""

from __future__ import print_function

import argparse
import json
import math
import random
import socket
import sys
import time

DEFAULT_PORT = 5010  # gaze_tracking.DEFAULT_PORT; that module needs numpy, this one nothing


def combine_eyes(gaze):
    """(x, y, pupil) of a Tobii gaze sample: the mean of the valid eyes; x, y are None if neither is."""
    points = []
    pupils = []
    for eye in ('left', 'right'):
        if gaze[eye + '_gaze_point_validity']:
            points.append(gaze[eye + '_gaze_point_on_display_area'])
        if gaze[eye + '_pupil_validity']:
            pupils.append(gaze[eye + '_pupil_diameter'])
    pupil = sum(pupils) / len(pupils) if pupils else None
    if not points:
        return None, None, pupil
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points), pupil


def run_tracker(send):
    import tobii_research  # only here: --mock runs without it
    trackers = tobii_research.find_all_eyetrackers()
    if not trackers:
        sys.exit('No eye tracker found. Is it plugged in and visible in Eye Tracker Manager?')
    tracker = trackers[0]
    print('Tracker: %s, serial %s, %g Hz' % (tracker.model, tracker.serial_number, tracker.get_gaze_output_frequency()))
    area = tracker.get_display_area()
    print('Display area: %.0f x %.0f mm (must be the middle monitor)' % (area.width, area.height))

    def on_gaze(gaze):
        x, y, pupil = combine_eyes(gaze)
        send(gaze['system_time_stamp'], x, y, pupil)

    tracker.subscribe_to(tobii_research.EYETRACKER_GAZE_DATA, on_gaze, as_dictionary=True)
    try:
        while True:
            time.sleep(1.0)
    finally:
        tracker.unsubscribe_from(tobii_research.EYETRACKER_GAZE_DATA, on_gaze)


def run_mock(send):
    """Holds a point for about a second, then jumps to the next, at 60 Hz."""
    x, y = 0.5, 0.45
    next_jump = 0.0
    while True:
        now = time.monotonic()
        if now >= next_jump:
            x, y = random.uniform(0.3, 0.7), 0.45 + random.uniform(-0.05, 0.05)
            next_jump = now + 1.0
        send(int(now * 1e6), x + random.gauss(0, 0.001), y + random.gauss(0, 0.001), 3.0 + 0.2 * math.sin(now))
        time.sleep(1.0 / 60.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='UDP port of --gaze (default: %d)' % DEFAULT_PORT)
    parser.add_argument('--mock', action='store_true', help='made-up gaze, no tracker needed')
    args = parser.parse_args()
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(stamp, x, y, pupil):
        packet = json.dumps({'t': stamp, 'x': x, 'y': y, 'pupil': pupil}).encode('utf-8')
        try:
            out.sendto(packet, ('127.0.0.1', args.port))
        except OSError:  # nobody listening yet
            pass

    print('Sending gaze to UDP port %d, Ctrl+C to stop' % args.port)
    try:
        (run_mock if args.mock else run_tracker)(send)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
