import { DEFAULT_SETTINGS, loadSettings } from './defaults.js';

const $ = (id) => document.getElementById(id);
const FIELDS = ['apiKey', 'model', 'effort', 'taskContext', 'bannedTerms', 'bridgeUrl'];

function flash(text) {
  $('status').textContent = text;
  setTimeout(() => { $('status').textContent = ''; }, 2000);
}

async function load() {
  const s = await loadSettings();
  for (const f of FIELDS) $(f).value = s[f];
  $('scenario').value = String(s.scenario);
  $('showPanel').checked = s.showPanel;
  $('showButton').checked = s.showButton;
  showLast();
  showBridge();
}

async function showBridge() {
  const { bridgeError } = await chrome.storage.local.get('bridgeError');
  $('bridgeStatus').textContent = bridgeError
    ? `연결 오류: ${bridgeError}`
    : 'Gmail 작성 창이 열려 있는 동안 0.5초마다 요청을 확인합니다.';
}

async function showLast() {
  const { lastResult } = await chrome.storage.local.get('lastResult');
  if (!lastResult) return;
  const warn = lastResult.warnings.length ? `\n\n경고: ${lastResult.warnings.join(' / ')}` : '';
  const pc = { ok: '실험 PC 전송 성공', off: '실험 PC 연결 꺼짐' }[lastResult.bridge] || `실험 PC 전송 실패: ${lastResult.bridge}`;
  $('last').textContent = `${lastResult.time} (${lastResult.latencyMs} ms, ${lastResult.source}, ${pc})\n\n${lastResult.lines.join('\n')}${warn}`;
}

function download(filename, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  chrome.downloads.download({ url, filename, saveAs: true }, () => URL.revokeObjectURL(url));
}

$('save').addEventListener('click', async () => {
  const values = Object.fromEntries(FIELDS.map((f) => [f, $(f).value.trim()]));
  values.scenario = Number($('scenario').value);
  values.showPanel = $('showPanel').checked;
  values.showButton = $('showButton').checked;
  await chrome.storage.local.set(values);
  flash('저장됨');
});

$('reset').addEventListener('click', () => {
  $('taskContext').value = DEFAULT_SETTINGS.taskContext;
  $('bannedTerms').value = DEFAULT_SETTINGS.bannedTerms;
  flash('기본값을 채웠습니다. 저장을 누르세요.');
});

// Same layout as _Experiment/NDRT_scripts/scenario<N>_NDRT_summary.txt
$('exportTxt').addEventListener('click', async () => {
  const { lastResult } = await chrome.storage.local.get('lastResult');
  if (!lastResult) return flash('결과 없음');
  const header = [
    '# 출처: gmail_rtr_extension (OpenAI API 생성)',
    `# 생성: ${lastResult.time}, 모델 ${lastResult.model}`,
    '# 형식: 줄마다 "라벨: 완결된 존댓말 문장", 줄당 30자 이내 (#으로 시작하는 줄은 표시하지 않음)',
    '# 3-B NDRT 요약형 (Ready-to-Resume 3요소), 운전자 답변 없음',
  ];
  const text = [...header, ...lastResult.lines].join('\n') + '\n';
  download(`scenario${lastResult.scenario}_NDRT_summary.txt`, text, 'text/plain');
});

$('exportLogs').addEventListener('click', async () => {
  const { logs = [] } = await chrome.storage.local.get('logs');
  download(`rtr_logs_${Date.now()}.json`, JSON.stringify(logs, null, 2), 'application/json');
});

$('clearLogs').addEventListener('click', async () => {
  if (!confirm('저장된 요약 로그를 모두 지울까요?')) return;
  await chrome.storage.local.remove(['logs', 'lastResult']);
  $('last').textContent = '(없음)';
  flash('로그 삭제됨');
});

chrome.storage.onChanged.addListener((changes) => {
  if (changes.lastResult) showLast();
  if (changes.bridgeError) showBridge();
});

load();
