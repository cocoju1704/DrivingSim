#!/usr/bin/env python

"""
Tobii Pro Glasses 2: aiming the scene camera. When the participant looks straight ahead at the middle
monitor, its centre should be in the middle of the scene camera; this shows how far off it is while the
glasses are adjusted (or the Glasses 2 re-mounted under the Ray-Ban Display).

    python g2_aim.py [HOST] [--aim-v=DEG]   HOST: devices.json's g2 when left out; DEG: AIM_V

The middle monitor shows a target like the calibration one at its centre; the right monitor (the last
one) shows the scene camera's latest frame with its centre cross and the target, and how many degrees
to turn the camera, every ~2 s (each update records the live stream for RECORD_S with g2_stream.py and
finds the target in the last frame), and how far each pupil is from where the eye tracker wants it
(TRACK_SPHERE: green within GREEN_MM, yellow within YELLOW_MM). Esc or q on either window: quit.

The seat position too, from the same frame: two more targets SIDE_MM left and right of the centre one
give the eyes' distance from the monitor (their angle apart in the scene camera), and the centre
target's angle in the camera plus the glasses' pitch (accelerometer: gravity) its height against the
eyes. Aimed at: SEAT_DISTANCE_MM (the distance at which a monitor fills the simulator's 43 degrees;
--distance=MM) within DISTANCE_TOL_MM, the eyes at the monitor centre's height within HEIGHT_TOL_MM.
The monitors' curve (CURVE_R_MM) is taken in: the side targets sit on it, a little nearer than the
centre one; the distance is the horizontal one, to the centre of the middle monitor. The pitch: the scene camera taken as level with the glasses' frame (the 2026-11-12
validations: the road target's angle in the camera and the pitch cancelled to 0-1.4 degrees with the
eyes at its height).
"""

from __future__ import print_function

import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import g2_validate as v

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD_S = 1.2
GOOD_DEG = 3.0          # within this both ways: aimed (--good=DEG)
# where the monitor centre should be, degrees from the camera's centre (- = up in the view): the camera
# must see both the monitors above and the glasses display below, so it points a little down
# (--aim-v=-6.5: the Ray-Ban Display's bottom edge is about 28 deg down, the monitor's top about 9.5 deg
# above its centre; the view is +-26 deg)
AIM_V = -6.5
# the eyes' place for the eye tracker (system status sys_track_sphere, mm in the glasses' frame) and its
# limits: green (good), yellow (still tracked); beyond: tracking breaks up
TRACK_SPHERE = {'left': (32.5, -27.0, -19.0), 'right': (-32.5, -27.0, -19.0)}
GREEN_MM, YELLOW_MM = 13.0, 16.0   # loosened 2026-11-12: under the Ray-Ban Display 10 mm is out of reach
# the fit check ("착용 OK"): the camera aimed and both pupils within FIT_MAX_MM of their place, the two
# within FIT_ASYM_MM of each other (more: the glasses sit tilted, one eye drops out); from the
# 2026-11-11 pilot, where the Ray-Ban Display under the Glasses 2 keeps them 12-13 mm out at best
FIT_MAX_MM = 16.0            # 2026-11-12: 13 -> 16 (the Ray-Ban Display keeps the eyes 12-15 mm out); the
FIT_ASYM_MM = 4.0            # validation tells whether the gaze is good enough (asymmetry 2 -> 4 mm)
# the seat position
MONITOR_WIDTH_MM = 708.0     # the 32 inch 16:9 monitors' panel width (along the curve)
CURVE_R_MM = 1800.0          # their curve: Leantech Blaze G32CF165, 1800R
SCREEN_FOV_DEG = 43.0        # the simulator's degrees per monitor (carla_base --screen-fov)


def on_curve(s):
    """(sideways, nearer) mm of a point s mm from the middle along the curved panel."""
    phi = s / CURVE_R_MM
    return CURVE_R_MM * math.sin(phi), CURVE_R_MM * (1.0 - math.cos(phi))


# where a monitor's edges are SCREEN_FOV_DEG apart, as the simulator draws it: ~926 mm
SEAT_DISTANCE_MM = (on_curve(MONITOR_WIDTH_MM / 2.0)[0] / math.tan(math.radians(SCREEN_FOV_DEG / 2.0))
                    + on_curve(MONITOR_WIDTH_MM / 2.0)[1])
DISTANCE_TOL_MM = 30.0
HEIGHT_TOL_MM = 30.0
SIDE_MM = 200.0              # the side targets, mm left and right of the centre one


