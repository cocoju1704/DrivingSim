#!/usr/bin/env python

"""
Where the bezel markers (mirror_markers.py, marker_plan.jpg) are in the experiment window's pixels:
mirror_markers/bezel_screen.json, which mirror_aoi.py reads to put the gaze in the monitors' pixels
(the mirrors are drawn there: carla_base._mirror_rect). Again whenever a marker or a side monitor was
moved.

    python _Experiment2/mirror_register.py                 show the markers and record (Enter starts)
    python _Experiment2/mirror_register.py --analyse DIR   from a recording again

The side monitors show SCREEN markers (ids 30-35 left, 40-45 right) at known pixels on grey; the
participant wears the Glasses 2 and looks ahead, then turns the head left and right (the outer bezel
markers come into the scene camera's view only then) while the live streams are saved
(Data/test/register_<time>/). In each frame where a bezel marker and at least two screen markers of
its monitor are found, a homography from the screen markers NEAREST to it (the monitors are curved,
1800R: about 35 mm out of plane across one, so a fit over the whole monitor would bend the far
ones) puts the bezel marker's corners in window pixels; the median over the frames is kept. Its
side in pixels is checked against MARKER_MM at the panel's pixel pitch.

Window pixels: the experiment window over the three monitors, 5760 x 1080 (left monitor x 0-1919,
middle 1920-3839, right 3840-5759); a bezel marker lies outside its monitor's pixels (y < 0, y >
1080 or beyond its side edge).
"""

from __future__ import print_function

import argparse
import base64
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mirror_markers as mm  # noqa: E402

OUT_FILE = os.path.join(mm.OUT_DIR, 'bezel_screen.json')
SCREEN_IDS = {'left': (30, 31, 32, 33, 34, 35), 'right': (40, 41, 42, 43, 44, 45)}
SCREEN_X = (0.10, 0.50, 0.90)       # the screen markers' centres, of the monitor's width / height
SCREEN_Y = (0.16, 0.84)
SCREEN_SIDE_PX = 170                # the black square (about 63 mm on the 32 inch panel)
SCREEN_BORDER_PX = 28               # its white border
BACKGROUND = '#8c8c8c'              # grey: the camera exposes for it, not for a white screen
PANEL_MM_PER_PX = 708.0 / 1920      # the 32 inch panel's pixel pitch (g2_aim.MONITOR_WIDTH_MM)
NEAREST = 3                         # screen markers per homography (at least 2)
MAX_FIT_PX = 12.0                   # window px: the screen markers' RMS error in the homography
MIN_FRAMES = 5
STRIDE = 5                          # every 5th frame (10 a second): the detector takes ~0.3 s a frame
STEPS = [('정면 가운데 점을 보세요', 4.0),
         ('고개를 천천히 왼쪽으로 돌려 왼쪽 모니터 바깥쪽을 보세요', 4.0),
         ('정면', 2.0),
         ('고개를 천천히 오른쪽으로 돌려 오른쪽 모니터 바깥쪽을 보세요', 4.0),
         ('정면', 2.0)]


def screen_markers():
    """{id: (monitor, 4 x 2 window px corners: tl, tr, br, bl)} of the screen markers."""
    out = {}
    for monitor, ids in SCREEN_IDS.items():
        x0 = mm.MONITOR_INDEX[monitor] * mm.MONITOR_PX[0]
        k = 0
        for fy in SCREEN_Y:
            for fx in SCREEN_X:
                cx, cy = x0 + fx * mm.MONITOR_PX[0], fy * mm.MONITOR_PX[1]
                h = SCREEN_SIDE_PX / 2.0
                out[ids[k]] = (monitor, [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)])
                k += 1
    return out


