#!/usr/bin/env python

"""
Tobii Pro Glasses 2: saves the glasses' live streams on this PC, so a block's gaze and scene video
are in its data folder without taking the SD card out (the SD card recording stays the backup).
G2Link (g2_link.py) runs this as its own process, so receiving the video (5 Mbit/s) never holds up
the experiment's frames; stopped by a line on its stdin (or Ctrl+C when run by hand):

    python g2_stream.py HOST OUT_DIR

Files in OUT_DIR:
  g2_scene.ts     the scene camera, as sent (MPEG-TS, H.264 960x540, 50 fps): each frame keeps
                  its PTS (90 kHz), the glasses' video clock
  g2_data.jsonl   every live data packet, one per line: "<PC time.time()> <packet JSON>". The packets
                  carry the glasses' clock ts (us): gaze gp / gp3, pupils pc / pd, gaze directions
                  gd, gyro gy, accelerometer ac, and the video sync pts {ts, pts} (video PTS -> ts)
  g2_sync.json    written at the end, from g2_data.jsonl: video PTS -> glasses ts (a line through the
                  pts packets) and glasses ts -> PC time (a line through the earliest arrivals: the
                  packets with the least network delay, 1 s bins)

Measured on this setup (cable, 30 s of screen flashes): PTS -> ts within 6 us; a flash on the monitor
was in the video 98-120 ms after the PC drew it (mean 108 ms: monitor, camera and glasses; constant),
the spread (sd 6 ms) one video frame. So a gaze sample, a video frame and the experiment's events
(frames.csv / events.csv wall_time, time.time()) line up to a video frame.

To line them up afterwards:
  ts of a video frame   = pts_to_ts[0] * PTS + pts_to_ts[1]
  PC time of a ts       = ts / 1e6 + ts_to_pc[0] * ts + ts_to_pc[1]
"""

from __future__ import print_function

import json
import os
import socket
import sys
import threading
import time

PORT = 49152          # the glasses' live stream port
KEEPALIVE_S = 1.0     # the glasses stop sending without a keep-alive for a few seconds


def address(host):
    """(family, sockaddr) for the glasses at host: IPv4, or IPv6 with its interface (fe80::...%15)."""
    host = host.strip('[]').replace('%25', '%')
    family, _, _, _, sockaddr = socket.getaddrinfo(host, PORT, 0, socket.SOCK_DGRAM)[0]
    return family, sockaddr


class Stream(object):
    def __init__(self, host, out_dir):
        self._family, self._sockaddr = address(host)
        self._out = out_dir
        self._stop = threading.Event()
        self._threads = []
        self.counts = {'data': 0, 'video_bytes': 0}

    def _socket(self):
        sock = socket.socket(self._family, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
        sock.settimeout(0.2)
        return sock

    def _keepalive(self, sock, kind):
        message = {'type': kind, 'key': 'abc-%s' % kind, 'op': 'start'}
        while not self._stop.is_set():
            try:
                sock.sendto(json.dumps(message).encode(), self._sockaddr)
            except OSError:
                pass  # the cable out for a moment: again in a second
            self._stop.wait(KEEPALIVE_S)
        message['op'] = 'stop'
        try:
            sock.sendto(json.dumps(message).encode(), self._sockaddr)
        except OSError:
            pass

    def _receive_data(self, sock):
        with open(os.path.join(self._out, 'g2_data.jsonl'), 'w', encoding='utf-8') as handle:
            while not self._stop.is_set():
                try:
                    packet = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    time.sleep(0.2)
                    continue
                handle.write('%.6f %s\n' % (time.time(), packet.decode('utf-8', 'replace').strip()))
                self.counts['data'] += 1

    def _receive_video(self, sock):
        with open(os.path.join(self._out, 'g2_scene.ts'), 'wb') as handle:
            while not self._stop.is_set():
                try:
                    packet = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    time.sleep(0.2)
                    continue
                handle.write(packet)
                self.counts['video_bytes'] += len(packet)

    def start(self):
        for kind, receive in (('live.data.unicast', self._receive_data), ('live.video.unicast', self._receive_video)):
            sock = self._socket()
            for target in (self._keepalive, receive):
                args = (sock, kind) if target == self._keepalive else (sock,)
                thread = threading.Thread(target=target, args=args, daemon=True)
                thread.start()
                self._threads.append(thread)

    def stop(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(2.0)
        sync = write_sync(self._out)
        return sync


def _line(points):
    """Least squares y = a x + b."""
    n = float(len(points))
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    a = sum((x - mx) * (y - my) for x, y in points) / sxx if sxx else 0.0
    return a, my - a * mx


def write_sync(out_dir):
    """g2_sync.json from g2_data.jsonl (see the module's doc); None without enough packets."""
    pts, earliest = [], {}
    try:
        with open(os.path.join(out_dir, 'g2_data.jsonl'), encoding='utf-8') as handle:
            for line in handle:
                pc, _, text = line.partition(' ')
                try:
                    packet = json.loads(text)
                except ValueError:
                    continue
                ts = packet.get('ts')
                if ts is None:
                    continue
                if 'pts' in packet:
                    pts.append((float(packet['pts']), float(ts)))
                offset = float(pc) - ts / 1e6
                second = int(ts // 1000000)
                if second not in earliest or offset < earliest[second][1]:
                    earliest[second] = (float(ts), offset)
    except OSError:
        return None
    if len(earliest) < 2:
        return None
    sync = {'ts_to_pc': _line(list(earliest.values())), 'seconds': len(earliest)}
    if len(pts) >= 2:
        sync['pts_to_ts'] = _line(pts)
        sync['pts_packets'] = len(pts)
    sync['use'] = ('ts of a video frame = pts_to_ts[0] * PTS + pts_to_ts[1]; '
                   'PC time.time() of a ts = ts / 1e6 + ts_to_pc[0] * ts + ts_to_pc[1]')
    with open(os.path.join(out_dir, 'g2_sync.json'), 'w', encoding='utf-8') as handle:
        json.dump(sync, handle, indent=1)
    return sync


def main():
    host, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    stream = Stream(host, out_dir)
    stream.start()
    try:
        sys.stdin.readline()  # G2Link writes a line (or closes the pipe) at the end of the block
    except KeyboardInterrupt:
        pass
    sync = stream.stop()
    print('Glasses 2 streams: %d data packets, %.1f MB video, sync %s' % (
        stream.counts['data'], stream.counts['video_bytes'] / 1e6, 'written' if sync else 'not written (no data)'))
    sys.stdout.flush()


if __name__ == '__main__':
    main()
