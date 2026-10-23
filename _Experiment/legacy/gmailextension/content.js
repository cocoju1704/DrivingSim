// Gmail content script: reads the compose window being written and shows the RtR summary.
(() => {
  const BODY_SELECTOR = 'div[contenteditable="true"][g_editable="true"]';
  let lastBody = null; // compose body the participant last typed in

  document.addEventListener('focusin', (e) => {
    const body = e.target.closest?.(BODY_SELECTOR);
    if (body) lastBody = body;
  });

  function currentCompose() {
    const body = (lastBody && lastBody.isConnected) ? lastBody : document.querySelector(BODY_SELECTOR);
    if (!body) return null;
    // Subject box lives in the same compose form as the body.
    const form = body.closest('form') || body.closest('div[role="dialog"]') || document;
    const subject = form.querySelector('input[name="subjectbox"]')?.value || '';
    return { subject, body: body.innerText.replace(/ /g, ' ').trimEnd() };
  }

  // ---- UI ----
  const button = document.createElement('button');
  button.id = 'rtr-button';
  button.textContent = 'RtR 요약';
  button.title = '작성 중인 메일을 ChatGPT에 보내 3줄 요약 (Alt+Shift+S)';
  button.addEventListener('mousedown', (e) => e.preventDefault()); // keep caret in the draft
  button.addEventListener('click', run);

  const panel = document.createElement('div');
  panel.id = 'rtr-panel';
  panel.hidden = true;

  let showButton = true;
  chrome.runtime.sendMessage({ type: 'settings' }).then((s) => {
    showButton = s.showButton;
    mount();
  });

  function mount() {
    if (!document.body) return;
    if (!button.isConnected) document.body.appendChild(button);
    if (!panel.isConnected) document.body.appendChild(panel);
    button.hidden = !showButton || !document.querySelector(BODY_SELECTOR);
  }
  new MutationObserver(mount).observe(document.documentElement, { childList: true, subtree: true });
  mount();

  function showPanel(contentNodes) {
    panel.replaceChildren(...contentNodes);
    const close = document.createElement('button');
    close.className = 'rtr-close';
    close.textContent = '×';
    close.addEventListener('click', () => { panel.hidden = true; });
    panel.prepend(close);
    panel.hidden = false;
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  const BRIDGE_TEXT = { ok: '실험 PC 전송 성공', off: '실험 PC 연결 꺼짐 (옵션의 브리지 주소 비어 있음)' };

  // Status lines always; the summary itself only with the "show result" option.
  function render(result) {
    const nodes = [el('div', 'rtr-ok', `✓ ChatGPT 연결 성공 · ${(result.latencyMs / 1000).toFixed(1)}초 · ${result.model}`)];
    const bridge = BRIDGE_TEXT[result.bridge];
    nodes.push(el('div', bridge ? 'rtr-ok' : 'rtr-warn', bridge ? `✓ ${bridge}` : `✗ 실험 PC 전송 실패: ${result.bridge} ` +
      '(takeover_experiment.py가 intervention NDRT + format summary로 실행 중인지, 브리지 주소가 맞는지 확인)'));
    if (result.showPanel) {
      for (const line of result.lines) {
        const [label, ...rest] = line.split(': ');
        const row = el('div', 'rtr-line');
        row.append(el('b', null, `${label}: `), rest.join(': '));
        nodes.push(row);
      }
      for (const w of result.warnings) nodes.push(el('div', 'rtr-warn', `⚠ ${w}`));
    }
    nodes.push(el('div', 'rtr-meta', '저장: 확장 프로그램 로그 (옵션 페이지에서 내보내기)' +
      (result.bridge === 'ok' ? ', 실험 PC의 Data/<실행 시각>/rtr.jsonl' : '')));
    return nodes;
  }

  // request: {id, source} from takeover_experiment.py (rtr_bridge.py), null for the button,
  // the toolbar icon or the shortcut. Bridge requests never show anything on this screen.
  let busy = false;
  async function run(request = null) {
    if (busy && !request) return;
    const compose = currentCompose();
    if (!compose) {
      if (request) chrome.runtime.sendMessage({ type: 'fail', request, error: '열려 있는 작성 창이 없음' });
      else showPanel([el('div', 'rtr-warn', '열려 있는 작성 창이 없습니다.')]);
      return;
    }
    busy = true;
    button.disabled = true;
    button.textContent = '요약 중…';
    if (!request) showPanel([el('div', 'rtr-meta', `ChatGPT에 보내는 중… (본문 ${compose.body.length}자)`)]);
    try {
      const res = await chrome.runtime.sendMessage({ type: 'summarize', ...compose, request });
      if (!res.ok) throw new Error(res.error);
      if (!request) showPanel(render(res.result));
    } catch (err) {
      if (!request) showPanel([el('div', 'rtr-warn', `✗ ${err.message || err}`)]);
    } finally {
      busy = false;
      button.disabled = false;
      button.textContent = 'RtR 요약';
    }
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'trigger') run();
  });

  // Ask the experiment for requests every 0.5 s, only while this tab has a compose window
  // (a tab without one would take the request and could not answer it).
  const poller = setInterval(async () => {
    if (!document.querySelector(BODY_SELECTOR)) return;
    try {
      const res = await chrome.runtime.sendMessage({ type: 'poll' });
      if (res?.request) run(res.request);
    } catch (err) {
      clearInterval(poller); // extension reloaded: this old content script is cut off
    }
  }, 500);
})();
