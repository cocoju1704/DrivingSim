#!/usr/bin/env python

"""
NDRT: a team group chat that looks like KakaoTalk (kakao_app/), in which the participant writes
the room's notice from what the team said (kakao_sets/scenario<N>.json).

It runs on the NDRT laptop, apart from the simulator PC: start it there before the drive and open
http://localhost:5008/ in the laptop's browser (a phone works too: the page fits narrow screens).
The participant enters their name, reads the chat and writes the notice. After the takeover the
experiment (takeover_experiment.py --ndrt <laptop address>, KakaoNdrtLink) releases the follow-up
messages: the team adds them one by one, each with the "카톡" message sound (kakao_app/kakao.mp3 if
it is there, else two tones the page makes) and no popup; the last one asks to finish the notice
with the additions. The draft stays where it was.

It also writes the NDRT ready-to-resume (RtR) summary of the draft with the OpenAI API, in place of
the Gmail extension and rtr_bridge.py (now in legacy/), when the experiment asks for one. API key:
the OPENAI_API_KEY environment variable or openai_api_key.txt next to this script (not in git).
The laptop's firewall has to let the simulator PC in on the port (5008).

    GET  /                  the chat page (kakao_app/)
    GET  /ndrt/state?seq=N  everything the page shows, unless nothing changed since seq N
    POST /ndrt/name         {"name": "김민수"}
    POST /ndrt/draft        {"text": "..."}: the notice being written (the page sends it as it changes)
    POST /ndrt/post         {"text": "..."}: the notice is posted to the room
    POST /ndrt/event        {"type": "focus"} etc.: logged only
    GET  /ndrt/followup     release the follow-up messages now (?source=NAME: the experiment, or by hand)
    GET  /ndrt/nudge        ?index=K: post nudge K (kakao_sets "nudges" during the pre-alert, then
                            "late_nudges" after the lane 2 hazard)
    GET  /ndrt/mark         ?event=prealert etc.: the experiment's events, logged on this clock
    GET  /ndrt/info         scenario and title, for the experiment to check
    GET  /rtr/request       request an RtR summary now (?source=NAME)
    GET  /rtr/status        the latest RtR request and result

Logs, in Data/YYMMDD_HHMMSS_ndrt/ (--log-dir): ndrt.jsonl (name, draft changes, posts, follow-up
messages, page events, the experiment's pre-alert / TOR / takeover) and rtr.jsonl (summary requests
and results).

On the NDRT laptop, from the CARLA_0.9.16 folder (or wherever _Experiment is):

    python _Experiment\\kakao_ndrt.py --scenario 4
    python _Experiment\\kakao_ndrt.py --scenario 0 --followup-after 120   (practice, no simulator)
"""

from __future__ import print_function

import argparse
import datetime
import json
import logging
import mimetypes
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_ROOT = os.path.join(HERE, '..', 'Data')
APP_DIR = os.path.join(HERE, 'kakao_app')
SET_DIR = os.path.join(HERE, 'kakao_sets')
API_KEY_FILE = os.path.join(HERE, 'openai_api_key.txt')
DEFAULT_PORT = 5008
REQUEST_TTL = 15.0         # s: an older RtR request is stale (as rtr_bridge.py)
FOLLOWUP_GAP = 3.0         # s between the follow-up messages
MODEL = 'gpt-5.5'
REASONING_EFFORT = 'low'
API_TIMEOUT = 60.0
NO_NAME = '○○○'            # in the messages until the participant has entered a name
NOTICE_DEADLINE = 10       # min after the name is entered: {deadline} in the messages ("오후 3시 25분")

LABELS = ['완료된 작업', '진행중이던 작업', '앞으로 남은 작업']
MAX_SENTENCE_CHARS = 32    # Notion: 줄당 30자 이내 (label excluded, small slack)
TOTAL_CHARS = (0, 80)      # Notion: 3줄 합계 60–80자; no lower bound since the lines only describe the draft

