#!/usr/bin/env python

"""
Scenario ABC's start window (start_experiment.bat): the participant number gives each block its set
and condition (assignment()); pick the block and Start runs abc_experiment.py in this console. When
the run is over the window comes back with the next block selected. The choices are kept in
launcher_last.json next to this script (not in git).

Assignment, participant p (1, 2, ...):
    condition order  the 6 orders of (glasses, phone, HUD), ORDERS[(p - 1) % 6]: full counterbalancing
    sets             a 3 x 3 Latin square row ((p - 1) // 6) % 3: block k gets set "ABC"[(k + row) % 3],
                     so each set meets each condition, and every 18 participants it all comes round
    practice drive   set P, with the condition of the participant's block 1 (no TOR anywhere)

Also started from here when ticked: the CARLA server (if not running), gaze_bridge.py for the
Tobii Pro Nano (venv_gaze), the mrbd-video server for the glasses video.
"""

from __future__ import print_function

import itertools
import json
import os
import shlex
import socket
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXPERIMENT = os.path.join(HERE, 'abc_experiment.py')
SERVER_BAT = os.path.join(HERE, 'CarlaUE4_nosound.bat')
LAST_FILE = os.path.join(HERE, 'launcher_last.json')
DEVICES_FILE = os.path.join(HERE, 'devices.json')
GAZE_PYTHON = os.path.join(ROOT, 'venv_gaze', 'Scripts', 'python.exe')
GAZE_BRIDGE = os.path.join(HERE, 'gaze_bridge.py')
MRBD_SERVER = os.path.join(ROOT, 'mrbd-video', 'server.py')
SAGAT_PORT = 5011
CONDITIONS = ('glasses', 'phone', 'hud')
CONDITION_NAMES = {'glasses': '글래스', 'phone': '휴대폰', 'hud': '앞유리 화면(HUD)'}
ORDERS = list(itertools.permutations(CONDITIONS))
BLOCKS = [('P', '연습 주행 (세트 P)'), ('1', '블록 1'), ('2', '블록 2'), ('3', '블록 3')]
DEFAULTS = {'participant': 1, 'block': 'P', 'manual': False, 'set': 'A', 'condition': 'glasses', 'input': 'wheel',
            'test': True, 'out': '', 'nano': False, 'g2': '', 'g2_record': False, 'video': '', 'video_server': False,
            'video_start': '0', 'extra': ''}


def assignment(participant):
    """[(block, set, condition)] for blocks 1-3 of a participant (1, 2, ...)."""
    p = max(1, int(participant))
    order = ORDERS[(p - 1) % len(ORDERS)]
    row = ((p - 1) // len(ORDERS)) % 3
    return [(str(k + 1), 'ABC'[(k + row) % 3], order[k]) for k in range(3)]


def own_address():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('8.8.8.8', 80))
        return probe.getsockname()[0]
    except OSError:
        return '<이 PC IP>'
    finally:
        probe.close()


def port_free(port):
    with socket.socket() as probe:
        try:
            probe.bind(('0.0.0.0', port))
            return True
        except OSError:
            return False


def load_last():
    try:
        with open(LAST_FILE, encoding='utf-8') as handle:
            return dict(DEFAULTS, **json.load(handle))
    except (OSError, ValueError):
        choices = dict(DEFAULTS)
        try:  # the Glasses 2 and video server addresses of devices.json, if there are
            with open(DEVICES_FILE, encoding='utf-8') as handle:
                devices = json.load(handle)
            choices['g2'] = devices.get('g2', '')
            choices['video'] = devices.get('video', '')
        except (OSError, ValueError):
            pass
        return choices


def save_last(choices):
    try:
        with open(LAST_FILE, 'w', encoding='utf-8') as handle:
            json.dump(choices, handle, ensure_ascii=False, indent=2)
    except OSError as error:
        print('Could not save %s: %s' % (LAST_FILE, error))


