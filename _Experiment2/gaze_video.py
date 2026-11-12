#!/usr/bin/env python

"""
The Glasses 2 scene video of a block with the gaze and the drive on it: gaze_video.mp4 in the block
folder, to watch what the driver looked at (the monitors, the mirrors, the glasses display) along
with what happened in the drive.

    python _Experiment2/gaze_video.py <block folder>                 the whole recording
    python _Experiment2/gaze_video.py <block folder> --from 180 --to 200    only block time 180-200 s
    python _Experiment2/gaze_video.py <block folder> --speed 0.5     slow motion (half speed)

On each frame:
    the gaze point (circle; its last 0.3 s as a trail), grey when the glasses report no gaze
    top left: block time, auto / manual, the TOR phase, the ego car's speed
    top right: the mirror glance going on (mirror_gaze.py's mirror_glances.csv, if it was run)
    a band at the bottom: the event windows open now (S, SD, R, F: its mirror or the car ahead;
    the TOR), and the events of the last 3 s (onsets, the SAGAT freeze and answer, the TOR alert,
    the first input, the lane change)
Outside the block (before the start, after the end) the frame says so. Needs g2_scene.ts,
g2_data.jsonl and g2_sync.json (abc_experiment.py --g2 saves them).
"""

from __future__ import print_function

import argparse
import bisect
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mirror_gaze import Run  # noqa: E402  (the video / gaze / block time mapping)

TRAIL_S = 0.3
EVENT_S = 3.0
KEEP = ('onset', 'freeze', 'answer', 'tor alert', 'first input', 'takeover', 'lane change', 'brake light',
        'lights on', 'tor obstacle', 'tor hazard', 'no_takeover', 'collision', 'conflict', 'emergency')
AOI_NAMES = {'left_mirror': 'LEFT mirror', 'rear_mirror': 'REAR mirror', 'right_mirror': 'RIGHT mirror',
             'lead_car': 'car ahead'}
COLOURS = {'left': (0, 200, 255), 'rear': (255, 120, 0), 'right': (255, 0, 200)}


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


