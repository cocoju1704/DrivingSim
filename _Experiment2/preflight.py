#!/usr/bin/env python

"""
Before a block (preflight.bat): is everything on? Uses the launcher's last choices
(launcher_last.json: Glasses 2 address, video server, input), so run it with the same settings
the block will start with. Changes nothing anywhere; only looks.

    CARLA       the server answers on port 2000 (if not: the launcher starts it), its map
    wheel       a wheel / joystick is connected (input wheel)
    video       the mrbd-video server answers; the glasses app reports to it (every 2 s), its
                version (v13+) and screen; the videos on the server
    Glasses 2   the recording unit answers: battery, eye tracker, a calibration since power-on;
                the display calibration (g2_display.json) and its age
    SAGAT       for a while this serves the SAGAT page on port 5011 itself (as the block does) and
                waits for the tablet or the laptop (sagat_laptop.bat) to ask for it

    python _Experiment2/preflight.py            all of it
    python _Experiment2/preflight.py --wait 30  wait up to 30 s for the SAGAT tablet (default 15)
"""

from __future__ import print_function

import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OK, WARN, FAIL = 'OK  ', '주의', '실패'
results = []


def report(level, what, text):
    results.append(level)
    print('[%s] %-10s %s' % (level, what, text))


def load_choices():
    try:
        with open(os.path.join(HERE, 'launcher_last.json'), encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def get_json(url, timeout=6.0):
    context = ssl._create_unverified_context()  # pylint: disable=protected-access
    request = urllib.request.Request(url, headers={'User-Agent': 'drivingsim-preflight/1.0'})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode('utf-8') or '{}')


def check_carla():
    try:
        import carla
        client = carla.Client('127.0.0.1', 2000)
        client.set_timeout(5.0)
        version = client.get_server_version()
        town = client.get_world().get_map().name.split('/')[-1]
        report(OK, 'CARLA', '서버 실행 중 (%s, 맵 %s)' % (version, town))
    except Exception as error:  # pylint: disable=broad-except
        report(WARN, 'CARLA', '서버 응답 없음: 시작 창에서 Start하면 켜집니다 (%s)' % str(error).splitlines()[0][:60])


def check_wheel(choices):
    os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
    try:
        import pygame
        pygame.joystick.init()
        names = [pygame.joystick.Joystick(i).get_name() for i in range(pygame.joystick.get_count())]
    except Exception as error:  # pylint: disable=broad-except
        report(WARN, '핸들', '확인 못 함 (%s)' % error)
        return
    wanted = choices.get('input', 'auto')
    if names:
        report(OK, '핸들', ', '.join(names))
    elif wanted == 'wheel':
        report(FAIL, '핸들', '연결된 핸들이 없습니다 (입력이 wheel로 되어 있음): USB와 전원을 확인하세요')
    else:
        report(WARN, '핸들', '연결된 핸들이 없습니다 (입력 %s)' % wanted)


def check_video(choices):
    base = (choices.get('video') or '').strip().rstrip('/')
    if not base:
        if choices.get('video_server'):
            base = 'http://127.0.0.1:8080'
        else:
            report(WARN, '영상', '시작 창에 영상 서버 주소가 비어 있습니다: 영상 제어 없이 진행됩니다')
            return
    if not base.startswith(('http://', 'https://')):
        base = 'http://' + base
    try:
        state = get_json(base + '/api/state')
    except Exception as error:  # pylint: disable=broad-except
        report(FAIL, '영상 서버', '%s 응답 없음 (%s): 노트북의 서버를 켜세요' % (base, str(error)[:60]))
        return
    try:
        videos = get_json(base + '/api/videos')
        names = [v.get('name', v) if isinstance(v, dict) else v for v in videos]
    except Exception:  # pylint: disable=broad-except
        names = None
    report(OK, '영상 서버', '%s 응답함%s' % (base, ', 영상 %d개' % len(names) if names is not None else ''))

    received, now = state.get('received_ts'), state.get('server_ts')
    if not received:
        report(FAIL, '글래스 앱', '보고가 없습니다: 안경에서 영상 앱(웹앱)을 여세요')
        return
    age = (now - received) / 1000.0
    if age > 6:
        report(FAIL, '글래스 앱', '마지막 보고가 %.0f초 전: 앱이 닫혔거나 화면이 꺼졌습니다' % age)
        return
    version = int(state.get('v') or 0)
    screen = state.get('screen') or '?'
    title = state.get('title') or ''
    text = 'v%d, 화면 %s%s, %.0f초 전 보고' % (version, screen, (' (%s)' % title) if title else '', age)
    if version < 13:
        report(FAIL, '글래스 앱', text + ': v13이 아닙니다. Meta AI 앱에서 웹앱 연결을 끊었다가 다시 연결하세요')
    elif state.get('frozen'):
        report(WARN, '글래스 앱', text + ': 지난 블록의 정지 화면이 남아 있습니다 (시작하면 풀립니다)')
    else:
        report(OK, '글래스 앱', text)