def run_plan(choices):
    """(set, condition) of the chosen block."""
    if choices['block'] == 'P':
        return 'P', choices['condition'] if choices['manual'] else assignment(choices['participant'])[0][2]
    if choices['manual']:
        return choices['set'], choices['condition']
    _, set_name, condition = assignment(choices['participant'])[int(choices['block']) - 1]
    return set_name, condition


def command(choices):
    set_name, condition = run_plan(choices)
    args = [sys.executable, EXPERIMENT, '--set', set_name, '--block', choices['block'], '--condition', condition,
            '--participant', str(choices['participant']), '--input', choices['input']]
    if choices['test']:
        args.append('--test')
    if choices['out'].strip():
        args += ['--out', choices['out'].strip()]
    if choices['nano']:
        args.append('--gaze')
    if choices['g2'].strip():
        args += ['--g2', choices['g2'].strip()]
        if choices['g2_record']:
            args.append('--g2-record')
    if choices['video'].strip():
        args += ['--video', choices['video'].strip()]
        try:
            if float(choices['video_start'] or 0) > 0:
                args += ['--video-start', str(float(choices['video_start']))]
        except ValueError:
            pass
    if choices['extra'].strip():
        args += shlex.split(choices['extra'], posix=False)
    return args


def server_running():
    try:
        tasklist = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'tasklist.exe')
        output = subprocess.run([tasklist, '/fi', 'imagename eq CarlaUE4-Win64-Shipping.exe'],
                                capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return 'CarlaUE4' in output


class Launcher(object):
    def __init__(self, choices):
        self.result = None
        self.root = root = tk.Tk()
        root.title('시나리오 ABC 실험 시작')
        root.resizable(False, False)
        font = ('Malgun Gothic', 11)
        root.option_add('*Font', font)
        style = ttk.Style(root)
        style.configure('.', font=font)
        style.configure('Start.TButton', font=('Malgun Gothic', 13, 'bold'), padding=8)
        style.configure('Plan.TLabel', foreground='#1a5fb4')
        v = self.vars = {
            'participant': tk.IntVar(value=choices['participant']), 'block': tk.StringVar(value=choices['block']),
            'manual': tk.BooleanVar(value=choices['manual']), 'set': tk.StringVar(value=choices['set']),
            'condition': tk.StringVar(value=choices['condition']), 'input': tk.StringVar(value=choices['input']),
            'test': tk.BooleanVar(value=choices['test']), 'out': tk.StringVar(value=choices['out']),
            'nano': tk.BooleanVar(value=choices['nano']), 'g2': tk.StringVar(value=choices['g2']),
            'g2_record': tk.BooleanVar(value=choices['g2_record']), 'video': tk.StringVar(value=choices['video']),
            'video_server': tk.BooleanVar(value=choices['video_server']),
            'video_start': tk.StringVar(value=choices['video_start']), 'extra': tk.StringVar(value=choices['extra'])}
        frame = ttk.Frame(root, padding=16)
        frame.grid()
        row = [0]

        def group(title):
            box = ttk.LabelFrame(frame, text=title, padding=(10, 6))
            box.grid(row=row[0], column=0, sticky='nsew', padx=4, pady=4)
            row[0] += 1
            return box

        box = group('참가자 / 블록')
        line = ttk.Frame(box)
        line.pack(anchor='w')
        ttk.Label(line, text='참가자 번호').pack(side='left')
        ttk.Spinbox(line, from_=1, to=200, width=5, textvariable=v['participant'], command=self._update).pack(
            side='left', padx=6)
        v['participant'].trace_add('write', lambda *_: self._update())
        self._order = ttk.Label(box, style='Plan.TLabel', justify='left')
        self._order.pack(anchor='w', pady=(4, 6))
        for value, text in BLOCKS:
            ttk.Radiobutton(box, text=text, value=value, variable=v['block'], command=self._update).pack(anchor='w')
        manual = ttk.Frame(box)
        manual.pack(anchor='w', pady=(6, 0))
        ttk.Checkbutton(manual, text='직접 지정:', variable=v['manual'], command=self._update).pack(side='left')
        self._set_box = ttk.Combobox(manual, textvariable=v['set'], values=('A', 'B', 'C'), width=3, state='readonly')
        self._set_box.pack(side='left', padx=4)
        self._cond_box = ttk.Combobox(manual, textvariable=v['condition'], values=CONDITIONS, width=8,
                                      state='readonly')
        self._cond_box.pack(side='left', padx=4)
        self._set_box.bind('<<ComboboxSelected>>', lambda _: self._update())
        self._cond_box.bind('<<ComboboxSelected>>', lambda _: self._update())
        self._plan = ttk.Label(box, font=('Malgun Gothic', 12, 'bold'))
        self._plan.pack(anchor='w', pady=(8, 0))

        box = group('입력 / 데이터')
        line = ttk.Frame(box)
        line.pack(anchor='w')
        for value, text in (('wheel', '핸들'), ('keyboard', '키보드 (핸들 없을 때)')):
            ttk.Radiobutton(line, text=text, value=value, variable=v['input']).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(box, text='테스트 (Data/test/MMDDHHMMSS 에 저장)', variable=v['test'],
                        command=self._update).pack(anchor='w', pady=(6, 0))
        line = ttk.Frame(box)
        line.pack(anchor='w', fill='x', pady=(4, 0))
        ttk.Label(line, text='저장 폴더').pack(side='left')
        ttk.Entry(line, textvariable=v['out'], width=40).pack(side='left', padx=6)
        self._out_hint = ttk.Label(box, foreground='#77767b')
        self._out_hint.pack(anchor='w')

        box = group('시선 / 영상')
        ttk.Checkbutton(box, text='Tobii Pro Nano (gaze_bridge.py 를 함께 실행)', variable=v['nano']).pack(anchor='w')
        line = ttk.Frame(box)
        line.pack(anchor='w', pady=(4, 0))
        ttk.Label(line, text='Tobii Glasses 2 주소').pack(side='left')
        ttk.Entry(line, textvariable=v['g2'], width=18).pack(side='left', padx=6)
        ttk.Checkbutton(line, text='녹화도 시작/종료', variable=v['g2_record']).pack(side='left')
        ttk.Label(box, text='(비우면 끔. 마커만: Glasses Controller에서 녹화 중일 때)', foreground='#77767b').pack(anchor='w')
        line = ttk.Frame(box)
        line.pack(anchor='w', pady=(6, 0))
        ttk.Label(line, text='NDRT 영상 서버').pack(side='left')
        ttk.Entry(line, textvariable=v['video'], width=26).pack(side='left', padx=6)
        ttk.Label(line, text='시작 위치(초)').pack(side='left')
        ttk.Entry(line, textvariable=v['video_start'], width=6).pack(side='left', padx=4)
        ttk.Checkbutton(box, text='mrbd-video 서버를 이 PC에서 실행 (http://127.0.0.1:8080)',
                        variable=v['video_server']).pack(anchor='w')
        ttk.Label(box, text='(SAGAT 때 안경 영상이 같이 멈춤. 비우면 끔. 다른 노트북에서 서버를 띄웠으면\n'
                            ' 그 주소, 예: http://192.168.0.69:8080 — 안경도 그 노트북 주소로 접속)',
                  foreground='#77767b', justify='left').pack(anchor='w')

        box = group('SAGAT 태블릿')
        ttk.Label(box, text='아이패드 Safari: http://%s:%d/' % (own_address(), SAGAT_PORT),
                  style='Plan.TLabel').pack(anchor='w')
        line = ttk.Frame(box)
        line.pack(anchor='w', fill='x', pady=(6, 0))
        ttk.Label(line, text='추가 인자').pack(side='left')
        ttk.Entry(line, textvariable=v['extra'], width=44).pack(side='left', padx=6)

        buttons = ttk.Frame(frame)
        buttons.grid(row=row[0], column=0, sticky='ew', pady=(10, 0))
        ttk.Button(buttons, text='종료', command=root.destroy).pack(side='right', padx=4)
        start = ttk.Button(buttons, text='실험 시작', style='Start.TButton', command=self._start)
        start.pack(side='right', padx=4)
        start.focus_set()
        root.bind('<Return>', lambda _: self._start())
        root.bind('<Escape>', lambda _: root.destroy())
        self._update()
        root.update_idletasks()
        x = (root.winfo_screenwidth() - root.winfo_width()) // 2
        y = (root.winfo_screenheight() - root.winfo_height()) // 4
        root.geometry('+%d+%d' % (max(0, x), max(0, y)))
        root.lift()
        root.attributes('-topmost', True)
        root.after(300, lambda: root.attributes('-topmost', False))

    def _choices(self):
        choices = {}
        for key, var in self.vars.items():
            try:
                choices[key] = var.get()
            except tk.TclError:  # participant field being typed
                choices[key] = DEFAULTS[key]
        return choices

    def _update(self):
        choices = self._choices()
        state = 'readonly' if choices['manual'] else 'disabled'
        self._set_box.configure(state=state if choices['block'] != 'P' else 'disabled')
        self._cond_box.configure(state=state)
        plan = assignment(choices['participant'])
        self._order.configure(text='배정: ' + '  ·  '.join('블록 %s = 세트 %s %s' % (b, s, CONDITION_NAMES[c])
                                                         for b, s, c in plan))
        set_name, condition = run_plan(choices)
        self._plan.configure(text='→ 세트 %s, %s' % (set_name, CONDITION_NAMES[condition]))
        if choices['test']:
            self._out_hint.configure(text='→ Data/test/<월일시분초>/')
        else:
            block = 'P' if choices['block'] == 'P' else choices['block']
            self._out_hint.configure(text='→ Data/P%02d_B%s_%s_%s/' % (int(choices['participant'] or 0), block,
                                                                        set_name, condition))

    def _start(self):
        self.result = self._choices()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.result


def start_helpers(choices, started):
    """gaze_bridge.py and the mrbd-video server, each once, in a console of its own."""
    new_console = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
    if choices['nano'] and 'nano' not in started:
        python = GAZE_PYTHON if os.path.isfile(GAZE_PYTHON) else sys.executable
        print('Starting gaze_bridge.py (Tobii Pro Nano) in its own console...')
        started['nano'] = subprocess.Popen([python, GAZE_BRIDGE], cwd=HERE, creationflags=new_console)
    if choices['video_server'] and 'video' not in started:
        if port_free(8080):
            print('Starting the mrbd-video server (http://%s:8080/) in its own console...' % own_address())
            started['video'] = subprocess.Popen([sys.executable, MRBD_SERVER], cwd=os.path.dirname(MRBD_SERVER),
                                                creationflags=new_console)
        else:
            print('Port 8080 is in use: the mrbd-video server is already running?')
        if not choices['video'].strip():
            choices['video'] = 'http://127.0.0.1:8080'


def main():
    choices = load_last()
    started = {}
    while True:
        choices = Launcher(choices).run()
        if choices is None:
            return
        save_last(choices)
        start_helpers(choices, started)
        if not server_running():
            print('Starting the CARLA server (CarlaUE4_nosound.bat)...')
            subprocess.call(['cmd', '/c', SERVER_BAT])
        args = command(choices)
        print()
        print('=' * 78)
        print(' '.join('"%s"' % arg if ' ' in arg else arg for arg in args))
        print('=' * 78, flush=True)
        try:
            code = subprocess.call(args, cwd=ROOT)
        except KeyboardInterrupt:
            code = None
        print('The run ended (exit code %s). The start window opens again.' % code, flush=True)
        order = [b for b, _ in BLOCKS]
        if code == 0 and choices['block'] in order[:-1]:  # the next block next time
            choices['block'] = order[order.index(choices['block']) + 1]


if __name__ == '__main__':
    main()
