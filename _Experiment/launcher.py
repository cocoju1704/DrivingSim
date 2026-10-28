#!/usr/bin/env python

"""
The experiment's start window (start_experiment.bat): the options of a run picked in a window instead
of typed as a command. Start runs takeover_experiment.py with them in this console; when the run is
over the window comes back, with the same choices, for the next one. The choices are kept in
launcher_last.json next to this script (not in git).

Recording (with the glasses only): TORApp records the glasses' camera with the glasses display
drawn over it and the glasses' microphone, on the phone in Movies/TORApp/<run>.mp4.

The intervention is written to intervention_launcher.json (not in git), with the delay and the
question time of intervention_config.json; a test run adds the test timing of intervention_none.json.
The CARLA server is started first if it is not running (CarlaUE4_nosound.bat).
"""

from __future__ import print_function

import json
import os
import shlex
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
EXPERIMENT = os.path.join(HERE, 'takeover_experiment.py')
SERVER_BAT = os.path.join(HERE, 'CarlaUE4_nosound.bat')
LAST_FILE = os.path.join(HERE, 'launcher_last.json')
CONFIG_FILE = os.path.join(HERE, 'intervention_config.json')
TEST_CONFIG_FILE = os.path.join(HERE, 'intervention_none.json')
RUN_CONFIG_FILE = os.path.join(HERE, 'intervention_launcher.json')
NDRT_PORT = 5008

SCENARIOS = [('0', '0    연습 (시내에서 고속도로까지 수동 주행)'),
             ('1-a', '1-a  고속도로 출구'), ('1-b', '1-b  고속도로 출구 (반대 방향 차로)'),
             ('2-a', '2-a  공사 구간 (3·4차로 막힘)'), ('2-b', '2-b  공사 구간 (1·2차로 막힘, 반전)'),
             ('3-a', '3-a  사고 차량 (3·4차로 막힘)'), ('3-b', '3-b  사고 차량 (1·2차로 막힘, 반전)')]
OLD_SCENARIOS = {0: '0', 1: '1-a', 2: '2-a', 3: '1-a', 4: '3-a'}  # launcher_last.json from before the variants
LANE_AUTO = '자동'  # no --lane: the lane that closes (2-b, 3-b: 2), else 3
INTERVENTIONS = [('none', '없음 (사전 경고만)'), ('driving', '주행 상황 (SA)'), ('NDRT', 'NDRT (RtR)')]
FORMATS = [('summary', '요약 (statement)'), ('question', '질문 (question)')]
MODALITIES = [('visual', '시각 (글래스/모니터 텍스트)'), ('auditory', '청각 (음성으로 읽기, TTS)')]
DISPLAYS = [('phone', '글래스 (Wi-Fi)'), ('usb', '글래스 (USB)'), ('screen', '모니터 (글래스 없음)')]
INPUTS = [('wheel', '핸들'), ('keyboard', '키보드')]
DEFAULTS = {'scenario': '1-a', 'intervention': 'NDRT', 'format': 'summary', 'modality': 'visual', 'display': 'phone',
            'ndrt': True,
            'input': 'wheel', 'lane': LANE_AUTO, 'minimap': False, 'speed_hold': False, 'reengage': True, 'test': False,
            'record': False, 'extra': ''}


