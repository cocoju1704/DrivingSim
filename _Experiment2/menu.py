#!/usr/bin/env python

"""
Scenario ABC on the experiment PC: one window with a button for everything run by hand (_menu.bat
starts it). Each button runs its step in a console window of its own (its output and keys there, the
calibration and validation on the monitors, running by themselves: Enter on their last screen closes
them, console too); the console closes by itself, but the preflight check's, which is its result,
and one whose step ended with an error (its message);
the menu stays open. Shown at the top: when
the Glasses 2 were last calibrated and the last validation's verdict.

Not in it: CarlaUE4_nosound.bat (the start window starts CARLA by itself; the CARLA button is for
starting it alone) and sagat_laptop.bat (copied to the SAGAT laptop and run there).
"""

from __future__ import print_function

import json
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(HERE, '..', 'venv_carla', 'Scripts', 'python.exe')
PY = VENV_PY if os.path.exists(VENV_PY) else 'python'
CALIBRATION_FILE = os.path.join(HERE, 'g2_calibration.json')
VALIDATION_FILE = os.path.join(HERE, 'g2_validation.json')
REFRESH_MS = 3000

# (group, label, what it does, console title, command lines run in turn: a line runs only when the
# one before ended without an error when it starts with '&&')
STEPS = [
    ('실험', '실험 시작', '시작 창: 참가자·블록을 고르고 시작', 'Scenario ABC experiment',
     ['py launcher.py']),
    ('실험', '사전 점검', 'CARLA, 핸들, 영상 서버·글래스 앱, Glasses 2, SAGAT', 'Scenario ABC - preflight check',
     ['py preflight.py']),
    ('Glasses 2', '착용 점검', '각도 측정: 오른쪽 모니터에 "착용 OK"가 나오면 Esc', 'Glasses 2 fit',
     ['py g2_aim.py --aim-v=-3.5 --good=2']),
    ('Glasses 2', '캘리브레이션 + 검증', '가운데 모니터 타깃 → 안경 화면 점 → 성공하면 바로 검증',
     'Glasses 2 calibration', ['py g2_calibrate.py --validate', '&& py g2_validate.py']),
    ('Glasses 2', '검증만', '모니터·미러 타깃, 안경 화면 점 → 통과 / 다시 착용', 'Glasses 2 validation',
     ['py g2_validate.py']),
    ('Glasses 2', '안경 화면 보정만', 'Ray-Ban Display 점만 다시 (+ 검증)', 'Glasses 2 display',
     ['py g2_calibrate.py --display-only --validate', '&& py g2_validate.py']),
    ('기타', 'CARLA 서버만 켜기', '시작 창이 알아서 켜므로 보통은 필요 없음', None, ['bat CarlaUE4_nosound.bat']),
]


def command(title, lines):
    """One cmd.exe line for the steps' console: UTF-8, Windows' own folders on PATH (the experiment
    PC's system PATH has lost System32), the lines in turn, then a pause to read the output."""
    parts = ['title %s' % title, 'chcp 65001 >nul', 'cd /d "%s"' % HERE]
    for line in lines:
        joiner = ' && ' if line.startswith('&&') else ' & '
        kind, rest = line.lstrip('& ').split(' ', 1)
        run = '"%s" %s' % (PY, rest) if kind == 'py' else 'call %s' % rest
        if line.startswith('&&'):
            parts[-1] = '(%s)%s%s' % (parts[-1], joiner, run)
        else:
            parts.append(run)
    if any('preflight' in line for line in lines):
        return ' & '.join(parts) + ' & echo. & pause'       # its result is this console
    # the console closes by itself (the results are on the monitors), but after an error: its message
    return ' & '.join(parts) + ' & if errorlevel 1 (echo. & echo 오류로 멈췄습니다: 위 메시지를 확인하세요. & pause)'


