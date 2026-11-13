"""NDRT scene questions after each SAGAT stop: 4 frames, "이 장면이 영상에 나왔나요?".

Shown frames come from the shots that start 8-55 s before the stop (the frame ~1.5 s into the shot,
no subtitles); not-shown frames come from the same episode, outside the clip and outside the
episode's opening preview, in the same look (same country part, same channel logo). The number
shown per stop differs (1-3 of 4) so one answer does not give away the next.

    python make_items.py     cuts the clips into mrbd-video/media/ (if missing), writes <block>/<id>-<n>.jpg,
                             ndrt_items.json and sheet_<block>.jpg (green = shown, orange = not)

It checks every shown frame against the stop times in schedules/<block>.json and stops if one is
no longer 5-55 s before its stop (the schedule changed): pick new frames then.
"""
import json
import os
import random
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FF = os.path.join(ROOT, 'venv_carla', 'Lib', 'site-packages', 'imageio_ffmpeg', 'binaries',
                  'ffmpeg-win-x86_64-v9.0.2.exe')
SRC = os.path.join(ROOT, 'mrbd-video')                # the episodes
MEDIA = os.path.join(SRC, 'media')                    # the clips (served by mrbd-video/server.py)
FONT = ImageFont.truetype(r'C:\Windows\Fonts\malgun.ttf', 15)
BEFORE_STOP = (5.0, 55.0)   # s: a shown frame this long before its stop

# block: episode, clip file, clip start and length in the episode (s), per stop: shown frames (s into
# the clip), not-shown frames (s into the episode)
BLOCKS = {
    'A': ('중국', '중국_A.mp4', 0.0, 690, {
        'A-Q1': ([137.8, 157.5, 172.0], [2265.0]),
        'A-Q2': ([315.8], [2341.1, 2310.2, 1624.6]),
        'A-Q3': ([464.7, 487.5], [1689.3, 2458.8])}),
    'B': ('스위스러시아', '스위스러시아_B.mp4', 0.0, 690, {
        'B-Q1': ([96.1, 113.6], [779.1, 794.9]),
        'B-Q2': ([271.3], [903.6, 756.7, 1188.9]),
        'B-Q3': ([464.4, 468.8, 497.7], [1067.6])}),
    'C': ('스페인 남부', '스페인남부_C.mp4', 0.0, 690, {
        'C-Q1': ([220.1], [862.4, 899.9, 1076.1]),
        'C-Q2': ([365.0, 370.7, 382.5], [1100.3]),
        'C-Q3': ([465.0, 496.1], [945.1, 1242.2])}),
    # practice: a Galapagos nature documentary (its first minute is the preview)
    'P': ('연습주행', '연습주행_P.mp4', 0.0, 240, {
        'P-Q1': ([94.9, 111.2], [1033.0, 387.9])}),
}


def mmss(t):
    return '%d:%04.1f' % (t // 60, t % 60)


def main():
    rng = random.Random(20261112)
    items = {}
    bad = []
    for b, (ep, clip, start, length, stops) in BLOCKS.items():
        sched = json.load(open(os.path.join(HERE, '..', 'schedules', b + '.json'), encoding='utf-8'))
        stop_t = {e['id']: e['t'] for e in sched['events']}
        for qid, (shown, _) in stops.items():
            for t in shown:
                if not BEFORE_STOP[0] <= stop_t[qid] - t <= BEFORE_STOP[1]:
                    bad.append('%s: %.1f s is %.1f s before the stop (%.0f s)' % (qid, t, stop_t[qid] - t, stop_t[qid]))
        if bad:
            continue
        src = os.path.join(SRC, ep + '.mp4')
        dst = os.path.join(MEDIA, clip)
        if not os.path.exists(dst):
            subprocess.run([FF, '-loglevel', 'error', '-y', '-ss', str(start), '-i', src, '-t', str(length),
                            '-c', 'copy', '-avoid_negative_ts', 'make_zero', '-movflags', '+faststart', dst],
                           check=True)
        os.makedirs(os.path.join(HERE, b), exist_ok=True)
        items[b] = {'episode': ep + '.mp4', 'clip': clip, 'clip_start_s': start, 'clip_s': length, 'stops': {}}
        sheet = Image.new('RGB', (4 * 400, len(stops) * 245), 'black')
        d = ImageDraw.Draw(sheet)
        for r, (qid, (shown, foils)) in enumerate(stops.items()):
            qt = stop_t[qid]
            lst = [(True, t) for t in shown] + [(False, t) for t in foils]
            rng.shuffle(lst)
            rows = []
            for k, (is_shown, t) in enumerate(lst, 1):
                name = '%s-%d.jpg' % (qid, k)
                p = os.path.join(HERE, b, name)
                t_ep = start + t if is_shown else t
                subprocess.run([FF, '-loglevel', 'error', '-y', '-ss', '%.2f' % t_ep, '-i', src, '-frames:v', '1',
                                '-vf', 'scale=1280:720', '-q:v', '3', p], check=True)
                row = {'image': '%s/%s' % (b, name), 'shown': is_shown, 'episode_t': round(t_ep, 2)}
                if is_shown:
                    row['video_t'] = t
                    row['before_stop_s'] = round(qt - t, 1)
                rows.append(row)
                x, y = (k - 1) * 400, r * 245
                sheet.paste(Image.open(p).resize((392, 220)), (x + 4, y + 22))
                d.text((x + 6, y + 3), '%s-%d  %s  %s' % (qid, k, '나옴' if is_shown else '안 나옴', mmss(t_ep)),
                       fill='lime' if is_shown else 'orange', font=FONT)
            items[b]['stops'][qid] = {'stop_t': qt, 'items': rows}
        sheet.save(os.path.join(HERE, 'sheet_%s.jpg' % b), quality=88)
    if bad:
        sys.exit('Shown frames no longer before their stops (schedule changed?):\n  ' + '\n  '.join(bad))
    out = {'_comment': 'NDRT scene questions after each SAGAT stop (make_items.py): "이 장면이 영상에 나왔나요?" '
                       'yes/no + confidence. shown: from the clip, video_t s into it (the shot starts ~1.5 s '
                       'earlier), before_stop_s before the stop; not shown: same episode outside the clip and its '
                       'preview. episode_t: where the frame is in the episode. Asked in the listed order.'}
    out.update(items)
    with open(os.path.join(HERE, 'ndrt_items.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('ok: ' + ', '.join('%s %d' % (b, sum(len(s['items']) for s in v['stops'].values())) for b, v in items.items()))


if __name__ == '__main__':
    main()