def offset_deg(x, y):
    """Degrees of a scene point (0..1) from the camera's centre: (right +, down +)."""
    tx = math.tan(math.radians(v.SCENE_FOV_DEG[0] / 2.0))
    ty = math.tan(math.radians(v.SCENE_FOV_DEG[1] / 2.0))
    return math.degrees(math.atan((x - 0.5) * 2 * tx)), math.degrees(math.atan((y - 0.5) * 2 * ty))


def grab(host, work):
    """The last scene frame (BGR) and the target in it (px) or None."""
    import cv2
    out = os.path.join(work, 'clip')
    shutil.rmtree(out, ignore_errors=True)
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, 'g2_stream.py'), host, out],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(RECORD_S)
    try:
        proc.communicate(b'stop\n', timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    eyes = eye_offsets(os.path.join(out, 'g2_data.jsonl'))
    eyes['ac'] = accel(os.path.join(out, 'g2_data.jsonl'))
    capture = cv2.VideoCapture(os.path.join(out, 'g2_scene.ts'))
    frame = None
    while True:
        ok, f = capture.read()
        if not ok:
            break
        frame = f
    capture.release()
    if frame is None:
        return None, None, eyes
    return frame, v.find_targets(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2), eyes


def accel(path):
    """The median accelerometer reading (m/s2, x y z in the glasses' frame), or None."""
    values = []
    try:
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                if '"ac"' not in line:
                    continue
                try:
                    p = json.loads(line.partition(' ')[2])
                except ValueError:
                    continue
                if p.get('s') == 0:
                    values.append(p['ac'])
    except OSError:
        return None
    if len(values) < 5:
        return None
    return [sorted(a[i] for a in values)[len(values) // 2] for i in range(3)]


def pick_targets(found):
    """(centre, left, right) px of the three targets in a row (left / right None when not seen), or None."""
    if not found:
        return None
    best = found[:6]
    for a in best:
        for b in best:
            for c in best:
                if a[1] < b[1] < c[1] and abs(a[2] - b[2]) < 40 and abs(c[2] - b[2]) < 40 \
                        and abs((c[1] - b[1]) - (b[1] - a[1])) < 0.25 * (c[1] - a[1]):
                    return b[1:], a[1:], c[1:]
    return found[0][1:], None, None


def seat(centre, left, right, ac):
    """(distance mm, eye height above the monitor centre mm or None), or None without the side targets."""
    if left is None or right is None:
        return None
    w, h = v.SCENE_PX
    apart = v.angle((left[0] / w, left[1] / h), (right[0] / w, right[1] / h))
    sideways, nearer = on_curve(SIDE_MM)
    line = sideways / math.tan(math.radians(apart / 2.0))     # eye to the side targets' row, mm
    if ac is None:
        return line + nearer, None
    pitch = math.degrees(math.atan2(ac[2], -ac[1]))        # + = the glasses tilted up
    up = -offset_deg(centre[0] / w, centre[1] / h)[1]        # the centre target, degrees above the camera's axis
    elevation = math.radians(up + pitch)                     # the monitor centre seen from the eyes
    distance = line * math.cos(elevation) + nearer
    return distance, -distance * math.tan(elevation)


def eye_offsets(path):
    """Each eye's median pupil centre minus its TRACK_SPHERE centre (mm, x y z), or None."""
    pupils = {'left': [], 'right': []}
    try:
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                try:
                    p = json.loads(line.partition(' ')[2])
                except ValueError:
                    continue
                if 'pc' in p and p.get('s') == 0 and p.get('eye') in pupils:
                    pupils[p['eye']].append(p['pc'])
    except OSError:
        return {}
    out = {}
    for eye, pcs in list(pupils.items()):
        if len(pcs) >= 5:
            out[eye] = [sorted(c[i] for c in pcs)[len(pcs) // 2] - TRACK_SPHERE[eye][i] for i in range(3)]
    return out


def main():
    import tkinter as tk
    from PIL import Image, ImageTk
    import cv2
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    aim_v = next((float(a.split('=', 1)[1]) for a in sys.argv[1:] if a.startswith('--aim-v=')), AIM_V)
    global GOOD_DEG, SEAT_DISTANCE_MM
    SEAT_DISTANCE_MM = next((float(a.split('=', 1)[1]) for a in sys.argv[1:] if a.startswith('--distance=')),
                            SEAT_DISTANCE_MM)
    GOOD_DEG = next((float(a.split('=', 1)[1]) for a in sys.argv[1:] if a.startswith('--good=')), GOOD_DEG)
    with open(os.path.join(HERE, 'devices.json'), encoding='utf-8') as handle:
        host = args[0] if args else json.load(handle)['g2']
    mons = v.monitors()
    root = tk.Tk()
    root.withdraw()
    stop = threading.Event()

    def window(rect, colour):
        left, top, right, bottom = rect
        w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.geometry('%dx%d%+d%+d' % (right - left, bottom - top, left, top))
        w.attributes('-topmost', True)
        c = tk.Canvas(w, width=right - left, height=bottom - top, background=colour, highlightthickness=0)
        c.pack()
        for key in ('<Escape>', 'q'):
            w.bind(key, lambda e: stop.set())
        return c

    middle = mons[len(mons) // 2]
    target = window(middle, 'white')
    mw, mh = middle[2] - middle[0], middle[3] - middle[1]
    r = v.TARGET_DIAMETER * mw / 2.0
    for radius, colour in ((r, 'black'), (r * 23 / 43.0, 'white'), (r * 3 / 43.0, 'black')):
        target.create_oval(mw / 2 - radius, mh / 2 - radius, mw / 2 + radius, mh / 2 + radius, fill=colour,
                           outline=colour)
    side = SIDE_MM * mw / MONITOR_WIDTH_MM
    for x in (mw / 2 - side, mw / 2 + side):      # the side targets, for the distance
        for radius, colour in ((r, 'black'), (r * 23 / 43.0, 'white'), (r * 3 / 43.0, 'black')):
            target.create_oval(x - radius, mh / 2 - radius, x + radius, mh / 2 + radius, fill=colour, outline=colour)
    target.create_text(mw / 2, mh / 2 + r + 40, text='정면을 보고 가운데 고리를 보세요', font=('Malgun Gothic', 22))
    side = mons[-1] if len(mons) > 1 else middle
    view = window(side, '#111')
    sw, sh = side[2] - side[0], side[3] - side[1]
    scale = min(sw * 0.9 / v.SCENE_PX[0], sh * 0.62 / v.SCENE_PX[1])
    iw, ih = int(v.SCENE_PX[0] * scale), int(v.SCENE_PX[1] * scale)
    ix, iy = (sw - iw) // 2, 80
    view.winfo_toplevel().focus_force()
    updates = queue.Queue()
    work = tempfile.mkdtemp(prefix='g2_aim_')

    def worker():
        while not stop.is_set():
            try:
                updates.put(grab(host, work))
            except Exception as error:      # keep aiming going; show what failed
                updates.put((None, str(error), {}))

    threading.Thread(target=worker, daemon=True).start()
    photo = {}

    def show():
        if stop.is_set():
            root.destroy()
            return
        try:
            frame, found, eyes = updates.get_nowait()
        except queue.Empty:
            root.after(100, show)
            return
        view.delete('all')
        aimed = False
        ac = eyes.pop('ac', None)
        picked = pick_targets(found) if isinstance(found, list) else None
        found = picked[0] if picked else (found if isinstance(found, str) else None)
        details = []
        position = None
        if frame is None:
            view.create_text(sw / 2, sh / 2, fill='white', font=('Malgun Gothic', 28),
                             text='장면 영상이 없습니다' + (': %s' % found if isinstance(found, str) else ''))
        else:
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((iw, ih))
            photo['img'] = ImageTk.PhotoImage(image)
            view.create_image(ix, iy, anchor='nw', image=photo['img'])
            cx, cy = ix + iw / 2, iy + ih / 2
            view.create_line(cx - 40, cy, cx + 40, cy, fill='#3cf', width=3)
            view.create_line(cx, cy - 40, cx, cy + 40, fill='#3cf', width=3)
            if found:
                tx, ty = ix + found[0] * scale, iy + found[1] * scale
                view.create_oval(tx - 18, ty - 18, tx + 18, ty + 18, outline='#ff3', width=4)
                dx, dy = offset_deg(found[0] / v.SCENE_PX[0], found[1] / v.SCENE_PX[1])
                ey = dy - aim_v      # vertical error from the aim
                aimed = abs(dx) <= GOOD_DEG and abs(ey) <= GOOD_DEG
                # the target is up in the view: the camera points too low, tilt it up
                vertical = '%.0f° %s' % (abs(ey), '위로' if ey < 0 else '아래로')
                horizontal = '%.0f° %s' % (abs(dx), '왼쪽으로' if dx < 0 else '오른쪽으로')
                text = '맞음' if aimed else '카메라를 %s, %s' % (vertical, horizontal)
                view.create_text(sw / 2, iy + ih + 50, text=text, fill='#6f6' if aimed else '#ff6',
                                 font=('Malgun Gothic', 34, 'bold'))
                details.append(('모니터 중앙: 카메라 중심에서 가로 %+.1f°, 세로 %+.1f° (목표 가로 0°, 세로 %+.1f°, ±%.0f°)'
                                % (dx, dy, aim_v, GOOD_DEG), '#ccc'))
                for p in picked[1:]:
                    if p is not None:
                        px, py = ix + p[0] * scale, iy + p[1] * scale
                        view.create_oval(px - 12, py - 12, px + 12, py + 12, outline='#3cf', width=3)
                position = seat(picked[0], picked[1], picked[2], ac)
                print('target %+.1f deg horizontal, %+.1f deg vertical%s' % (dx, dy, '  aimed' if aimed else ''))
                sys.stdout.flush()
            else:
                view.create_text(sw / 2, iy + ih + 50, text='카메라에 타깃이 안 보입니다', fill='#f66',
                                 font=('Malgun Gothic', 34, 'bold'))
                print('target not seen')
                sys.stdout.flush()
        lines = []
        for eye, name in (('left', '왼쪽 눈'), ('right', '오른쪽 눈')):
            d = eyes.get(eye)
            if d is None:
                lines.append(('%s: 동공 안 잡힘' % name, '#f66'))
                continue
            dist = math.sqrt(sum(c * c for c in d))
            colour = '#6f6' if dist <= GREEN_MM else '#ff6' if dist <= YELLOW_MM else '#f66'
            # z: + = the eye nearer the glasses than its place; - = farther (the glasses too far out)
            depth = '안경을 %.0f mm %s' % (abs(d[2]), '얼굴 쪽으로' if d[2] < 0 else '바깥으로') if abs(d[2]) >= 2 else '앞뒤 맞음'
            lines.append(('%s: 기준에서 %.1f mm (%s, 위아래 %+.0f, 좌우 %+.0f mm)' % (name, dist, depth, d[1], d[0]), colour))
        placed = {'distance': None, 'height': None}
        if position is None:
            lines.append(('자리: 양옆 고리가 카메라에 안 보입니다' if found else '자리: -', '#f66' if found else '#ccc'))
        else:
            distance, height = position
            off = distance - SEAT_DISTANCE_MM
            placed['distance'] = abs(off) <= DISTANCE_TOL_MM
            move = '맞음' if placed['distance'] else '의자를 %.0f cm %s' % (abs(off) / 10.0, '앞으로' if off > 0 else '뒤로')
            lines.append(('거리: 눈에서 모니터까지 %.0f cm (목표 %.0f ± %.0f cm) → %s' % (
                distance / 10.0, SEAT_DISTANCE_MM / 10.0, DISTANCE_TOL_MM / 10.0, move),
                '#6f6' if placed['distance'] else '#ff6'))
            if height is None:
                lines.append(('높이: 가속도계 값이 없습니다', '#f66'))
            else:
                placed['height'] = abs(height) <= HEIGHT_TOL_MM
                move = '맞음' if placed['height'] else '눈을 %.0f cm %s' % (abs(height) / 10.0, '내리세요' if height > 0 else '올리세요')
                lines.append(('높이: 눈이 모니터 중앙보다 %.0f cm %s (± %.0f cm) → %s' % (
                    abs(height) / 10.0, '위' if height > 0 else '아래', HEIGHT_TOL_MM / 10.0, move),
                    '#6f6' if placed['height'] else '#ff6'))
            print('seat: distance %.0f mm (aim %.0f), eyes %s mm against the monitor centre'
                  % (distance, SEAT_DISTANCE_MM, '?' if height is None else '%+.0f' % height))
            sys.stdout.flush()
        for k, (text, colour) in enumerate(details + lines):
            view.create_text(sw / 2, iy + ih + 100 + 34 * k, text=text, fill=colour, font=('Malgun Gothic', 19))
        dists = {e: math.sqrt(sum(c * c for c in d)) for e, d in eyes.items()}
        problems = []
        if not aimed:
            problems.append('카메라 각도')
        if len(dists) < 2:
            problems.append('동공')
        else:
            if max(dists.values()) > FIT_MAX_MM:
                problems.append('눈과의 거리 (%.0f mm 이하)' % FIT_MAX_MM)
            if abs(dists['left'] - dists['right']) > FIT_ASYM_MM:
                problems.append('좌우 기울기 (차이 %.1f mm)' % abs(dists['left'] - dists['right']))
        if placed['distance'] is False:
            problems.append('거리')
        if placed['height'] is False:
            problems.append('높이')
        if position is None:
            problems.append('자리 측정')
        fit = not problems
        view.create_text(sw / 2, 20, anchor='n', font=('Malgun Gothic', 34, 'bold'),
                         fill='#6f6' if fit else '#f96',
                         text='착용 OK' if fit else '착용 확인: ' + ', '.join(problems))
        if eyes:
            print('eyes ' + ', '.join('%s %.1f mm (z %+.1f)' % (e, dists[e], d[2]) for e, d in sorted(eyes.items()))
                  + ('  fit ok' if fit else '  fit: ' + ', '.join(problems)))
            sys.stdout.flush()
        root.after(100, show)

    root.after(100, show)
    root.mainloop()
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
