#!/usr/bin/env python

"""
Bluetooth delay of the earphones: a click on the Windows default output and, in the same frame, the
window white, every 2 s. Film the screen and the earphone (held close to the phone's microphone)
with a phone in slow motion; the delay is the time from the white frame to the click in the video.
Do it once with the earphones and once with a wired output (the monitor's speakers): the earphones'
own delay is the difference (the screen's and the phone's delays are in both and cancel).

    python _Experiment2/bt_latency.py              10 clicks
    python _Experiment2/bt_latency.py --count 20   20 clicks

The time each click is handed to the sound output is printed and logged (bt_latency_<time>.csv in
_Experiment2/claude_reply/): this is the time the experiment logs for its alert sounds too.
Esc or closing the window stops.
"""

import argparse
import array
import csv
import math
import os
import time

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame  # pylint: disable=wrong-import-position

HERE = os.path.dirname(os.path.abspath(__file__))


def click(rate, channels):
    """A 10 ms 2 kHz tone burst, sharp at its start."""
    n = int(rate * 0.010)
    samples = array.array('h')
    for i in range(n):
        value = int(28000 * math.sin(2.0 * math.pi * 2000.0 * i / rate) * (1.0 - i / n))
        samples.extend([value] * channels)
    return pygame.mixer.Sound(buffer=samples.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--count', type=int, default=10, help='clicks (default 10)')
    parser.add_argument('--every', type=float, default=2.0, help='s between clicks (default 2)')
    args = parser.parse_args()

    pygame.mixer.init(frequency=44100, size=-16, channels=2)   # as carla_base.AlertSound
    pygame.init()
    rate, _, channels = pygame.mixer.get_init()
    sound = click(rate, channels)
    screen = pygame.display.set_mode((640, 400))
    pygame.display.set_caption('bt_latency: click + white frame')
    out_dir = os.path.join(HERE, 'claude_reply')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, time.strftime('bt_latency_%y%m%d_%H%M%S.csv'))
    print('Sound driver %s; log %s' % (pygame.mixer.get_init(), path))
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['click', 'wall_time', 'perf_s'])
        next_at = time.perf_counter() + 1.5
        done = 0
        while done < args.count:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    done = args.count
            now = time.perf_counter()
            if done < args.count and now >= next_at:
                screen.fill((255, 255, 255))
                sound.play()
                sent = time.perf_counter()
                pygame.display.flip()
                done += 1
                writer.writerow([done, '%.3f' % time.time(), '%.4f' % sent])
                handle.flush()
                print('click %d at %.4f s' % (done, sent))
                pygame.time.wait(100)
                screen.fill((0, 0, 0))
                pygame.display.flip()
                next_at += args.every
            pygame.time.wait(1)
    pygame.quit()


if __name__ == '__main__':
    main()
