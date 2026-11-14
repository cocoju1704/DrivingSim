#!/usr/bin/env python

"""
Before a block (menu.py: 사전 점검): is everything on? Uses the launcher's last choices
(launcher_last.json: Glasses 2 address, video server, input), so run it with the same settings
the block will start with. Changes nothing anywhere; only looks.

    CARLA       the server answers on port 2000 (if not: the launcher starts it), its map
    wheel       a wheel / joystick is connected (input wheel)
    sound       the Windows default output is the earphones (devices.json "earphones": part of their
                name); the car sound, the TOR alert and the HUD video sound all play on it
    video       the mrbd-video server answers; the glasses app reports to it (every 2 s), its
                version (v13+) and screen; the videos on the server. In the phone condition (the
                block's, as the launcher plans it): the phone app (mrbd-video/phone_app) instead
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
import shutil
import socket
import ssl
import sys
import time
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OK, WARN, FAIL = 'OK', '주의', '실패'
results = []
NAME_COLS = 16          # display columns of the item's name (Hangul counts 2)


class Style(object):
    """ANSI colours on the console (Windows 10 cmd: virtual terminal mode switched on), none when the
    output is not a console or NO_COLOR is set."""

    def __init__(self):
        self.on = sys.stdout.isatty() and not os.environ.get('NO_COLOR') and self._enable()

    @staticmethod
    def _enable():
        if os.name != 'nt':
            return True
        try:
            import ctypes  # pylint: disable=import-outside-toplevel
            kernel = ctypes.windll.kernel32
            handle = kernel.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:  # pylint: disable=broad-except
            return False

    def __call__(self, text, *codes):
        return '\033[%sm%s\033[0m' % (';'.join(codes), text) if self.on and codes else text


style = Style()
BADGE = {OK: (' OK ', '30', '42'), WARN: ('주의', '30', '43'), FAIL: ('실패', '97', '41')}
TONE = {OK: '92', WARN: '93', FAIL: '91'}


def cols(text):
    """Display columns of text (East Asian wide characters count 2)."""
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def pad(text, width):
    return text + ' ' * max(width - cols(text), 0)


def wrap(text, width):
    """Lines of at most width columns, broken at spaces where possible."""
    lines, line = [], ''
    for word in text.split(' '):
        candidate = word if not line else line + ' ' + word
        if cols(candidate) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
        while cols(line) > width:   # a word longer than the line
            cut = 0
            while cols(line[:cut + 1]) <= width:
                cut += 1
            lines.append(line[:cut])
            line = line[cut:]
    return lines + [line] if line else lines


def term_width():
    return max(min(shutil.get_terminal_size((100, 30)).columns, 110) - 1, 60)


def busy(what):
    """'checking ...' on the line the result will overwrite."""
    if style.on:
        sys.stdout.write('  %s %s %s' % (style('····', '90'), pad(what, NAME_COLS), style('확인 중…', '90')))
        sys.stdout.flush()


def report(level, what, text):
    """One result: the badge, the item, what was found; after the first ': ' what to do, on its own
    line(s) below in the result's colour."""
    results.append(level)
    width = term_width()
    indent = 2 + 4 + 1 + NAME_COLS + 1
    found, _, todo = text.partition(': ')
    label, fg, bg = BADGE[level]
    if style.on:
        head = '  %s %s ' % (style(label, fg, bg), style(pad(what, NAME_COLS), '1'))
    else:   # no colours: the badge in brackets, all as wide as '[주의]'
        head = '  %s %s ' % (pad('[%s]' % label.strip(), 6), pad(what, NAME_COLS))
        indent += 2
    lines = wrap(found, width - indent)
    out = [head + (lines[0] if lines else '')] + [' ' * indent + l for l in lines[1:]]
    for k, l in enumerate(wrap(todo, width - indent - 2) if todo else []):
        out.append(' ' * indent + style(('→ ' if k == 0 else '  ') + l, TONE[level]))
    if style.on:
        sys.stdout.write('\r\033[2K')
    print('\n'.join(out))