def record(out_dir):
    import cv2  # pylint: disable=import-outside-toplevel
    import tkinter as tk  # pylint: disable=import-outside-toplevel
    import g2_validate as v  # pylint: disable=import-outside-toplevel
    with open(os.path.join(HERE, 'devices.json'), encoding='utf-8') as handle:
        host = json.load(handle)['g2']
    screen = v.Screen()
    if len(screen.monitors) != 3:
        print('3 monitors needed, %d found' % len(screen.monitors))
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, mm.DICTIONARY))
    images = {}    # the PhotoImages (Tk keeps none of its own)
    for mid in sum(SCREEN_IDS.values(), ()):
        marker = cv2.aruco.generateImageMarker(dictionary, mid, SCREEN_SIDE_PX, borderBits=1)
        marker = cv2.copyMakeBorder(marker, SCREEN_BORDER_PX, SCREEN_BORDER_PX, SCREEN_BORDER_PX, SCREEN_BORDER_PX,
                                    cv2.BORDER_CONSTANT, value=255)
        ok, png = cv2.imencode('.png', marker)
        images[mid] = png.tobytes()
    markers = screen_markers()
    state = {}

    def show(caption):
        def draw():
            if 'photos' not in state:
                state['photos'] = {mid: tk.PhotoImage(data=base64.b64encode(png).decode('ascii')) for mid, png in images.items()}
            for k, (canvas, (left, top, right, bottom)) in enumerate(zip(screen.canvases, screen.monitors)):
                canvas.delete('all')
                canvas.configure(background=BACKGROUND)
                for mid, (monitor, corners) in markers.items():
                    if mm.MONITOR_INDEX[monitor] == k:
                        cx = sum(c[0] for c in corners) / 4.0 - k * mm.MONITOR_PX[0]
                        cy = sum(c[1] for c in corners) / 4.0
                        canvas.create_image(cx, cy, image=state['photos'][mid])
                if k == 1:
                    x, y = (right - left) / 2.0, (bottom - top) / 2.0
                    for radius, colour in ((40, 'black'), (21, 'white'), (3, 'black')):
                        canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=colour, outline=colour)
                    canvas.create_text(x, y + 90, text=caption, fill='black', font=('Malgun Gothic', 26, 'bold'))
        screen._call(draw)  # pylint: disable=protected-access

    result = {}

    def steps():
        try:
            screen.message('미러 마커 등록', '글래스를 쓰고 앉으세요. 화면 안내대로 정면을 보다가 고개를 좌우로 돌립니다 (약 16초)\n'
                                           'Enter: 시작   Esc: 그만')
            if not screen.wait_enter():
                return
            show('스트림 연결 중...')
            result['stream'] = subprocess.Popen(
                [sys.executable, os.path.join(HERE, 'g2_stream.py'), host, out_dir], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            if not screen.wait(2.5):
                return
            data = os.path.join(out_dir, 'g2_data.jsonl')
            if not os.path.exists(data) or os.path.getsize(data) == 0:
                print('No data from the Glasses 2 (%s): on, and on the cable?' % host)
                screen.message('글래스 데이터가 없습니다', '글래스가 켜져 있고 케이블이 연결됐는지 확인하세요\nEnter: 닫기')
                screen.wait_enter()
                return
            for caption, seconds in STEPS:
                show(caption)
                if not screen.wait(seconds):
                    return
            result['done'] = True
            screen.message('끝', '분석 중...')
        finally:
            screen.close()

    worker = threading.Thread(target=steps, daemon=True)
    worker.start()
    screen.root.mainloop()
    worker.join(10)
    stream = result.get('stream')
    if stream:
        output, _ = stream.communicate('stop\n', timeout=20.0)
        print(output.strip())
    return result.get('done', False) and os.path.exists(os.path.join(out_dir, 'g2_sync.json'))


def centre(c):
    return sum(p[0] for p in c) / 4.0, sum(p[1] for p in c) / 4.0


def analyse(folder):
    import cv2  # pylint: disable=import-outside-toplevel
    import numpy as np  # pylint: disable=import-outside-toplevel

    screen = screen_markers()
    bezel = {spec[0]: (name, spec[1]) for name, spec in mm.MARKERS.items()}    # id -> (name, monitor)
    detector = mm.Detector(set(screen) | set(bezel))
    capture = cv2.VideoCapture(os.path.join(folder, 'g2_scene.ts'))
    samples = {name: [] for name, _ in bezel.values()}
    fits = []
    frames = 0
    best = {}      # monitor -> (number of markers, frame) for the picture
    index = -1
    while True:
        index += 1
        if index % STRIDE:
            if not capture.grab():
                break
            continue
        ok, frame = capture.read()
        if not ok:
            break
        frames += 1
        found = detector(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        for monitor in ('left', 'right'):
            on_screen = [(mid, c) for mid, c in found.items() if mid in screen and screen[mid][0] == monitor]
            if len(on_screen) < 2:
                continue
            here = [(mid, c) for mid, c in found.items() if mid in bezel and bezel[mid][1] == monitor]
            if here and len(here) + len(on_screen) > best.get(monitor, (0,))[0]:
                best[monitor] = (len(here) + len(on_screen), frame.copy(), found)
            for mid, c in here:
                bx, by = centre(c)
                near = sorted(on_screen, key=lambda s: math.hypot(centre(s[1])[0] - bx, centre(s[1])[1] - by))[:NEAREST]
                src = np.float32([p for _, sc in near for p in sc])
                dst = np.float32([p for sid, _ in near for p in screen[sid][1]])
                h, _ = cv2.findHomography(src, dst, 0)
                if h is None:
                    continue
                back = cv2.perspectiveTransform(src.reshape(-1, 1, 2), h).reshape(-1, 2)
                rms = float(np.sqrt(np.mean(np.sum((back - dst) ** 2, axis=1))))
                fits.append(rms)
                if rms > MAX_FIT_PX:
                    continue
                corners = cv2.perspectiveTransform(np.float32(c).reshape(-1, 1, 2), h).reshape(-1, 2)
                samples[bezel[mid][0]].append(corners)

    result = {}
    expected = mm.MARKER_MM / PANEL_MM_PER_PX
    print('\nframes %d, homography fits %d (screen markers RMS median %.1f window px)' % (
        frames, len(fits), sorted(fits)[len(fits) // 2] if fits else float('nan')))
    print('%-4s %-6s %7s %9s %8s   %s' % ('name', 'monitor', 'frames', 'spread px', 'side px', 'centre (window px)'))
    for name, (mid, monitor, where) in mm.MARKERS.items():
        s = samples[name]
        if len(s) < MIN_FRAMES:
            print('%-4s %-6s %7d   not enough frames: not registered' % (name, monitor, len(s)))
            continue
        arr = np.array(s)
        med = np.median(arr, axis=0)
        dist = np.linalg.norm(arr.mean(axis=1) - med.mean(axis=0), axis=1)
        mad = float(np.median(dist))
        keep = arr[dist <= max(15.0, 3.0 * mad)]
        med = np.median(keep, axis=0)
        spread = float(np.median(np.linalg.norm(keep.mean(axis=1) - med.mean(axis=0), axis=1)))
        side = float(np.mean([np.linalg.norm(med[i] - med[(i + 1) % 4]) for i in range(4)]))
        result[name] = {'id': mid, 'monitor': monitor, 'corners_px': [[round(float(x), 1), round(float(y), 1)] for x, y in med],
                        'frames': int(len(keep)), 'spread_px': round(spread, 1), 'side_px': round(side, 1)}
        cx, cy = med.mean(axis=0)
        flag = '' if abs(side - expected) < 0.2 * expected else '   <- side off (expected %.0f px)' % expected
        print('%-4s %-6s %7d %9.1f %8.1f   (%.0f, %.0f)%s' % (name, monitor, len(keep), spread, side, cx, cy, flag))
    print('expected side: %.0f px (%d mm at %.3f mm/px)' % (expected, mm.MARKER_MM, PANEL_MM_PER_PX))

    out = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'recording': os.path.basename(folder),
           'window_px': [mm.MONITOR_PX[0] * 3, mm.MONITOR_PX[1]], 'monitor_px': list(mm.MONITOR_PX),
           'monitor_index': mm.MONITOR_INDEX, 'markers': result,
           'note': 'bezel markers in the experiment window px (5760 x 1080, left monitor x 0-1919); '
                   'corners tl, tr, br, bl of the black square; mirror_register.py'}
    with open(os.path.join(folder, 'bezel_screen.json'), 'w', encoding='utf-8') as handle:
        json.dump(out, handle, indent=1)
    if result:
        shutil.copy(os.path.join(folder, 'bezel_screen.json'), OUT_FILE)
        print('written: %s' % OUT_FILE)

    # pictures: the frame with the most markers per monitor, the registered markers drawn back into it
    for monitor, (_, frame, found) in best.items():
        for mid, c in found.items():
            colour = (0, 200, 0) if mid in screen else (0, 0, 255)
            cv2.polylines(frame, [np.int32(c)], True, colour, 2, cv2.LINE_AA)
            label = bezel[mid][0] if mid in bezel else str(mid)
            cv2.putText(frame, label, tuple(int(v) for v in c[0] - (0, 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1,
                        cv2.LINE_AA)
        cv2.imwrite(os.path.join(folder, 'register_%s.jpg' % monitor), frame)
    # the window with the registered markers (1/4 scale)
    q = 0.25
    pad = 150
    canvas = np.full((int((mm.MONITOR_PX[1] + 2 * pad) * q), int((3 * mm.MONITOR_PX[0] + 2 * pad) * q), 3), 40, np.uint8)
    for k in range(3):
        cv2.rectangle(canvas, (int((pad + k * mm.MONITOR_PX[0]) * q), int(pad * q)),
                      (int((pad + (k + 1) * mm.MONITOR_PX[0] - 4) * q), int((pad + mm.MONITOR_PX[1]) * q)),
                      (200, 200, 200), 1)
    for name, r in result.items():
        pts = np.int32([[(x + pad) * q, (y + pad) * q] for x, y in r['corners_px']])
        cv2.fillPoly(canvas, [pts], (0, 0, 255) if r['monitor'] == 'left' else (255, 120, 0))
        cv2.putText(canvas, name, (int(pts[:, 0].min()), int(pts[:, 1].min()) - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (255, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(folder, 'register_window.png'), canvas)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--analyse', metavar='DIR', help='from a recording again')
    args = parser.parse_args()
    if args.analyse:
        analyse(os.path.abspath(args.analyse))
        return
    out_dir = os.path.join(HERE, 'Data', 'test', 'register_' + time.strftime('%y%m%d_%H%M%S'))
    os.makedirs(out_dir)
    if record(out_dir):
        analyse(out_dir)
    else:
        print('No recording to analyse (%s)' % out_dir)


if __name__ == '__main__':
    main()
