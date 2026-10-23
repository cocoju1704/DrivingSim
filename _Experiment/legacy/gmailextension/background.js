// Service worker: sends the Gmail draft to the OpenAI API (ChatGPT) and returns the 3-B RtR summary.
// Raw fetch instead of the openai package because the extension has no bundler step.
import { loadSettings } from './defaults.js';

const LABELS = ['완료된 작업', '진행중이던 작업', '앞으로 남은 작업'];
const MAX_SENTENCE_CHARS = 32;   // Notion: 줄당 30자 이내 (label excluded, small slack)
const TOTAL_CHARS = [60, 80];    // Notion: 3줄 합계 60–80자

const SYSTEM_PROMPT = `당신은 운전 시뮬레이터 실험에서 Ready-to-Resume(RtR) 요약을 쓰는 보조자입니다.
참가자는 자율주행 중 이메일 작성 과제(NDRT)를 하다가 곧 운전 제어권을 넘겨받습니다.
인수 후 이메일로 돌아왔을 때 빨리 재개하도록, 현재 초안의 상태를 3줄로 요약해 스마트 안경에 띄웁니다.

## 판정
- 반영 항목: 과제 설명의 항목 중 초안에 해당 내용이 쓰인 것. 값이 맞는지는 판정하지 않습니다 (틀려도 썼으면 반영).
- 진행중이던 작업: 초안 맨 끝이 끊긴 문장이면 그 문장이 다루는 항목. 끝이 완결 문장이면 없음.
- 남은 항목: 반영도, 진행중이던 작업도 아닌 항목.

## 3줄 작성 규칙
- 완료된 작업: 반영한 항목 이름을 나열하고 "~을 반영하셨습니다."로 끝냅니다. 반영 항목이 없으면 그렇다고 씁니다.
- 진행중이던 작업: "~ 문장을 쓰다 멈추셨습니다." 진행중이던 작업이 없으면 마지막으로 마친 항목을 말합니다.
- 앞으로 남은 작업: 진행중이던 작업부터 이어서 쓰고 남은 항목을 쓰라는 다음 행동. 남은 것이 없으면 검토·발송을 안내합니다.
- 각 줄은 완결된 존댓말 문장 1개, 라벨 제외 30자 이내, 3줄 합계 60–80자.
- 괄호 보충 금지. 항목은 과제 설명의 짧은 항목 이름(날짜, 장소, 출발, 숙박비, 발표, 자료 마감, 저녁 등)으로 부릅니다.
- 금지: 남은 항목이나 하던 항목의 정답 값(금액, 시각, 날짜, 장소명, 메뉴 등)을 절대 쓰지 않습니다. 계산 결과나 정보 충돌의 해답도 쓰지 않습니다. 상태와 다음 행동만 씁니다.
- 초안의 오류를 지적하거나 고치라고 하지 않습니다.

예시 (날짜, 장소, 출발, 발표, 자료 마감 반영 / 숙박비 문장 작성 중 / 저녁 남음):
완료된 작업: 날짜, 장소, 출발, 발표, 자료 마감을 반영하셨습니다.
진행중이던 작업: 숙박비 문장을 쓰다 멈추셨습니다.
앞으로 남은 작업: 숙박비부터 이어서 쓰고, 저녁 안내를 마저 쓰시면 됩니다.`;

const OUTPUT_SCHEMA = {
  type: 'object',
  properties: {
    reflected_items: { type: 'array', items: { type: 'string' } },
    in_progress_item: { type: 'string', description: '하던 항목 이름, 없으면 빈 문자열' },
    remaining_items: { type: 'array', items: { type: 'string' } },
    so_far: { type: 'string', description: '"완료된 작업" 줄의 문장 (라벨 제외)' },
    current_work: { type: 'string', description: '"진행중이던 작업" 줄의 문장 (라벨 제외)' },
    after_return: { type: 'string', description: '"앞으로 남은 작업" 줄의 문장 (라벨 제외)' },
  },
  required: ['reflected_items', 'in_progress_item', 'remaining_items', 'so_far', 'current_work', 'after_return'],
  additionalProperties: false,
};