SYSTEM_PROMPT = """당신은 운전 시뮬레이터 실험에서 Ready-to-Resume(RtR) 요약을 쓰는 보조자입니다.
참가자는 자율주행 중 회사 단톡방(카카오톡)의 대화를 정리해 공지를 작성하는 과제(NDRT)를 하다가 곧 운전 제어권을 넘겨받습니다.
인수 후 공지 작성으로 돌아왔을 때 빨리 재개하도록, 현재 공지 초안의 상태를 3줄로 요약해 스마트 안경에 띄웁니다.

## 판정
- 반영 항목: 과제 설명의 항목 중 초안에 해당 내용이 쓰인 것. 값이 맞는지는 판정하지 않습니다 (틀려도 썼으면 반영).
- 항목 이름이 아니라 내용으로 판정합니다. 참가자는 항목을 자기 말로 씁니다: 다른 단어(점심 → 식사, 집합 → 모이는 곳·만나는 장소, 입장권 → 티켓·입장료), 줄임말, 다른 순서, 제목 없이 문장 속에 넣기, 여러 항목을 한 문장에 묶기 모두 반영으로 봅니다.
- 항목의 일부만 썼어도 (예: 집합 시각만 쓰고 장소는 안 씀) 그 항목을 다루기 시작했으면 반영으로 봅니다. 단, 초안 맨 끝에서 쓰다 만 항목은 반영이 아니라 진행중이던 작업으로만 셉니다 (두 곳에 함께 넣지 않음).
- 진행중이던 작업: 초안 맨 끝이 끊긴 문장이면 그 문장이 다루는 항목. 끝이 완결 문장이면 없음.
- 남은 항목: 반영도, 진행중이던 작업도 아닌 항목.

## 말투 (가장 중요)
- 참가자의 초안을 담담하게 서술합니다. 과제의 정답을 아는 말투를 쓰지 않습니다: 값이 맞는지, 무엇이 틀렸는지, 항목이 몇 개 남았는지를 말하지 않습니다.
- 평가하지 않습니다: "반영하셨습니다", "잘", "빠짐없이", "아직 ~ 안 하셨습니다" 금지.
- 명령·지시하지 않습니다: "~하세요", "~해야 합니다", "~부터 쓰세요", "확인하세요" 금지. 완료된 작업과 진행중이던 작업 줄은 상태를 알려 주는 서술문("~이 있습니다", "~하던 중이었습니다")만 씁니다. 앞으로 남은 작업 줄만 아래의 "~을 마저 작성하시면 됩니다." 형식을 씁니다.

## 3줄 작성 규칙
- 완료된 작업: "초안에 A, B, C 내용이 있습니다." (반영 항목 나열). 반영 항목이 없으면 "초안에 아직 쓴 내용이 없습니다."
- 진행중이던 작업: "A 문장을 쓰던 중이었습니다." 진행중이던 작업이 없으면 "마지막으로 A 문장을 마쳤습니다."
- 앞으로 남은 작업: 남은 항목을 모두 나열하지 않습니다 (정답을 아는 것처럼 보임). 과제 설명의 순서로 바로 다음 항목 하나만 들고 "등"을 붙여 "B 등을 마저 작성하시면 됩니다."라고 씁니다. 진행중이던 작업이 있으면 그것부터: "A부터 B 등을 마저 작성하시면 됩니다." 진행중이던 작업 말고 남은 항목이 없으면 "A부터 마저 작성하시면 됩니다." 남은 항목이 하나도 없으면 "작성한 공지를 확인하고 등록하시면 됩니다." 남은 항목이 몇 개인지는 말하지 않습니다.
- 각 줄은 완결된 존댓말 문장 1개, 라벨 제외 30자 이내, 3줄 합계 80자 이내.
- 괄호 보충 금지. 항목은 과제 설명의 짧은 항목 이름으로 부르되, 참가자가 초안에서 그 항목을 다른 단어로 불렀으면 (예: "식사") 참가자의 단어를 씁니다. 단, 값(시각, 장소명 등)이 들어간 말은 쓰지 않습니다.
- 금지: 정답 값(금액, 시각, 날짜, 장소명, 메뉴 등), 계산 결과, 정보 충돌의 해답을 절대 쓰지 않습니다.
- 초안의 오류를 지적하거나 고치라고 하지 않습니다.

예시 (날짜, 장소, 출발, 발표, 자료 마감 반영 / 숙박비 문장 작성 중 / 운영 파트, 저녁 남음):
완료된 작업: 초안에 날짜, 장소, 출발, 발표, 자료 마감 내용이 있습니다.
진행중이던 작업: 숙박비 문장을 쓰던 중이었습니다.
앞으로 남은 작업: 숙박비부터 운영 파트 등을 마저 작성하시면 됩니다."""

OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'reflected_items': {'type': 'array', 'items': {'type': 'string'}},
        'in_progress_item': {'type': 'string', 'description': '하던 항목 이름, 없으면 빈 문자열'},
        'remaining_items': {'type': 'array', 'items': {'type': 'string'}},
        'so_far': {'type': 'string', 'description': '"완료된 작업" 줄의 문장 (라벨 제외)'},
        'current_work': {'type': 'string', 'description': '"진행중이던 작업" 줄의 문장 (라벨 제외)'},
        'after_return': {'type': 'string', 'description': '"앞으로 남은 작업" 줄의 문장 (라벨 제외)'},
    },
    'required': ['reflected_items', 'in_progress_item', 'remaining_items', 'so_far', 'current_work',
                 'after_return'],
    'additionalProperties': False,
}