def section(title):
    width = term_width()
    print()
    print(style(' %s ' % title, '1', '96') + style('─' * max(width - cols(title) - 2, 0), '90'))


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
    busy('CARLA')
    try:
        with quiet_stdout():   # the CARLA client's own lines ("Found the required file in cache!")
            import carla
            client = carla.Client('127.0.0.1', 2000)
            client.set_timeout(5.0)
            version = client.get_server_version()
            world = client.get_world()
            town = world.get_map().name.split('/')[-1]
            del world, client
        report(OK, 'CARLA', '서버 실행 중 (%s, 맵 %s)' % (version, town))
    except Exception as error:  # pylint: disable=broad-except
        report(WARN, 'CARLA', '서버 응답 없음: 시작 창에서 Start하면 켜집니다 (%s)' % str(error).splitlines()[0][:60])


class quiet_stdout(object):  # pylint: disable=invalid-name
    """Standard output (the file descriptor: a C++ library's prints too) to nowhere for a while."""

    def __enter__(self):
        sys.stdout.flush()
        self._saved = os.dup(1)
        self._null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(self._null, 1)
        return self

    def __exit__(self, *exc):
        sys.stdout.flush()
        os.dup2(self._saved, 1)
        os.close(self._saved)
        os.close(self._null)
        return False


def check_wheel(choices):
    busy('핸들')
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