def run(title, lines):
    env = dict(os.environ)
    root = env.get('SystemRoot', r'C:\Windows')
    env['PATH'] = os.pathsep.join([os.path.join(root, 'System32'), root,
                                   os.path.join(root, 'System32', 'WindowsPowerShell', 'v1.0'), env.get('PATH', '')])
    if title is None:       # a .bat that opens its own console
        subprocess.Popen([os.path.join(root, 'System32', 'cmd.exe'), '/c', os.path.join(HERE, lines[0].split(' ', 1)[1])],
                         cwd=HERE, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        return
    subprocess.Popen('"%s" /c "%s"' % (os.path.join(root, 'System32', 'cmd.exe'), command(title, lines)), cwd=HERE,
                     env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)


def _ago(seconds):
    if seconds < 90:
        return '방금'
    if seconds < 3600:
        return '%d분 전' % (seconds / 60)
    if seconds < 86400:
        return '%d시간 전' % (seconds / 3600)
    return '%d일 전' % (seconds / 86400)


def status():
    """[(text, ok)] of the last calibration and validation (ok None: unknown)."""
    rows = []
    try:
        with open(CALIBRATION_FILE, encoding='utf-8') as handle:
            cal = json.load(handle)
        at = cal.get('pc_time') or os.path.getmtime(CALIBRATION_FILE)
        rows.append(('캘리브레이션: %s (%s, %s)' % (_ago(time.time() - at), time.strftime('%m-%d %H:%M', time.localtime(at)),
                                                cal.get('ca_id', '?')), None))
    except (OSError, ValueError):
        rows.append(('캘리브레이션: 기록 없음', False))
    try:
        with open(VALIDATION_FILE, encoding='utf-8') as handle:
            val = json.load(handle)
        at = os.path.getmtime(VALIDATION_FILE)
        same = val.get('g2_calibration') == (cal.get('ca_id') if rows[0][1] is None else None)
        verdict = val.get('pass')
        text = '검증: %s (%s)' % ('통과' if verdict else '다시 착용' if verdict is False else '판정 없음', _ago(time.time() - at))
        if verdict is False and val.get('pass_reasons'):
            text += '  ·  ' + ', '.join(val['pass_reasons'])
        if not same:
            text += '  ·  지금 캘리브레이션 이전의 검증'
            verdict = None if verdict else verdict
        rows.append((text, verdict))
    except (OSError, ValueError):
        rows.append(('검증: 기록 없음', None))
    return rows


class Menu(object):
    def __init__(self):
        self.root = root = tk.Tk()
        root.title('시나리오 ABC')
        root.configure(background='#f4f4f4')
        font = ('Malgun Gothic', 11)
        root.option_add('*Font', font)
        style = ttk.Style(root)
        style.configure('.', font=font, background='#f4f4f4')
        style.configure('Step.TButton', font=('Malgun Gothic', 12, 'bold'), padding=(10, 8), width=18)
        style.configure('Group.TLabel', font=('Malgun Gothic', 10, 'bold'), foreground='#666666')
        style.configure('Note.TLabel', foreground='#555555')
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='시나리오 ABC 실험', font=('Malgun Gothic', 16, 'bold')).grid(
            row=0, column=0, columnspan=2, sticky='w')
        self.status = []
        for k in range(2):
            label = tk.Label(frame, anchor='w', justify='left', background='#f4f4f4', font=('Malgun Gothic', 10),
                             wraplength=520)
            label.grid(row=1 + k, column=0, columnspan=2, sticky='w')
            self.status.append(label)
        row, group = 3, None
        for name, label, note, title, lines in STEPS:
            if name != group:
                group = name
                ttk.Label(frame, text=name, style='Group.TLabel').grid(row=row, column=0, columnspan=2, sticky='w',
                                                                      pady=(14, 2))
                row += 1
            ttk.Button(frame, text=label, style='Step.TButton',
                       command=lambda t=title or label, l=lines, b=title: self._run(b, l, t)).grid(
                row=row, column=0, sticky='w', pady=3)
            ttk.Label(frame, text=note, style='Note.TLabel').grid(row=row, column=1, sticky='w', padx=(12, 0))
            row += 1
        self.message = ttk.Label(frame, text='', style='Note.TLabel')
        self.message.grid(row=row, column=0, columnspan=2, sticky='w', pady=(14, 0))
        self.refresh()

    def _run(self, title, lines, shown):
        try:
            run(title, lines)
            self.message.configure(text='%s: 새 창에서 실행 중 (%s)' % (shown, time.strftime('%H:%M:%S')))
        except OSError as error:
            self.message.configure(text='%s: 실행 실패 (%s)' % (shown, error))

    def refresh(self):
        for label, (text, ok) in zip(self.status, status()):
            label.configure(text=text, foreground='#222222' if ok is None else ('#1a7f37' if ok else '#c62828'))
        self.root.after(REFRESH_MS, self.refresh)


def main():
    if '--print' in sys.argv:       # the console lines, for a check
        for _, label, _, title, lines in STEPS:
            print(label, '->', command(title or label, lines))
        for text, ok in status():
            print(ok, text)
        return 0
    Menu().root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