async function callLLM(settings, subject, body) {
  const userContent = `<task>
${settings.taskContext}
</task>

<draft>
제목: ${subject || '(없음)'}

${body || '(본문 없음)'}
</draft>

위 초안의 RtR 3줄 요약을 작성하세요.`;

  const request = {
    model: settings.model,
    max_completion_tokens: 4000, // reasoning tokens count too
    messages: [
      { role: 'system', content: SYSTEM_PROMPT },
      { role: 'user', content: userContent },
    ],
    response_format: {
      type: 'json_schema',
      json_schema: { name: 'rtr_summary', strict: true, schema: OUTPUT_SCHEMA },
    },
  };
  // reasoning models only (gpt-5 family, o-series); '' leaves it out for the others
  if (settings.effort) request.reasoning_effort = settings.effort;

  let res;
  try {
    res = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${settings.apiKey}`,
      },
      body: JSON.stringify(request),
      signal: AbortSignal.timeout(60000),
    });
  } catch (err) {
    throw new Error(`ChatGPT 연결 실패: OpenAI 서버에 접속하지 못함 (인터넷 연결 확인) - ${err.message || err}`);
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const hint = { 401: 'API 키가 틀렸거나 만료됨', 403: '이 키로 쓸 수 없는 모델', 404: '모델 이름 확인',
      429: '요청 한도 또는 잔액 초과' }[res.status] || res.statusText;
    throw new Error(`ChatGPT 연결 실패 (${res.status} ${hint}): ${data?.error?.message || ''}`);
  }
  const choice = data.choices?.[0];
  if (choice?.message?.refusal) throw new Error(`요청이 거절됨: ${choice.message.refusal}`);
  if (choice?.finish_reason === 'length') throw new Error('응답이 max_completion_tokens에서 잘림');
  const text = choice?.message?.content;
  if (!text) throw new Error('응답에 내용이 없음');
  return { parsed: JSON.parse(text), usage: data.usage, model: data.model, apiRequestId: res.headers.get('x-request-id') };
}

// ---- rtr_bridge.py (takeover_experiment.py) ----

function bridgeUrl(settings, path) {
  return settings.bridgeUrl ? settings.bridgeUrl.replace(/\/+$/, '') + path : null;
}

let bridgeError = null; // last poll error, kept in storage for the options page

async function setBridgeError(error) {
  if (error === bridgeError) return;
  bridgeError = error;
  await chrome.storage.local.set({ bridgeError: error });
}

async function pollBridge() {
  const settings = await loadSettings();
  const url = bridgeUrl(settings, '/rtr/next');
  if (!url) return null;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
    const data = await res.json();
    await setBridgeError(null);
    return data.request;
  } catch (err) {
    await setBridgeError(`${url}: ${err.message || err}`);
    return null;
  }
}

// Returns how the result reached the experiment PC: 'ok', 'off' (no bridge address) or the error.
async function postResult(result) {
  const settings = await loadSettings();
  const url = bridgeUrl(settings, '/rtr/result');
  if (!url) return 'off';
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(result),
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await setBridgeError(null);
    return 'ok';
  } catch (err) {
    const error = `${url}: ${err.message || err}`;
    await setBridgeError(error);
    return error;
  }
}

// Toolbar icon badge: what the last summary did (also for requests from the experiment / TORApp,
// which show nothing on the Gmail screen).
function badge(text, color, title) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setTitle({ title: `NDRT RtR 요약: ${title}` });
}

async function addLog(entry) {
  const { logs = [] } = await chrome.storage.local.get('logs');
  logs.push(entry);
  await chrome.storage.local.set({ logs });
}

function checkRules(sentences, bannedTerms) {
  const warnings = [];
  sentences.forEach((s, i) => {
    if (s.length > MAX_SENTENCE_CHARS) warnings.push(`${LABELS[i]} 줄 ${s.length}자 (30자 초과)`);
  });
  const total = sentences.reduce((n, s) => n + s.length, 0);
  if (total < TOTAL_CHARS[0] || total > TOTAL_CHARS[1]) warnings.push(`3줄 합계 ${total}자 (60–80자 밖)`);
  for (const term of bannedTerms.split(',').map((t) => t.trim()).filter(Boolean)) {
    if (sentences.some((s) => s.includes(term))) warnings.push(`금지어 포함: "${term}"`);
  }
  return warnings;
}

// request: {id, source} from the bridge, null for the extension's own button
async function summarize(subject, body, request) {
  const settings = await loadSettings();
  if (!settings.apiKey) throw new Error('옵션 페이지에서 OpenAI API 키를 입력하세요.');

  const started = Date.now();
  const { parsed, usage, model, apiRequestId } = await callLLM(settings, subject, body);
  const sentences = [parsed.so_far, parsed.current_work, parsed.after_return].map((s) => s.trim());
  const lines = sentences.map((s, i) => `${LABELS[i]}: ${s}`);

  const entry = {
    time: new Date().toISOString(),
    latencyMs: Date.now() - started,
    scenario: settings.scenario,
    request_id: request?.id ?? null,
    source: request?.source ?? 'extension',
    model,
    apiRequestId,
    subject,
    body,
    analysis: {
      reflected_items: parsed.reflected_items,
      in_progress_item: parsed.in_progress_item,
      remaining_items: parsed.remaining_items,
    },
    lines,
    warnings: checkRules(sentences, settings.bannedTerms),
    usage,
  };

  entry.bridge = await postResult(entry); // the experiment shows these lines on the glasses
  await addLog(entry);
  await chrome.storage.local.set({ lastResult: entry });
  // only the extension's own button shows the panel: requests from the experiment or TORApp
  // must not put the summary on the participant's screen
  return { ...entry, showPanel: settings.showPanel && !request };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === 'settings') {
    loadSettings().then((s) => sendResponse({ showButton: s.showButton }));
    return true;
  }
  if (msg.type === 'poll') {
    pollBridge().then((request) => sendResponse({ request }));
    return true;
  }
  if (msg.type === 'fail') { // a bridge request the tab could not answer (no compose window)
    postResult({ request_id: msg.request.id, source: msg.request.source, error: msg.error })
      .then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg.type !== 'summarize') return false;
  const source = msg.request?.source ?? 'extension';
  badge('…', '#5f6368', `요청 중 (${source})`);
  summarize(msg.subject, msg.body, msg.request || null)
    .then((result) => {
      const pcOk = result.bridge === 'ok' || result.bridge === 'off';
      const pc = { ok: '실험 PC 전송 성공', off: '실험 PC 연결 꺼짐' }[result.bridge] || '실험 PC 전송 실패';
      badge(pcOk ? 'OK' : 'PC!', pcOk ? '#188038' : '#e37400',
        `${new Date().toLocaleTimeString()} 완료 (${(result.latencyMs / 1000).toFixed(1)}초, ${source}), ${pc}`);
      sendResponse({ ok: true, result });
    })
    .catch(async (err) => {
      const error = String(err.message || err);
      badge('ERR', '#d93025', `${new Date().toLocaleTimeString()} 실패: ${error}`);
      await addLog({ time: new Date().toISOString(), request_id: msg.request?.id ?? null, source, error });
      if (msg.request) await postResult({ request_id: msg.request.id, source: msg.request.source, error });
      sendResponse({ ok: false, error });
    });
  return true; // async response
});

function trigger(tab) {
  if (tab?.id && tab.url?.startsWith('https://mail.google.com/')) {
    chrome.tabs.sendMessage(tab.id, { type: 'trigger' });
  }
}

chrome.commands.onCommand.addListener((command, tab) => {
  if (command === 'summarize') trigger(tab);
});

// Toolbar icon = manual trigger for the experimenter (no button on the participant's screen needed).
// Settings: right-click the icon -> Options.
chrome.action.onClicked.addListener((tab) => {
  if (tab?.url?.startsWith('https://mail.google.com/')) trigger(tab);
  else chrome.runtime.openOptionsPage();
});