def load_set(scenario):
    with open(os.path.join(SET_DIR, 'scenario%d.json' % scenario), encoding='utf-8') as handle:
        return json.load(handle)


def _own_address():
    """This laptop's address on the network toward the internet (a UDP socket only picks the
    route, nothing is sent), or None."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('8.8.8.8', 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def _now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')


class KakaoNdrt(object):
    def __init__(self, scenario, port=DEFAULT_PORT, log_dir=None, on_change=None):
        """scenario: which kakao_sets file. log_dir: folder for ndrt.jsonl and rtr.jsonl (None: no
        files). on_change(status): called when the latest RtR request or result changes, e.g. to
        show it in TORApp."""
        self._set = load_set(scenario)
        self._scenario = scenario
        self._lock = threading.Lock()
        self._log_dir = log_dir
        self._on_change = on_change
        self._seq = 1                       # increases with every change the page shows
        self._name = None
        started = datetime.datetime.now()
        self._instance = started.strftime('%y%m%d_%H%M%S_%f')  # a page from an earlier run reloads itself
        self._messages = [{'id': k, 'from': m['from'], 'text': m['text'], 'phase': 1}
                          for k, m in enumerate(self._set['messages'])]
        self._start_clock(started)
        self._draft = ''
        self._notice = None                 # the posted notice: {'text', 'time'}
        self._followup = 'waiting'          # waiting, sending, done
        self._nudged = set()                # indexes of the nudges posted (once each per run)
        # RtR summaries, as rtr_bridge.py
        self._next_id = 1
        self._latest = None                 # latest request dict: id, source, time (monotonic)
        self._result = None                 # latest result dict, with 'since' (monotonic)
        self._reported = None
        self._simulators = set()            # addresses the experiment has called from (_seen_simulator)
        self._running = True
        self._api_key = os.environ.get('OPENAI_API_KEY') or self._read_key()

        ndrt = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlparse(self.path)
                if url.path.startswith(('/rtr/', '/ndrt/info', '/ndrt/mark')):
                    ndrt._seen_simulator(self.client_address[0])
                query = parse_qs(url.query)
                if url.path == '/ndrt/state':
                    self._json(ndrt._state(int(query.get('seq', ['0'])[0] or 0)))
                elif url.path == '/ndrt/followup':
                    self._json({'ok': ndrt.release_followup(query.get('source', ['http'])[0])})
                elif url.path == '/ndrt/nudge':
                    self._json({'ok': ndrt.post_nudge(int(query.get('index', ['-1'])[0]),
                                                      query.get('source', ['http'])[0])})
                elif url.path == '/ndrt/mark':
                    entry = {key: values[0] for key, values in query.items()}
                    if 'lines' in entry:  # the summary the glasses showed, as JSON
                        try:
                            entry['lines'] = json.loads(entry['lines'])
                        except ValueError:
                            pass
                    ndrt.log_ndrt(dict(entry, event='experiment_' + entry.pop('event', 'mark')))
                    self._json({'ok': True})
                elif url.path == '/ndrt/info':
                    self._json({'scenario': ndrt._scenario, 'title': ndrt._set['title'],
                                'followup': ndrt._followup, 'nudges': ndrt.nudge_plan})
                elif url.path == '/rtr/request':
                    self._json({'id': ndrt.request(query.get('source', ['http'])[0])})
                elif url.path == '/rtr/status':
                    self._json(ndrt.status())
                else:
                    self._static(url.path)

            def do_POST(self):
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    body = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                except (ValueError, UnicodeDecodeError):
                    self.send_error(400)
                    return
                path = urlparse(self.path).path
                if path == '/ndrt/name':
                    ndrt._set_name(str(body.get('name', '')).strip())
                elif path == '/ndrt/draft':
                    ndrt._set_draft(str(body.get('text', '')))
                elif path == '/ndrt/post':
                    ndrt._post(str(body.get('text', '')))
                elif path == '/ndrt/event':
                    ndrt.log_ndrt(dict(body, event='page_' + str(body.get('type', 'event'))))
                else:
                    self.send_error(404)
                    return
                self._json({'ok': True})

            def _static(self, path):
                name = 'index.html' if path in ('', '/') else path.lstrip('/')
                full = os.path.normpath(os.path.join(APP_DIR, name))
                if not full.startswith(APP_DIR) or not os.path.isfile(full):
                    self.send_error(404)
                    return
                with open(full, 'rb') as handle:
                    data = handle.read()
                kind = mimetypes.guess_type(full)[0] or 'application/octet-stream'
                if kind.startswith('text/') or kind == 'application/javascript':
                    kind += '; charset=utf-8'
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def _json(self, value):
                data = json.dumps(value, ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # the page polls every second
                pass

        self._server = ThreadingHTTPServer(('', port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name='kakao-ndrt')
        self._thread.daemon = True
        self._thread.start()
        if on_change is not None:  # also report a request that times out
            watcher = threading.Thread(target=self._watch, name='kakao-ndrt-watch')
            watcher.daemon = True
            watcher.start()
        self.log_ndrt({'event': 'start', 'scenario': scenario, 'title': self._set['title']})
        logging.info('NDRT chat (%s): open http://localhost:%d/ in the browser', self._set['title'], port)
        address = _own_address()
        logging.info('Simulator PC: takeover_experiment.py --scenario %d --ndrt %s  (this laptop now; the '
                     'address can change when the Wi-Fi reconnects)', scenario, address or '<this laptop IP>')
        if not self._api_key:
            logging.warning('NDRT chat: no OpenAI API key (OPENAI_API_KEY or %s): no RtR summaries',
                            os.path.basename(API_KEY_FILE))

    @staticmethod
    def _read_key():
        try:
            with open(API_KEY_FILE, encoding='utf-8') as handle:
                return handle.read().strip()
        except OSError:
            return ''

    def _seen_simulator(self, address):
        """Log the first call from the experiment (KakaoNdrtLink) at each address: the check that the
        simulator PC is connected before the drive."""
        with self._lock:
            if address in self._simulators:
                return
            self._simulators.add(address)
        self.log_ndrt({'event': 'simulator_connected', 'address': address})
        logging.info('NDRT chat: the simulator PC is connected (%s)', address)

    # -- the chat ----------------------------------------------------------------

    @property
    def fallback_summary(self):
        """Fixed RtR lines of this set, for when no summary has arrived in time."""
        return list(self._set.get('fallback_summary', []))

    @property
    def followup_released(self):
        return self._followup != 'waiting'

    def _changed_page(self):
        self._seq += 1

    def _fill(self, text):
        return text.replace('{name}', self._name or NO_NAME).replace('{deadline}', self._deadline)

    def _state(self, seq):
        with self._lock:
            if seq == self._seq:
                return {'instance': self._instance, 'seq': self._seq, 'changed': False}
            return {
                'instance': self._instance,
                'seq': self._seq,
                'changed': True,
                'name': self._name,
                'room': self._set['room'],
                'member_count': self._set['member_count'],
                'messages': [dict(m, text=self._fill(m['text'])) for m in self._messages],
                'notice': self._notice,
                'draft': self._draft,
                'placeholder': self._set.get('placeholder'),  # grey template in the empty editor
            }

    def _start_clock(self, now):
        """The chat's clock: the times of the first messages (kakao_sets "t", min before `now`) and
        {deadline} (NOTICE_DEADLINE min after `now`). Set again when the name is entered."""
        for message, source in zip(self._messages, self._set['messages']):
            message['time'] = (now + datetime.timedelta(minutes=source['t'])).isoformat(timespec='seconds')
        deadline = now + datetime.timedelta(minutes=NOTICE_DEADLINE)
        self._deadline = '%s %d시%s' % ('오전' if deadline.hour < 12 else '오후', deadline.hour % 12 or 12,
                                       ' %d분' % deadline.minute if deadline.minute else '')

    def _set_name(self, name):
        if not name:
            return
        with self._lock:
            if self._name is None:  # the participant starts now: the deadline counts from here
                self._start_clock(datetime.datetime.now())
            self._name = name
            self._changed_page()
        self.log_ndrt({'event': 'name', 'name': name})
        logging.info('NDRT chat: participant %s', name)

    def _set_draft(self, text):
        with self._lock:
            if text == self._draft:
                return
            self._draft = text
        self.log_ndrt({'event': 'draft', 'chars': len(text), 'text': text})

    def _post(self, text):
        with self._lock:
            self._draft = text
            self._notice = {'text': text, 'time': _now_iso()}
            self._messages.append({'id': len(self._messages), 'from': None, 'kind': 'notice', 'phase': 0,
                                   'text': '%s님이 공지를 등록했습니다.' % (self._name or NO_NAME),
                                   'time': self._notice['time']})
            self._changed_page()
        self.log_ndrt({'event': 'post', 'chars': len(text), 'text': text})
        logging.info('NDRT chat: notice posted (%d characters)', len(text))

    def release_followup(self, source):
        """The team's follow-up messages, one every FOLLOWUP_GAP s. Once per run; False if already."""
        with self._lock:
            if self._followup != 'waiting':
                return False
            self._followup = 'sending'
        self.log_ndrt({'event': 'followup_release', 'source': source})
        logging.info('NDRT chat: follow-up messages start (%s)', source)
        thread = threading.Thread(target=self._send_followup, name='kakao-ndrt-followup')
        thread.daemon = True
        thread.start()
        return True

    def _nudges(self):
        """kakao_sets "nudges" (during the pre-alert) then "late_nudges" (after the lane 2 hazard),
        each with 'when': 'prealert' or 'hazard'. A nudge's index is its place in this list."""
        return ([dict(n, when='prealert') for n in self._set.get('nudges', [])] +
                [dict(n, when='hazard') for n in self._set.get('late_nudges', [])])

    @property
    def nudge_plan(self):
        """For the experiment: [{'after': s, 'when': 'prealert' or 'hazard'}, ...] by index."""
        return [{'after': float(n['after']), 'when': n['when']} for n in self._nudges()]

    def post_nudge(self, index, source):
        """Post nudge `index` (a team member pressing for the notice) to the room. The experiment
        plays the KakaoTalk sound on the simulator PC. Once per index per run; False if already
        posted or no such nudge."""
        nudges = self._nudges()
        with self._lock:
            if not 0 <= index < len(nudges) or index in self._nudged:
                return False
            self._nudged.add(index)
            nudge = nudges[index]
            self._messages.append({'id': len(self._messages), 'from': nudge['from'], 'text': nudge['text'],
                                   'phase': 'nudge', 'time': _now_iso()})
            self._changed_page()
        self.log_ndrt({'event': 'nudge', 'index': index, 'source': source, 'from': nudge['from'],
                       'text': self._fill(nudge['text'])})
        logging.info('NDRT chat: nudge %d posted (%s)', index, source)
        return True

    def next_nudge(self):
        """Index of the first nudge not posted yet, or None."""
        with self._lock:
            return next((k for k in range(len(self._nudges())) if k not in self._nudged), None)

    def _send_followup(self):
        for k, message in enumerate(self._set['followup']):
            if k:
                time.sleep(FOLLOWUP_GAP)
            if not self._running:
                return
            with self._lock:
                entry = {'id': len(self._messages), 'from': message['from'], 'text': message['text'],
                         'phase': 2, 'time': _now_iso()}
                self._messages.append(entry)
                self._changed_page()
            self.log_ndrt({'event': 'followup_message', 'index': k, 'from': message['from'],
                           'text': self._fill(message['text'])})
        with self._lock:
            self._followup = 'done'

    # -- RtR summaries (the interface of rtr_bridge.py) ----------------------------

    def request(self, source):
        """Summarize the draft as it is now (in the background). Returns the request id."""
        with self._lock:
            request = {'id': self._next_id, 'source': source, 'time': time.monotonic(), 'draft': self._draft}
            self._next_id += 1
            self._latest = request
        logging.info('RtR summary requested (#%d, %s)', request['id'], source)
        self.log({'event': 'request', 'id': request['id'], 'source': source})
        self.log_ndrt({'event': 'rtr_request', 'id': request['id'], 'source': source, 'draft': request['draft']})
        self._changed()
        thread = threading.Thread(target=self._summarize, args=(request,), name='kakao-ndrt-rtr')
        thread.daemon = True
        thread.start()
        return request['id']

    def result_since(self, since):
        """Latest result with lines for a request made at time.monotonic() >= since; None if none."""
        with self._lock:
            result = self._result
        if result is None or not result.get('lines') or result['since'] < since:
            return None
        return result

    def status(self):
        """Small summary for TORApp and /rtr/status: id, source, state, lines, error."""
        with self._lock:
            request, result = self._latest, self._result
        if request is None and result is None:
            return {'id': 0, 'state': 'idle', 'source': '', 'lines': [], 'error': ''}
        if request is not None and (result is None or result['since'] < request['time']):  # not answered yet
            state = 'pending' if time.monotonic() - request['time'] < REQUEST_TTL else 'timeout'
            return {'id': request['id'], 'state': state, 'source': request['source'], 'lines': [], 'error': ''}
        return {'id': result['request_id'] or 0, 'state': 'error' if result.get('error') else 'done',
                'source': result['source'], 'lines': result.get('lines') or [], 'error': result.get('error') or ''}

    def _task_context(self):
        with self._lock:
            released = 2 if self._followup != 'waiting' else 1
        items = [item for item in self._set['items'] if item['phase'] <= released]
        lines = ['과제: ' + self._set['task'], '', '반영 항목 (항목 이름 / 내용):']
        lines += ['- %s: %s' % (item['name'], item['answer']) for item in items]
        return '\n'.join(lines)

    def _summarize(self, request):
        started = time.monotonic()
        entry = {'request_id': request['id'], 'source': request['source'], 'model': MODEL,
                 'draft': request['draft']}
        try:
            if not self._api_key:
                raise RuntimeError('OpenAI API 키 없음 (OPENAI_API_KEY 또는 %s)' % os.path.basename(API_KEY_FILE))
            parsed, usage = self._call_llm(request['draft'])
            sentences = [parsed['so_far'].strip(), parsed['current_work'].strip(), parsed['after_return'].strip()]
            entry.update({
                'lines': ['%s: %s' % (label, sentence) for label, sentence in zip(LABELS, sentences)],
                'analysis': {key: parsed[key] for key in ('reflected_items', 'in_progress_item', 'remaining_items')},
                'warnings': self._check_rules(sentences),
                'usage': usage,
            })
        except Exception as error:  # pylint: disable=broad-except
            entry['error'] = str(error)
        entry['latency_s'] = round(time.monotonic() - started, 2)
        self._receive(request, entry)

    def _call_llm(self, draft):
        user = '<task>\n%s\n</task>\n\n<draft>\n%s\n</draft>\n\n위 공지 초안의 RtR 3줄 요약을 작성하세요.' % (
            self._task_context(), draft or '(아직 쓴 내용 없음)')
        body = {
            'model': MODEL,
            'max_completion_tokens': 4000,  # reasoning tokens count too
            'messages': [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_schema',
                                'json_schema': {'name': 'rtr_summary', 'strict': True, 'schema': OUTPUT_SCHEMA}},
        }
        if REASONING_EFFORT:
            body['reasoning_effort'] = REASONING_EFFORT
        http = urllib.request.Request('https://api.openai.com/v1/chat/completions',
                                      data=json.dumps(body).encode('utf-8'), method='POST',
                                      headers={'Content-Type': 'application/json',
                                               'Authorization': 'Bearer ' + self._api_key})
        try:
            with urllib.request.urlopen(http, timeout=API_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')[:300]
            raise RuntimeError('ChatGPT 연결 실패 (%d): %s' % (error.code, detail))
        except (urllib.error.URLError, OSError) as error:
            raise RuntimeError('ChatGPT 연결 실패 (인터넷 연결 확인): %s' % error)
        choice = data['choices'][0]
        if choice['message'].get('refusal'):
            raise RuntimeError('요청이 거절됨: %s' % choice['message']['refusal'])
        if choice.get('finish_reason') == 'length':
            raise RuntimeError('응답이 max_completion_tokens에서 잘림')
        return json.loads(choice['message']['content']), data.get('usage')

    def _check_rules(self, sentences):
        warnings = ['%s 줄 %d자 (30자 초과)' % (LABELS[k], len(s)) for k, s in enumerate(sentences)
                    if len(s) > MAX_SENTENCE_CHARS]
        total = sum(len(s) for s in sentences)
        if not TOTAL_CHARS[0] <= total <= TOTAL_CHARS[1]:
            warnings.append('3줄 합계 %d자 (%d–%d자 밖)' % (total, TOTAL_CHARS[0], TOTAL_CHARS[1]))
        warnings += ['금지어 포함: "%s"' % term for term in self._set.get('banned_terms', [])
                     if any(term in s for s in sentences)]
        return warnings

    def _receive(self, request, entry):
        stored = {'request_id': request['id'], 'source': request['source'], 'since': request['time'],
                  'lines': entry.get('lines') or [], 'error': entry.get('error')}
        with self._lock:
            self._result = stored
        if stored['error']:
            logging.warning('RtR summary #%d failed: %s', request['id'], stored['error'])
        else:
            logging.info('RtR summary #%d (%s, %.1f s): %s', request['id'], request['source'], entry['latency_s'],
                         ' / '.join(stored['lines']))
            for warning in entry.get('warnings') or []:
                logging.warning('RtR summary #%d: %s', request['id'], warning)
        self.log(dict(entry, event='result', seconds=entry['latency_s']))
        # the generated summary in the chat log too, next to the draft it summarizes
        self.log_ndrt({'event': 'rtr_result', 'id': request['id'], 'source': request['source'],
                       'lines': entry.get('lines'), 'analysis': entry.get('analysis'),
                       'warnings': entry.get('warnings'), 'error': entry.get('error'),
                       'seconds': entry['latency_s']})
        self._changed()

    def _changed(self):
        if self._on_change is None:
            return
        status = self.status()
        if status != self._reported:
            self._reported = status
            self._on_change(status)

    def _watch(self):
        while self._running:
            time.sleep(1.0)
            self._changed()

    # -- logs --------------------------------------------------------------------

    def _append(self, filename, entry):
        if self._log_dir is None:
            return
        entry = dict(entry, wall_time=datetime.datetime.now().isoformat(timespec='milliseconds'))
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            with open(os.path.join(self._log_dir, filename), 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except OSError as error:
            logging.error('NDRT chat: could not write %s: %s', filename, error)

    def log(self, entry):
        """One line in rtr.jsonl (the RtR summaries, as rtr_bridge.py)."""
        self._append('rtr.jsonl', entry)

    def log_ndrt(self, entry):
        """One line in ndrt.jsonl (the chat)."""
        self._append('ndrt.jsonl', entry)

    def close(self):
        with self._lock:
            final = {'event': 'end', 'name': self._name, 'draft': self._draft, 'notice': self._notice,
                     'followup': self._followup}
        self.log_ndrt(final)
        self._running = False
        self._server.shutdown()
        self._server.server_close()


class KakaoNdrtLink(object):
    """The experiment's side of the NDRT chat on the NDRT laptop (KakaoNdrt there), over HTTP: the
    same calls as KakaoNdrt (release_followup, followup_released, request, result_since, status,
    log), plus mark() for the experiment's events. Nothing here waits for the laptop: every call
    goes out on a thread, and the RtR status is polled in the background."""

    POLL = 0.5         # s between /rtr/status polls
    TIMEOUT = 2.0      # s per HTTP call

    def __init__(self, address, scenario, default_port=DEFAULT_PORT, log_dir=None, on_change=None):
        """address: 'IP' or 'IP:PORT' of the NDRT laptop."""
        host, _, port = address.partition(':')
        self._base = 'http://%s:%d' % (host, int(port) if port else default_port)
        self._scenario = scenario
        self._log_dir = log_dir
        self._on_change = on_change
        self._lock = threading.Lock()
        self._released = False
        self._pending = None        # our latest request: {'id' (once the laptop answered), 'source', 'time'}
        self._result = None         # as KakaoNdrt
        self._status = {'id': 0, 'state': 'idle', 'source': '', 'lines': [], 'error': ''}
        self._reported = None
        self._online = None
        self._running = True
        self.nudges = []            # [{'after', 'when'}] by index, from the laptop's /ndrt/info
        thread = threading.Thread(target=self._poll, name='kakao-ndrt-link')
        thread.daemon = True
        thread.start()
        logging.info('NDRT chat on the NDRT laptop: %s', self._base)

    def _get(self, path, **query):
        url = self._base + path
        if query:
            url += '?' + urllib.parse.urlencode(query)
        with urllib.request.urlopen(url, timeout=self.TIMEOUT) as response:
            return json.loads(response.read().decode('utf-8'))

    def _later(self, function, *args):
        thread = threading.Thread(target=function, args=args, name='kakao-ndrt-link-call')
        thread.daemon = True
        thread.start()

    @property
    def followup_released(self):
        return self._released

    def release_followup(self, source):
        """The team's follow-up messages, once; False if already released."""
        if self._released:
            return False
        self._released = True
        self._later(self._send_followup, source)
        return True

    def _send_followup(self, source):
        try:
            self._get('/ndrt/followup', source=source)
            logging.info('NDRT chat: follow-up messages released (%s)', source)
        except (OSError, ValueError) as error:
            self._released = False  # tried again next frame
            logging.warning('NDRT chat: could not release the follow-up messages: %s', error)

    def post_nudge(self, index, source):
        """Post nudge `index` to the room on the laptop (it ignores one already posted)."""
        self._later(self._send_nudge, index, source)

    def _send_nudge(self, index, source):
        try:
            self._get('/ndrt/nudge', index=index, source=source)
        except (OSError, ValueError) as error:
            logging.warning('NDRT chat: could not post nudge %d: %s', index, error)

    def mark(self, event, **fields):
        """Log the experiment's `event` in the laptop's ndrt.jsonl, on its clock."""
        fields = {key: value for key, value in fields.items() if value is not None}
        self._later(self._send_mark, dict(fields, event=event))

    def _send_mark(self, fields):
        try:
            self._get('/ndrt/mark', **fields)
        except (OSError, ValueError) as error:
            logging.warning('NDRT chat: could not log %s on the laptop: %s', fields['event'], error)

    # -- RtR summaries -----------------------------------------------------------

    def request(self, source):
        with self._lock:
            self._pending = {'id': None, 'source': source, 'time': time.monotonic()}
            pending = self._pending
        logging.info('RtR summary requested from the NDRT laptop (%s)', source)
        self.log({'event': 'request', 'source': source})
        self._later(self._send_request, pending)

    def _send_request(self, pending):
        try:
            pending['id'] = self._get('/rtr/request', source=pending['source'])['id']
        except (OSError, ValueError, KeyError) as error:
            logging.warning('RtR summary request failed: %s', error)
            with self._lock:
                self._result = {'request_id': None, 'source': pending['source'], 'since': pending['time'],
                                'lines': [], 'error': 'NDRT laptop: %s' % error}

    def result_since(self, since):
        with self._lock:
            result = self._result
        if result is None or not result.get('lines') or result['since'] < since:
            return None
        return result

    def status(self):
        with self._lock:
            return dict(self._status)

    def _poll(self):
        while self._running:
            try:
                status = self._get('/rtr/status')
                online = True
            except (OSError, ValueError) as error:
                status = {'id': 0, 'state': 'error', 'source': '', 'lines': [], 'error': 'NDRT laptop: %s' % error}
                online = False
            if online != self._online:
                self._online = online
                if online:
                    self._check_scenario()
                else:
                    logging.warning('NDRT chat: the NDRT laptop (%s) is not reachable', self._base)
            with self._lock:
                self._status = status
                pending = self._pending
                if (pending is not None and pending['id'] is not None and status.get('id') == pending['id']
                        and status.get('state') in ('done', 'error')):
                    self._pending = None
                    self._result = {'request_id': pending['id'], 'source': pending['source'],
                                    'since': pending['time'], 'lines': status.get('lines') or [],
                                    'error': status.get('error') or None}
                    result = self._result
                else:
                    result = None
            if result is not None:
                logging.info('RtR summary #%s: %s', result['request_id'], result['error'] or ' / '.join(result['lines']))
                self.log({'event': 'result', 'request_id': result['request_id'], 'lines': result['lines'],
                          'error': result['error'], 'seconds': round(time.monotonic() - result['since'], 2)})
            if self._on_change is not None and status != self._reported:
                self._reported = status
                self._on_change(status)
            time.sleep(self.POLL)

    def _check_scenario(self):
        try:
            info = self._get('/ndrt/info')
        except (OSError, ValueError):
            return
        self.nudges = info.get('nudges', [])
        if info.get('scenario') != self._scenario:
            logging.warning('NDRT chat: the laptop runs scenario %s (%s), the drive is scenario %d',
                            info.get('scenario'), info.get('title'), self._scenario)
        else:
            logging.info('NDRT chat: connected to the NDRT laptop (%s)', info.get('title'))

    def log(self, entry):
        """One line in the experiment's rtr.jsonl (the laptop keeps its own). The summary the
        glasses showed ('shown': the LLM's or the fixed fallback) goes to the laptop's ndrt.jsonl too."""
        if entry.get('event') == 'shown':
            self.mark('rtr_shown', trial=entry.get('trial'), source=entry.get('source'),
                      request_id=entry.get('request_id'), lines=json.dumps(entry.get('lines'), ensure_ascii=False))
        if self._log_dir is None:
            return
        entry = dict(entry, wall_time=datetime.datetime.now().isoformat(timespec='milliseconds'))
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            with open(os.path.join(self._log_dir, 'rtr.jsonl'), 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except OSError as error:
            logging.error('NDRT chat: could not write rtr.jsonl: %s', error)

    def close(self):
        self._running = False


def main():
    argparser = argparse.ArgumentParser(description='NDRT group chat, on the NDRT laptop')
    argparser.add_argument('--scenario', type=int, default=1, help='kakao_sets/scenario<N>.json (default: 1)')
    argparser.add_argument('--port', type=int, default=DEFAULT_PORT, help='HTTP port (default: %d)' % DEFAULT_PORT)
    argparser.add_argument('--followup-after', metavar='SEC', type=float, default=None,
                           help='release the follow-up messages this many seconds after the start '
                                '(else: GET /ndrt/followup, or press Enter)')
    argparser.add_argument('--log-dir', metavar='DIR',
                           help='write ndrt.jsonl and rtr.jsonl here (default: Data/YYMMDD_HHMMSS_ndrt)')
    argparser.add_argument('--no-log', action='store_true', help='no log files')
    args = argparser.parse_args()
    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)
    log_dir = args.log_dir or os.path.normpath(os.path.join(
        LOG_ROOT, datetime.datetime.now().strftime('%y%m%d_%H%M%S') + '_ndrt'))
    ndrt = KakaoNdrt(args.scenario, args.port, None if args.no_log else log_dir)
    if not args.no_log:
        logging.info('NDRT logs: %s', log_dir)
    if args.followup_after is not None:
        timer = threading.Timer(args.followup_after, ndrt.release_followup, args=('timer',))
        timer.daemon = True
        timer.start()
    try:
        print('Enter: follow-up messages, n + Enter: next nudge, s + Enter: RtR summary, Ctrl+C: quit')
        while True:
            try:
                line = input()
            except EOFError:  # no console: wait for Ctrl+C
                while True:
                    time.sleep(1.0)
            if line.strip() == 's':
                ndrt.request('console')
            elif line.strip() == 'n':
                index = ndrt.next_nudge()
                if index is None:
                    print('No nudges left')
                else:
                    ndrt.post_nudge(index, 'console')
            else:
                ndrt.release_followup('console')
    except KeyboardInterrupt:
        pass
    finally:
        ndrt.close()


if __name__ == '__main__':
    main()