def audio_outputs():
    """(name of the Windows default output, [names of every active output]) from Windows Core Audio,
    over ctypes COM (no packages). The car sound (carla-audio-engine, FMOD), the TOR alert and the HUD
    video sound (pygame) all play on the default output, so this is where they are heard."""
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    class GUID(ctypes.Structure):
        _fields_ = [('a', ctypes.c_uint32), ('b', ctypes.c_uint16), ('c', ctypes.c_uint16), ('d', ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [('vt', ctypes.c_ushort), ('r1', ctypes.c_ushort), ('r2', ctypes.c_ushort),
                    ('r3', ctypes.c_ushort), ('value', ctypes.c_void_p), ('pad', ctypes.c_void_p)]

    def guid(text):
        value = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p('{%s}' % text), ctypes.byref(value))
        return value

    def method(obj, index, *argtypes):   # the COM object's index-th method (its vtable)
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[index])

    def release(obj):
        if obj:
            vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(obj)

    out = ctypes.POINTER(ctypes.c_void_p)
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)   # S_FALSE / RPC_E_CHANGED_MODE: COM is on in this thread already, fine
    friendly = PROPERTYKEY(guid('a45c254e-df1c-4efd-8020-67d146a850e0'), 14)   # PKEY_Device_FriendlyName

    def name(device):   # IMMDevice::OpenPropertyStore(STGM_READ), IPropertyStore::GetValue
        store = ctypes.c_void_p()
        method(device, 4, wintypes.DWORD, out)(device, 0, ctypes.byref(store))
        try:
            value = PROPVARIANT()
            method(store, 5, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(
                store, ctypes.byref(friendly), ctypes.byref(value))
            text = ctypes.wstring_at(value.value) if value.vt == 31 and value.value else ''   # VT_LPWSTR
            ole32.PropVariantClear(ctypes.byref(value))
            return text
        finally:
            release(store)

    enumerator = ctypes.c_void_p()   # MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL
    ctypes.oledll.ole32.CoCreateInstance(ctypes.byref(guid('BCDE0395-E52F-467C-8E3D-C4579291692E')), None, 0x17,
                                         ctypes.byref(guid('A95664D2-9614-4F35-A746-DE8DB63617E6')),
                                         ctypes.byref(enumerator))
    try:
        default, device = '', ctypes.c_void_p()
        try:   # GetDefaultAudioEndpoint(eRender, eConsole): fails when there is no output at all
            method(enumerator, 4, ctypes.c_int, ctypes.c_int, out)(enumerator, 0, 0, ctypes.byref(device))
            default = name(device)
        except OSError:
            pass
        finally:
            release(device)
        names, collection = [], ctypes.c_void_p()   # EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE)
        method(enumerator, 3, ctypes.c_int, wintypes.DWORD, out)(enumerator, 0, 1, ctypes.byref(collection))
        try:
            count = ctypes.c_uint()
            method(collection, 3, ctypes.POINTER(ctypes.c_uint))(collection, ctypes.byref(count))
            for i in range(count.value):
                item = ctypes.c_void_p()
                method(collection, 4, ctypes.c_uint, out)(collection, i, ctypes.byref(item))
                try:
                    names.append(name(item))
                finally:
                    release(item)
        finally:
            release(collection)
        return default, names
    finally:
        release(enumerator)


def check_audio():
    """The Windows default output is the earphones (devices.json "earphones": part of its name). If they
    are not connected, the PC's sound (car sound, TOR alert, HUD video) goes to another output, e.g. the
    glasses over Bluetooth."""
    busy('소리 출력')
    try:
        with open(os.path.join(HERE, 'devices.json'), encoding='utf-8') as handle:
            wanted = (json.load(handle).get('earphones') or '').strip()
    except (OSError, ValueError):
        wanted = ''
    try:
        default, names = audio_outputs()
    except Exception as error:  # pylint: disable=broad-except
        report(WARN, '소리 출력', '기본 출력 장치를 읽지 못함 (%s): 작업 표시줄의 소리 아이콘에서 이어폰인지 보세요' % error)
        return
    if not default:
        report(FAIL, '소리 출력', '출력 장치가 없습니다: 이어폰을 연결하세요')
        return
    if not wanted:
        report(WARN, '소리 출력', '기본 출력 장치 %s: 이어폰 이름을 devices.json의 "earphones"에 넣으면 맞는지 봅니다' % default)
        return
    hands_free = 'hands-free' in default.lower() or default.startswith('헤드셋')
    if wanted.lower() in default.lower() and not hands_free:
        report(OK, '소리 출력', '기본 출력 장치 %s (이어폰)' % default)
    elif wanted.lower() in default.lower():
        report(WARN, '소리 출력', '기본 출력 장치 %s (통화용 핸즈프리, 음질 나쁨): 소리 아이콘에서 "스피커(%s)" 쪽을 고르세요' % (
            default, wanted))
    elif any(wanted.lower() in n.lower() for n in names):
        report(WARN, '소리 출력', '기본 출력 장치 %s (이어폰 아님): 이어폰(%s)은 연결돼 있으니 소리 아이콘에서 기본 장치로 고르세요' % (
            default, wanted))
    else:
        report(WARN, '소리 출력', '기본 출력 장치 %s (이어폰 아님): 이어폰(%s)이 연결 안 됨. 이대로면 영상 소리는 '
               '모든 조건에서 글래스가 내고(안경 앱 v18), 차량 소리·TOR 경고음은 이 장치로 나감' % (default, wanted))


def check_video(choices):
    try:
        from launcher import run_plan
        condition = run_plan(choices)[1]
    except Exception:  # pylint: disable=broad-except
        condition = None
    if condition == 'hud':   # played by the experiment itself (hud_video.py), no app
        from hud_video import find_video
        path = find_video(None)
        if path:
            report(OK, 'HUD 영상', '%s (실험 PC에서 재생; 다른 영상은 추가 인자 --video-file 이름)' % os.path.basename(path))
        else:
            report(FAIL, 'HUD 영상', 'mrbd-video 폴더에 영상(mp4)이 없습니다')
    base = (choices.get('video') or '').strip().rstrip('/')
    if not base:
        if choices.get('video_server'):
            base = 'http://127.0.0.1:8080'
        elif condition == 'hud':
            report(WARN, '글래스 앱', '영상 서버 주소가 비어 있어 이 블록 동안 안경 화면을 끄지 못합니다')
            return
        else:
            report(WARN, '영상', '시작 창에 영상 서버 주소가 비어 있습니다: 영상 제어 없이 진행됩니다')
            return
    if not base.startswith(('http://', 'https://')):
        base = 'http://' + base
    busy('영상 서버')
    try:
        from launcher import run_plan
        phone = run_plan(choices)[1] == 'phone'
    except Exception:  # pylint: disable=broad-except
        phone = False
    try:
        state = get_json(base + '/api/state' + ('?device=phone' if phone else ''))
    except Exception as error:  # pylint: disable=broad-except
        report(FAIL, '영상 서버', '%s 응답 없음 (%s): 노트북의 서버를 켜세요' % (base, str(error)[:60]))
        return
    try:
        videos = get_json(base + '/api/videos')
        names = [v.get('name', v) if isinstance(v, dict) else v for v in videos]
    except Exception:  # pylint: disable=broad-except
        names = None
    report(OK, '영상 서버', '%s 응답함%s' % (base, ', 영상 %d개' % len(names) if names is not None else ''))

    if phone:
        check_phone_app(state)
    if phone or condition == 'hud':
        # the glasses app too (2026-11-14): v17 keeps its display black in the other conditions' blocks
        try:
            state = get_json(base + '/api/state')
        except Exception:  # pylint: disable=broad-except
            return
    check_glasses_app(state, condition)


def check_glasses_app(state, condition):
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
    if condition in ('phone', 'hud'):
        if version < 17:
            report(FAIL, '글래스 앱', text + ': v17이 아니면 이 블록(%s 조건)에서 안경에 영상이 나옵니다. 웹앱 연결을 끊었다가 다시 연결하세요' % condition)
        else:
            report(OK, '글래스 앱', text + ' (이 블록 동안 화면을 끔)')
        return
    if version < 17:
        report(FAIL, '글래스 앱', text + ': v17이 아닙니다 (v17: 영상 10° 오른쪽 위, 소리는 PC 이어폰, 다른 조건 블록은 검은 화면). Meta AI 앱에서 웹앱 연결을 끊었다가 다시 연결하세요')
    elif state.get('frozen'):
        report(WARN, '글래스 앱', text + ': 지난 블록의 정지 화면이 남아 있습니다 (시작하면 풀립니다)')
    else:
        report(OK, '글래스 앱', text)


def check_phone_app(state):
    """The phone condition: the NDRT video app on the phone (mrbd-video/phone_app) reports every 2 s."""
    received, now = state.get('received_ts'), state.get('server_ts')
    if not received:
        report(FAIL, '폰 앱', '보고가 없습니다: 휴대폰에서 "NDRT 영상" 앱을 여세요 (서버 주소가 같은지)')
        return
    if state.get('device') != 'phone':
        report(FAIL, '폰 앱', '서버가 기기별 보고를 모릅니다: 영상 서버 노트북의 mrbd-video/server.py를 새 버전으로 바꾸세요')
        return
    age = (now - received) / 1000.0
    if age > 6:
        report(FAIL, '폰 앱', '마지막 보고가 %.0f초 전: 앱이 닫혔거나 화면이 꺼졌습니다' % age)
        return
    title = state.get('title') or ''
    text = 'v%s, 화면 %s%s, %.0f초 전 보고' % (state.get('v'), state.get('screen') or '?',
                                         (' (%s)' % title) if title else '', age)
    if int(state.get('v') or 0) < 4:
        report(FAIL, '폰 앱', text + ': v4가 아닙니다 (v4: 화면 응시 분석용 마커, v3: 세로 재생·소리는 PC 이어폰). python mrbd-video/phone_app/build.py --install --videos')
    elif state.get('frozen'):
        report(WARN, '폰 앱', text + ': 지난 블록의 정지 화면이 남아 있습니다 (시작하면 풀립니다)')
    else:
        report(OK, '폰 앱', text)


def check_g2(choices):
    host = (choices.get('g2') or '').strip()
    if not host:
        report(WARN, 'Glasses 2', '시작 창에 주소가 비어 있습니다: 시선 데이터 없이 진행됩니다')
        return
    from g2_link import G2Link
    busy('Glasses 2')
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
    end = time.monotonic() + wait
    if not style.on:
        print('  SAGAT 화면을 %d초 동안 기다립니다: 태블릿/노트북에서 %s' % (wait, url))
    try:
        while time.monotonic() < end and not server.connected(within=2.0):
            if style.on:   # a countdown on the result's line
                sys.stdout.write('\r\033[2K  %s %s %s' % (
                    style('····', '90'), pad('SAGAT', NAME_COLS),
                    style('태블릿/노트북 기다리는 중 %2d초  %s' % (int(end - time.monotonic()) + 1, url), '90')))
                sys.stdout.flush()
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
    parser.add_argument('--hold', action='store_true',
                        help='at the end wait for a key or a mouse click on the console (the menu)')
    args = parser.parse_args()
    choices = load_choices()
    started = time.monotonic()
    header(choices)
    section('시뮬레이터')
    check_carla()
    check_wheel(choices)
    section('소리 (이어폰)')
    check_audio()
    section('NDRT 영상')
    check_video(choices)
    section('시선 (Glasses 2)')
    check_g2(choices)
    section('SAGAT')
    check_sagat(args.wait)
    return verdict(time.monotonic() - started)


def header(choices):
    """The title and the block the launcher's last settings start."""
    width = term_width()
    try:
        from launcher import run_plan
        set_name, condition = run_plan(choices)
    except Exception:  # pylint: disable=broad-except
        set_name, condition = choices.get('set'), choices.get('condition')
    block = choices.get('block')
    print(style('━' * width, '96'))
    print(style('  사전 점검', '1') + style('   %s' % time.strftime('%Y-%m-%d %H:%M'), '90'))
    print(style('━' * width, '96'))
    rows = [('참가자', '%s%s' % (choices.get('participant'), '  (테스트)' if choices.get('test') else '')),
            ('블록', '%s  →  세트 %s, 조건 %s' % ('연습' if block == 'P' else block, set_name or '?', condition or '?')),
            ('입력', choices.get('input') or '-'),
            ('영상 서버', choices.get('video') or ('이 PC' if choices.get('video_server') else '-')),
            ('Glasses 2', choices.get('g2') or '-')]
    for name, value in rows:
        print('  %s %s' % (style(pad(name, 10), '90'), value))
    print(style('  시작 창의 마지막 설정입니다. 바꾸려면 시작 창에서 고른 뒤 다시 점검하세요.', '90'))


def verdict(seconds):
    """The banner at the end; 1 with a failure."""
    width = term_width()
    fails, warns, oks = results.count(FAIL), results.count(WARN), results.count(OK)
    if fails:
        text, codes = '  ×  실패 %d개: 위의 → 를 고친 뒤 다시 점검하세요' % fails, ('1', '97', '41')
    elif warns:
        text, codes = '  ○  시작해도 됩니다 (주의 %d개: 위를 확인하세요)' % warns, ('1', '30', '43')
    else:
        text, codes = '  ○  모두 정상: 시작해도 됩니다', ('1', '30', '42')
    print()
    print(style(pad(text, width), *codes) if style.on else '==>' + text)
    print(style('  OK %d · 주의 %d · 실패 %d · %.0f초 걸림' % (oks, warns, fails, seconds), '90'))
    return 1 if fails else 0


def hold():
    """The console stays open until a key or a mouse click on it (right click included; QuickEdit,
    which takes the mouse for selecting text, is switched off meanwhile). Windows only, else a key."""
    print()
    print(style('  닫기: 아무 키나 누르거나 이 창을 마우스 오른쪽 클릭', '90'))
    sys.stdout.flush()
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        input()
        return
    kernel = ctypes.windll.kernel32
    handle = kernel.GetStdHandle(-10)                   # STD_INPUT_HANDLE
    mode = wintypes.DWORD()
    if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
        input()
        return
    ENABLE_MOUSE_INPUT, ENABLE_EXTENDED_FLAGS, ENABLE_QUICK_EDIT = 0x10, 0x80, 0x40
    kernel.SetConsoleMode(handle, (mode.value | ENABLE_MOUSE_INPUT | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT)
    kernel.FlushConsoleInputBuffer(handle)

    class Record(ctypes.Structure):     # INPUT_RECORD: EventType, then the event (KEY: bKeyDown first;
        _fields_ = [('kind', wintypes.WORD), ('_pad', wintypes.WORD),   # MOUSE: pos, dwButtonState)
                    ('a', wintypes.DWORD), ('b', wintypes.DWORD), ('c', wintypes.DWORD), ('d', wintypes.DWORD)]
    record, count = Record(), wintypes.DWORD()
    try:
        while kernel.ReadConsoleInputW(handle, ctypes.byref(record), 1, ctypes.byref(count)):
            if record.kind == 1 and record.a:                     # KEY_EVENT, key down
                break
            if record.kind == 2 and record.b & 0x3 and record.d == 0:   # MOUSE_EVENT: a button pressed (not a move)
                break
    finally:
        kernel.SetConsoleMode(handle, mode.value)


if __name__ == '__main__':
    code = main()
    if '--hold' in sys.argv:
        hold()
    sys.exit(code)