class Writer(object):
    """H.264 through ffmpeg (pip install imageio-ffmpeg: it brings its own ffmpeg); without it
    OpenCV's mp4v (its text smears on moving frames)."""

    def __init__(self, cv2, path, fps, width, height):
        self._pipe = self._cv = None
        try:
            import subprocess  # pylint: disable=import-outside-toplevel
            import imageio_ffmpeg  # pylint: disable=import-outside-toplevel
            self._pipe = subprocess.Popen(
                [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                 '-s', '%dx%d' % (width, height), '-r', '%.3f' % fps, '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast',
                 '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path], stdin=subprocess.PIPE)
        except ImportError:
            print('imageio-ffmpeg not installed: mp4v (pip install imageio-ffmpeg for H.264)')
            self._cv = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))

    def write(self, frame):
        if self._pipe:
            self._pipe.stdin.write(frame.tobytes())
        else:
            self._cv.write(frame)

    def release(self):
        if self._pipe:
            self._pipe.stdin.close()
            self._pipe.wait()
        else:
            self._cv.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('folder')
    parser.add_argument('--from', dest='t_from', type=float, default=None, help='block time to start at (s)')
    parser.add_argument('--to', dest='t_to', type=float, default=None, help='block time to end at (s)')
    parser.add_argument('--speed', type=float, default=1.0, help='playback speed (0.5: slow motion)')
    parser.add_argument('--out', default=None, help='default: <folder>/gaze_video.mp4')
    args = parser.parse_args()
    import cv2  # pylint: disable=import-outside-toplevel

    folder = os.path.abspath(args.folder)
    run = Run(folder)
    frames = read_csv(os.path.join(folder, 'frames.csv'))
    f_t = [float(r['t_sim']) for r in frames]
    events = [(float(r['t_sim']), r['id'], r['what']) for r in read_csv(os.path.join(folder, 'events.csv'))
              if any(r['what'].startswith(k) or k in r['what'] for k in KEEP)]
    windows = [(float(r['window_start']), float(r['window_end']), '%s %s: %s' % (
        r['id'], r['type'], AOI_NAMES.get(r['aoi'], r['aoi']))) for r in read_csv(os.path.join(folder, 'gaze_windows.csv'))]
    for r in read_csv(os.path.join(folder, 'tor_events.csv')):
        end = r.get('t_lane_change_start') or r.get('t_manual') or r['t_tor']
        windows.append((float(r['t_tor']), float(end) + 2.0, 'TOR: alert -> lane change (safe lane %s)' % r['safe_lane']))
    # the glances (mirror_glances.csv: frames joined with the hysteresis and short gaps bridged), not the
    # frames one by one: the label stays on for the whole glance
    glance_rows = [(float(r['start']), float(r['end']) + float(r['duration_s']) - (float(r['end']) - float(r['start'])),
                    r['mirror']) for r in read_csv(os.path.join(folder, 'mirror_glances.csv'))]

    capture = cv2.VideoCapture(run.video)
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    out_path = args.out or os.path.join(folder, 'gaze_video.mp4')
    writer = Writer(cv2, out_path, fps * args.speed, width, height)
    sx, sy = width, height
    font = cv2.FONT_HERSHEY_SIMPLEX

    def text(img, s, x, y, scale=0.55, colour=(255, 255, 255)):
        # the outline as thin text around it: in OpenCV 5 thicker text is also wider, a thick
        # black copy underneath would stick out to the right
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 2), (2, 0), (-2, 0), (0, -2)):
            cv2.putText(img, s, (x + dx, y + dy), font, scale, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(img, s, (x, y), font, scale, colour, 1, cv2.LINE_AA)

    index = written = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        msec = capture.get(cv2.CAP_PROP_POS_MSEC)
        ts = run.ts_of_msec(msec)
        pc = run.pc_of_ts(ts)
        inside = run.in_block(pc)
        t = run.sim_of_pc(pc) if inside else None
        if (args.t_from is not None and (t is None or t < args.t_from)) or \
                (args.t_to is not None and (t is None or t > args.t_to)):
            index += 1
            if args.t_to is not None and t is not None and t > args.t_to:
                break
            continue

        # gaze: trail and point
        i0 = bisect.bisect_left(run.gaze_ts, ts - TRAIL_S * 1e6)
        i1 = bisect.bisect_right(run.gaze_ts, ts + 0.02e6)
        trail = [(int(g[1] * sx), int(g[2] * sy)) for g in run.gaze[i0:i1]]
        for a, b in zip(trail, trail[1:]):
            cv2.line(frame, a, b, (0, 255, 255), 1, cv2.LINE_AA)
        point = run.gaze_at(ts)
        if point is not None:
            p = (int(point[0] * sx / 960.0), int(point[1] * sy / 540.0))
            cv2.circle(frame, p, 14, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.circle(frame, p, 14, (0, 0, 255), 2, cv2.LINE_AA)
            cv2.circle(frame, p, 2, (0, 0, 255), -1)
        else:
            text(frame, 'no gaze', 10, height - 70, 0.5, (160, 160, 160))

        # drive state
        if t is None:
            text(frame, 'outside the block', 10, 24, 0.6, (160, 160, 160))
        else:
            k = min(max(bisect.bisect_right(f_t, t) - 1, 0), len(frames) - 1)
            r = frames[k]
            phase = (' | TOR ' + r['tor_phase']) if r.get('tor_phase') else ''
            text(frame, 't %.1f s | %s%s | %.0f km/h' % (t, r['mode'], phase, float(r['speed_kmh'])), 10, 24, 0.6)
            # the mirror glance going on now (mirror_glances.csv)
            name = next((m for a, b, m in glance_rows if a <= t <= b), None)
            if name:
                text(frame, 'ON %s MIRROR' % name.upper(), width - 260, 28, 0.75, COLOURS.get(name, (255, 255, 255)))
            # windows open now, events of the last few seconds
            lines = [('window  ' + label, (120, 255, 120)) for a, b, label in windows if a <= t <= b]
            lines += [('%.1f  %s %s' % (et, eid if eid != '-' else '', what[:70]), (255, 255, 255))
                      for et, eid, what in events if t - EVENT_S <= et <= t]
            y = height - 12 - 22 * (len(lines) - 1)
            for s, colour in lines:
                text(frame, s, 10, y, 0.5, colour)
                y += 22
        writer.write(frame)
        written += 1
        index += 1
        if index % 500 == 0:
            print('  %d of %d frames' % (index, total), end='\r')
    writer.release()
    print('%d frames written: %s' % (written, out_path))


if __name__ == '__main__':
    main()
