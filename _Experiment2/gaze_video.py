#!/usr/bin/env python

"""
The Glasses 2 scene video of a block with the gaze and the drive on it: gaze_video.mp4 in the block
folder, to watch what the driver looked at (the monitors, the mirrors, the glasses display) along
with what happened in the drive.

    python _Experiment2/gaze_video.py <block folder>                 the whole recording
    python _Experiment2/gaze_video.py <block folder> --from 180 --to 200    only block time 180-200 s
    python _Experiment2/gaze_video.py <block folder> --speed 0.5     slow motion (half speed)
    python _Experiment2/gaze_video.py <block folder> --ndrt-video mrbd-video/나미비아.mp4

On each frame:
    the gaze point (circle; its last 0.3 s as a trail), grey when the glasses report no gaze
    top left: block time, auto / manual, the TOR phase, the ego car's speed
    top right: the mirror glance going on (mirror_aoi.py's mirror_aoi_glances.csv, if it was run), or
    LEFT? / RIGHT? while the eyes are far to that side without a gaze point (mirror or not unknown)
    the glasses display (glasses condition, g2_display.json): its outline (solid) and the outline
    postprocess.py counts as on it (+15 %, dotted); "ON DISPLAY" while the gaze is inside that;
    inside the outline the NDRT video at the place it was playing (events.csv's "video ...: glasses
    at T s" reports; between two reports it runs on at 1x unless paused), dark while covered (SAGAT,
    TOR). The file: --ndrt-video, else the title the reports name ([...], logged since 2026-11-12),
    looked up in mrbd-video/ and mrbd-video/media/; none: the outline only
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
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from g2_block import Run  # noqa: E402  (the video / gaze / block time mapping)
from postprocess import DISPLAY_MARGIN, DISPLAY_PX, display_map, display_outline, inside as in_poly, ndrt_band  # noqa: E402

TRAIL_S = 0.3
EVENT_S = 3.0
KEEP = ('onset', 'freeze', 'answer', 'tor alert', 'first input', 'takeover', 'lane change', 'brake light',
        'lights on', 'tor obstacle', 'tor hazard', 'no_takeover', 'collision', 'conflict', 'emergency')
AOI_NAMES = {'left_mirror': 'LEFT mirror', 'rear_mirror': 'REAR mirror', 'right_mirror': 'RIGHT mirror',
             'lead_car': 'car ahead'}
DISPLAY_COLOUR = (80, 255, 80)
NDRT_ALPHA = 0.8        # the NDRT video over the scene (the real display is see-through)
NDRT_DIRS = (os.path.join(HERE, '..', 'mrbd-video'), os.path.join(HERE, '..', 'mrbd-video', 'media'))
VIDEO_EVENT = re.compile(r'^video (\w+): glasses at (\S+) s(, paused)?(, covered)?(?: \[(.+)\])?')
COLOURS = {'left': (0, 200, 255), 'rear': (255, 120, 0), 'right': (255, 0, 200)}


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


class NdrtTimeline(object):
    """Where the NDRT video was (s into it) and whether it was covered, at a PC time, from the
    glasses app's reports in events.csv. A report without a place (the block start's play: the app
    had not reported yet) takes it from the next report, counted back at 1x."""

    def __init__(self, rows):
        self.points = []   # (wall, position or None, paused, covered)
        self.title = None
        for r in rows:
            m = VIDEO_EVENT.match(r['what'])
            if not m:
                continue
            try:
                pos = float(m.group(2))
            except ValueError:
                pos = None
            self.points.append((float(r['wall_time']), pos, bool(m.group(3)), bool(m.group(4))))
            self.title = m.group(5) or self.title
        for k in range(len(self.points) - 2, -1, -1):
            w, pos, paused, covered = self.points[k]
            if pos is None and self.points[k + 1][1] is not None:
                nw, npos = self.points[k + 1][0], self.points[k + 1][1]
                self.points[k] = (w, max(npos - (0 if paused else nw - w), 0.0), paused, covered)
        self.walls = [p[0] for p in self.points]

    def at(self, wall):
        """(position s, covered) at wall, None before the first report or without a place."""
        k = bisect.bisect_right(self.walls, wall) - 1
        if k < 0 or self.points[k][1] is None:
            return None
        w, pos, paused, covered = self.points[k]
        return (pos if paused else pos + (wall - w)), covered


class NdrtVideo(object):
    """The NDRT video's frames, read on in order (a seek only on a jump), laid out as the glasses
    app does: 600 x 600, the video fitted in its width (object-fit: contain), from top px down
    (postprocess.ndrt_band: at the top from app v14 on, in the middle before)."""

    def __init__(self, cv2, np, path, top=None):
        self.cv2, self.np = cv2, np
        self.capture = cv2.VideoCapture(path)
        self.fps = self.capture.get(cv2.CAP_PROP_FPS) or 30.0
        vw, vh = self.capture.get(cv2.CAP_PROP_FRAME_WIDTH), self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        scale = min(600.0 / vw, 600.0 / vh)
        self.size = int(round(vw * scale)), int(round(vh * scale))
        self.offset = (600 - self.size[0]) // 2, (600 - self.size[1]) // 2 if top is None else int(round(top))
        self.index = -1
        self.frame = None

    def screen(self, position):
        """The 600 x 600 display at position s, and the mask of the video on it."""
        target = int(position * self.fps)
        if target < self.index or target > self.index + 3 * self.fps:
            self.capture.set(self.cv2.CAP_PROP_POS_FRAMES, target)
            self.index = target - 1
        while self.index < target:
            if not self.capture.grab():
                break
            self.index += 1
            if self.index == target:
                ok, frame = self.capture.retrieve()
                if ok:
                    self.frame = self.cv2.resize(frame, self.size, interpolation=self.cv2.INTER_AREA)
        screen = self.np.zeros((600, 600, 3), self.np.uint8)
        mask = self.np.zeros((600, 600), self.np.uint8)
        if self.frame is not None:
            x, y = self.offset
            screen[y:y + self.size[1], x:x + self.size[0]] = self.frame
            mask[y:y + self.size[1], x:x + self.size[0]] = 255
        return screen, mask


def find_ndrt_video(title):
    if not title:
        return None
    stem = os.path.splitext(title)[0]
    for folder in NDRT_DIRS:
        for name in (title, stem + '.mp4', stem + '_600p.mp4'):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return os.path.abspath(path)
    return None


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
    parser.add_argument('--ndrt-video', default=None,
                        help='the NDRT video file (default: the title in the video reports, in mrbd-video/)')
    parser.add_argument('--no-ndrt', action='store_true', help='the display outline only, no NDRT video in it')
    args = parser.parse_args()
    import cv2  # pylint: disable=import-outside-toplevel

    folder = os.path.abspath(args.folder)
    run = Run(folder)
    frames = read_csv(os.path.join(folder, 'frames.csv'))
    f_t = [float(r['t_sim']) for r in frames]
    event_rows = read_csv(os.path.join(folder, 'events.csv'))
    events = [(float(r['t_sim']), r['id'], r['what']) for r in event_rows
              if any(r['what'].startswith(k) or k in r['what'] for k in KEEP)]
    ndrt_timeline = NdrtTimeline(event_rows)
    windows = [(float(r['window_start']), float(r['window_end']), '%s %s: %s' % (
        r['id'], r['type'], AOI_NAMES.get(r['aoi'], r['aoi']))) for r in read_csv(os.path.join(folder, 'gaze_windows.csv'))]
    for r in read_csv(os.path.join(folder, 'tor_events.csv')):
        end = r.get('t_lane_change_start') or r.get('t_manual') or r['t_tor']
        windows.append((float(r['t_tor']), float(end) + 2.0, 'TOR: alert -> lane change (safe lane %s)' % r['safe_lane']))
    # the glances (mirror_aoi_glances.csv: frames joined with the hysteresis and short gaps bridged), not the
    # frames one by one: the label stays on for the whole glance
    glance_rows = [(float(r['start']), float(r['end']) + float(r['duration_s']) - (float(r['end']) - float(r['start'])),
                    r['mirror']) for r in read_csv(os.path.join(folder, 'mirror_aoi_glances.csv'))]

    capture = cv2.VideoCapture(run.video)
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    out_path = args.out or os.path.join(folder, 'gaze_video.mp4')
    writer = Writer(cv2, out_path, fps * args.speed, width, height)
    sx, sy = width, height
    font = cv2.FONT_HERSHEY_SIMPLEX
    import numpy as np  # pylint: disable=import-outside-toplevel
    outline = display_outline(folder)
    if outline:
        display_px = np.array([[int(x * sx), int(y * sy)] for x, y in outline], np.int32)
        margin_px = [(int(x * sx), int(y * sy)) for x, y in display_outline(folder, DISPLAY_MARGIN)]
    ndrt = None
    if outline and not args.no_ndrt:
        path = args.ndrt_video or find_ndrt_video(ndrt_timeline.title)
        if path and os.path.isfile(path):
            ndrt = NdrtVideo(cv2, np, path, ndrt_band(folder)[0])
            print('NDRT video: %s' % path)
            corners = [(0, 0), (DISPLAY_PX, 0), (DISPLAY_PX, DISPLAY_PX), (0, DISPLAY_PX)]
            to_gp = display_map(folder)
            warp = cv2.getPerspectiveTransform(np.float32(corners), np.float32(
                [(gx * sx, gy * sy) for gx, gy in (to_gp(x, y) for x, y in corners)]))
        else:
            print('NDRT video: none (%s): the outline only (--ndrt-video FILE)' % (
                path or ndrt_timeline.title or 'no title in the video reports'))

    def dotted(img, poly, colour):
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            n = max(int(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 / 8), 1)
            for k in range(0, n, 2):
                a, b = k / float(n), min(k + 1, n) / float(n)
                cv2.line(img, (int(x1 + (x2 - x1) * a), int(y1 + (y2 - y1) * a)),
                         (int(x1 + (x2 - x1) * b), int(y1 + (y2 - y1) * b)), colour, 1, cv2.LINE_AA)

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

        # the glasses display (drawn first: the gaze on top), the NDRT video in it
        state = ndrt_timeline.at(pc) if ndrt else None
        if state:
            position, covered = state
            if covered:
                cv2.fillPoly(frame, [display_px], (0, 0, 0))
                text(frame, 'NDRT covered', int(display_px[:, 0].mean()) - 60, int(display_px[:, 1].mean()), 0.5,
                     (160, 160, 160))
            else:
                screen, mask = ndrt.screen(position)
                screen = cv2.warpPerspective(screen, warp, (width, height))
                mask = cv2.warpPerspective(mask, warp, (width, height)) > 127
                frame[mask] = (frame[mask] * (1 - NDRT_ALPHA) + screen[mask] * NDRT_ALPHA).astype(np.uint8)
                text(frame, 'NDRT %d:%02d' % (position // 60, position % 60), int(display_px[:, 0].min()),
                     int(display_px[:, 1].min()) - 8, 0.45, DISPLAY_COLOUR)
        if outline:
            cv2.polylines(frame, [display_px], True, DISPLAY_COLOUR, 2, cv2.LINE_AA)
            dotted(frame, margin_px, DISPLAY_COLOUR)
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
            if outline and in_poly(outline, point[0] / 960.0, point[1] / 540.0, DISPLAY_MARGIN):
                text(frame, 'ON DISPLAY', width - 260, 60, 0.75, DISPLAY_COLOUR)
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
            # the mirror glance going on now (mirror_aoi_glances.csv)
            name = next((m for a, b, m in glance_rows if a <= t <= b), None)
            if name:
                label = '%s (MIRROR?)' % name.upper() if name.endswith('?') else 'ON %s MIRROR' % name.upper()
                text(frame, label, width - 260, 28, 0.75, COLOURS.get(name, (180, 180, 180)))
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