def check_g2(choices):
    host = (choices.get('g2') or '').strip()
    if not host:
        report(WARN, 'Glasses 2', '시작 창에 주소가 비어 있습니다: 시선 데이터 없이 진행됩니다')
        return
    from g2_link import G2Link
    try:
        # G2Link's own request (the IPv6 link-local address in a URL) without its thread's work
        link = G2Link.__new__(G2Link)
        h = host
        if ':' in h:
            h = h.strip('[]')
            if '%' in h and '%25' not in h:
                h = h.replace('%', '%25')
            h = '[%s]' % h
        link._base = 'http://%s' % h  # pylint: disable=protected-access
        status = link._request('/api/system/status')  # pylint: disable=protected-access
    except Exception as error:  # pylint: disable=broad-except
        report(FAIL, 'Glasses 2', '%s 응답 없음 (%s): 녹화 장치 전원과 케이블을 확인하세요' % (host, str(error)[:60]))
        return
    battery = (status.get('sys_battery') or {}).get('level')
    eye = (status.get('sys_et') or {}).get('state', '?')
    storage = status.get('sys_storage') or {}
    free = storage.get('remaining')
    text = '배터리 %s%%, 시선 추적 %s' % (battery, eye)
    if free is not None:
        text += ', SD 남은 공간 %.1f GB' % (float(free) / 1e9)
    level = OK
    if battery is not None and float(battery) < 30:
        level, text = FAIL, text + ': 배터리를 바꾸세요 (블록 하나 약 15분)'
    elif battery is not None and float(battery) < 50:
        level = WARN
    report(level, 'Glasses 2', text)
    try:
        # calibrated_participant() warns (logging) when no calibration was made since power-on
        import logging
        warned = []
        catcher = logging.Handler()
        catcher.emit = lambda record: warned.append(record.getMessage())
        root = logging.getLogger()
        root.addHandler(catcher)
        root.propagate, handlers = False, root.handlers[:]
        root.handlers = [catcher]
        try:
            _, calibration = link.calibrated_participant()
        finally:
            root.handlers = handlers
        if calibration is None:
            report(FAIL, 'G2 보정', '보정이 없습니다: g2_calibrate.py를 먼저 하세요')
        elif warned:
            report(WARN, 'G2 보정', '켠 뒤로 보정이 없습니다 (예전 보정 %s를 씀): 참가자로 g2_calibrate.py를 하세요'
                   % calibration)
        else:
            report(OK, 'G2 보정', '이번에 켠 뒤 한 보정 %s' % calibration)
    except Exception as error:  # pylint: disable=broad-except
        report(WARN, 'G2 보정', '확인 못 함 (%s)' % str(error)[:60])
    path = os.path.join(HERE, 'g2_display.json')
    if os.path.exists(path):
        hours = (time.time() - os.path.getmtime(path)) / 3600.0
        report(OK if hours < 3 else WARN, '디스플레이 보정',
               'g2_display.json %s (%.0f시간 전)%s' % (
                   time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(path))), hours,
                   '' if hours < 3 else ': 오늘 이 참가자로 다시 하세요'))
    else:
        report(WARN, '디스플레이 보정', 'g2_display.json 없음')


def check_sagat(wait):
    from sagat_server import SagatServer, own_address, DEFAULT_PORT
    with socket.socket() as probe:
        try:
            probe.bind(('0.0.0.0', DEFAULT_PORT))
        except OSError:
            report(WARN, 'SAGAT', '포트 %d을 이미 쓰는 중 (블록이 실행 중?): 확인 못 함' % DEFAULT_PORT)
            return
    server = SagatServer(DEFAULT_PORT)
    url = 'http://%s:%d/' % (own_address() or '<이 PC IP>', DEFAULT_PORT)
    print('           SAGAT 화면을 %d초 동안 기다립니다: 태블릿/노트북에서 %s' % (wait, url))
    end = time.monotonic() + wait
    try:
        while time.monotonic() < end and not server.connected(within=2.0):
            time.sleep(0.3)
        if server.connected(within=2.0):
            report(OK, 'SAGAT', '태블릿(노트북) 연결됨 (%s)' % url)
        else:
            report(FAIL, 'SAGAT', '%d초 동안 요청이 없습니다: 노트북에서 sagat_laptop.bat을 실행하세요 (이 PC를 스스로 찾습니다), iPad라면 %s' % (wait, url))
    finally:
        server.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--wait', type=float, default=15.0, help='s to wait for the SAGAT tablet')
    args = parser.parse_args()
    choices = load_choices()
    print('시작 창의 마지막 설정: 참가자 %s, 블록 %s, 입력 %s, 영상 %s, Glasses 2 %s' % (
        choices.get('participant'), choices.get('block'), choices.get('input'), choices.get('video') or '-',
        choices.get('g2') or '-'))
    print()
    check_carla()
    check_wheel(choices)
    check_video(choices)
    check_g2(choices)
    check_sagat(args.wait)
    print()
    if FAIL in results:
        print('==> 실패 %d개: 위를 고친 뒤 다시 확인하세요.' % results.count(FAIL))
        return 1
    print('==> 시작해도 됩니다%s.' % (' (주의 %d개)' % results.count(WARN) if WARN in results else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