def own_address():
    """This PC's address on the network (for the NDRT laptop's browser), or None."""
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('8.8.8.8', 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def load_last():
    try:
        with open(LAST_FILE, encoding='utf-8') as handle:
            choices = dict(DEFAULTS, **json.load(handle))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    if isinstance(choices['scenario'], int):  # numbered before the variants (3 was the fog, gone)
        choices['scenario'] = OLD_SCENARIOS.get(choices['scenario'], DEFAULTS['scenario'])
        choices['lane'] = LANE_AUTO
    choices['lane'] = str(choices['lane'])
    return choices


def save_last(choices):
    try:
        with open(LAST_FILE, 'w', encoding='utf-8') as handle:
            json.dump(choices, handle, ensure_ascii=False, indent=2)
    except OSError as error:
        print('Could not save %s: %s' % (LAST_FILE, error))


def write_intervention(choices):
    """intervention_launcher.json for this run: the chosen intervention and format, the timing of
    intervention_config.json (and the test timing of intervention_none.json for a test run)."""
    with open(CONFIG_FILE, encoding='utf-8') as handle:
        config = json.load(handle)
    config['intervention'] = choices['intervention']
    config['format'] = choices['format']
    config['modality'] = choices['modality']
    config.pop('test', None)
    if choices['test']:
        with open(TEST_CONFIG_FILE, encoding='utf-8') as handle:
            test = json.load(handle)
        config.update({key: value for key, value in test.items() if key.startswith('test')})
    with open(RUN_CONFIG_FILE, 'w', encoding='utf-8') as handle:
        json.dump(config, handle, ensure_ascii=False, indent=4)


def command(choices):
    """takeover_experiment.py's command line for the choices."""
    args = [sys.executable, EXPERIMENT, '--scenario', choices['scenario'],
            '--input', choices['input'], '--intervention-config', RUN_CONFIG_FILE]
    if choices['lane'] != LANE_AUTO:
        args += ['--lane', choices['lane']]
    if choices['display'] == 'screen':
        args.append('--no-glasses')
    else:
        args += ['--glasses', choices['display']]
    if choices['ndrt'] and choices['scenario'] != '0':
        args += ['--ndrt', 'here', '--ndrt-port', str(NDRT_PORT)]
    if choices['minimap']:
        args.append('--minimap')
    if choices['speed_hold']:
        args.append('--speed-hold')
    if not choices['reengage']:
        args.append('--no-reengage')
    if choices['record'] and choices['display'] != 'screen':
        args.append('--record')
    if choices['extra'].strip():
        args += shlex.split(choices['extra'], posix=False)
    return args


def server_running():
    try:
        output = subprocess.run(['tasklist', '/fi', 'imagename eq CarlaUE4-Win64-Shipping.exe'],
                                capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell: the experiment waits for the server anyway
    return 'CarlaUE4' in output


class Launcher(object):
    """The window: one run's choices; Start closes it and hands them back."""

    def __init__(self, choices):
        self.result = None
        self.root = root = tk.Tk()
        root.title('TOR 실험 시작')
        root.resizable(False, False)
        font = ('Malgun Gothic', 11)
        root.option_add('*Font', font)
        style = ttk.Style(root)
        style.configure('.', font=font)
        style.configure('Start.TButton', font=('Malgun Gothic', 13, 'bold'), padding=8)

        self.vars = {
            'scenario': tk.StringVar(value=choices['scenario']),
            'intervention': tk.StringVar(value=choices['intervention']),
            'format': tk.StringVar(value=choices['format']),
            'modality': tk.StringVar(value=choices['modality']),
            'display': tk.StringVar(value=choices['display']),
            'ndrt': tk.BooleanVar(value=choices['ndrt']),
            'input': tk.StringVar(value=choices['input']),
            'lane': tk.StringVar(value=choices['lane']),
            'minimap': tk.BooleanVar(value=choices['minimap']),
            'speed_hold': tk.BooleanVar(value=choices['speed_hold']),
            'reengage': tk.BooleanVar(value=choices['reengage']),
            'test': tk.BooleanVar(value=choices['test']),
            'record': tk.BooleanVar(value=choices['record']),
            'extra': tk.StringVar(value=choices['extra']),
        }
        frame = ttk.Frame(root, padding=16)
        frame.grid()
        row = 0

        def group(title, column=0, span=1):
            box = ttk.LabelFrame(frame, text=title, padding=(10, 6))
            box.grid(row=row, column=column, columnspan=span, sticky='nsew', padx=4, pady=4)
            return box

        box = group('시나리오', span=2)
        for value, text in SCENARIOS:
            ttk.Radiobutton(box, text=text, value=value, variable=self.vars['scenario'],
                            command=self._update).pack(anchor='w')
        row += 1
        box = group('개입 (사전 경고 중 텍스트)')
        for value, text in INTERVENTIONS:
            ttk.Radiobutton(box, text=text, value=value, variable=self.vars['intervention'],
                            command=self._update).pack(anchor='w')
        self._format_box = box = group('형식 / 전달 방식', column=1)
        self._format_buttons = [ttk.Radiobutton(box, text=text, value=value, variable=self.vars['format'])
                                for value, text in FORMATS]
        for button in self._format_buttons:
            button.pack(anchor='w')
        ttk.Separator(box).pack(fill='x', pady=4)
        for value, text in MODALITIES:  # how the text reaches the driver
            button = ttk.Radiobutton(box, text=text, value=value, variable=self.vars['modality'])
            button.pack(anchor='w')
            self._format_buttons.append(button)
        row += 1
        box = group('경고 / 개입 표시')
        for value, text in DISPLAYS:
            ttk.Radiobutton(box, text=text, value=value, variable=self.vars['display'],
                            command=self._update).pack(anchor='w')
        self._record_check = ttk.Checkbutton(box, text='녹화 (글래스 카메라 + 화면 + 마이크)',
                                             variable=self.vars['record'])
        self._record_check.pack(anchor='w', pady=(6, 0))
        box = group('운전 입력', column=1)
        for value, text in INPUTS:
            ttk.Radiobutton(box, text=text, value=value, variable=self.vars['input']).pack(anchor='w')
        lane = ttk.Frame(box)
        lane.pack(anchor='w', pady=(6, 0))
        ttk.Label(lane, text='차로').pack(side='left')
        ttk.Combobox(lane, textvariable=self.vars['lane'], values=(LANE_AUTO, '1', '2', '3'), width=5,
                     state='readonly').pack(side='left', padx=6)
        ttk.Label(lane, text='(1 = 중앙분리대 쪽; 자동: 막히는 차로)').pack(side='left')
        row += 1
        box = group('NDRT (카카오톡 채팅)', span=2)
        self._ndrt_check = ttk.Checkbutton(box, text='이 PC에서 채팅 서버 실행', variable=self.vars['ndrt'],
                                           command=self._update)
        self._ndrt_check.pack(anchor='w')
        address = own_address() or '<이 PC IP>'
        self._ndrt_hint = ttk.Label(box, text='노트북 브라우저: http://%s:%d/' % (address, NDRT_PORT),
                                    foreground='#1a5fb4')
        self._ndrt_hint.pack(anchor='w', padx=(24, 0))
        row += 1
        box = group('옵션', span=2)
        for key, text in (('minimap', '내비게이션 미니맵 (오른쪽 위)'),
                          ('reengage', 'takeover 10초 뒤 자율주행 자동 복귀'),
                          ('speed_hold', 'takeover 후 속도 유지 (끄면 페달만으로 주행: MALAT 측정용)'),
                          ('test', '테스트 실행 (10초 뒤 사전 경고, 5초 뒤 TOR)')):
            ttk.Checkbutton(box, text=text, variable=self.vars[key]).pack(anchor='w')
        extra = ttk.Frame(box)
        extra.pack(anchor='w', fill='x', pady=(6, 0))
        ttk.Label(extra, text='추가 인자').pack(side='left')
        ttk.Entry(extra, textvariable=self.vars['extra'], width=44).pack(side='left', padx=6)
        row += 1
        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        ttk.Button(buttons, text='종료', command=root.destroy).pack(side='right', padx=4)
        start = ttk.Button(buttons, text='실험 시작', style='Start.TButton', command=self._start)
        start.pack(side='right', padx=4)
        start.focus_set()
        root.bind('<Return>', lambda _: self._start())
        root.bind('<Escape>', lambda _: root.destroy())
        self._update()
        root.update_idletasks()
        x = (root.winfo_screenwidth() - root.winfo_width()) // 2
        y = (root.winfo_screenheight() - root.winfo_height()) // 3
        root.geometry('+%d+%d' % (max(0, x), max(0, y)))
        root.lift()
        root.attributes('-topmost', True)
        root.after(300, lambda: root.attributes('-topmost', False))

    def _update(self):
        """Grey out what does not apply: the format without an intervention, the NDRT in practice."""
        state = 'disabled' if self.vars['intervention'].get() == 'none' else 'normal'
        for button in self._format_buttons:
            button.configure(state=state)
        practice = self.vars['scenario'].get() == '0'
        self._ndrt_check.configure(state='disabled' if practice else 'normal')
        shown = self.vars['ndrt'].get() and not practice
        self._ndrt_hint.configure(foreground='#1a5fb4' if shown else '#9a9996')
        # the recording is made by TORApp with the glasses' camera: only with the glasses
        self._record_check.configure(state='disabled' if self.vars['display'].get() == 'screen' else 'normal')

    def _start(self):
        choices = {key: var.get() for key, var in self.vars.items()}
        if choices['intervention'] == 'NDRT' and not choices['ndrt'] and choices['scenario'] != '0':
            if not messagebox.askyesno('NDRT', 'NDRT 개입인데 채팅 서버를 켜지 않았습니다.\n'
                                               'RtR 요약 없이 고정 문장으로 진행할까요?', parent=self.root):
                return
        self.result = choices
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.result


def main():
    choices = load_last()
    while True:
        choices = Launcher(choices).run()
        if choices is None:
            return
        save_last(choices)
        write_intervention(choices)
        if not server_running():
            print('Starting the CARLA server (CarlaUE4_nosound.bat)...')
            subprocess.call(['cmd', '/c', SERVER_BAT])
        args = command(choices)
        print()
        print('=' * 78)
        print(' '.join('"%s"' % arg if ' ' in arg else arg for arg in args))
        print('=' * 78, flush=True)
        try:
            code = subprocess.call(args, cwd=os.path.dirname(HERE))
        except KeyboardInterrupt:
            code = None
        print('The run ended (exit code %s). The start window opens again.' % code, flush=True)


if __name__ == '__main__':
    main()
