// NDRT group chat page: polls the experiment PC (kakao_ndrt.py) for the chat, sends the notice draft.
(() => {
  'use strict';

  const POLL_MS = 1000;
  const DRAFT_DELAY_MS = 400;     // the draft is sent this long after the last change
  const AVATAR_COLORS = ['#7c9cbf', '#e0a85a', '#8bbf7c', '#c98bb9', '#d77b6f', '#6fb3b8', '#a596d6'];

  const $ = (id) => document.getElementById(id);
  const app = $('app');
  const messagesEl = $('messages');
  const draftEl = $('draft');
  const postBtn = $('post');

  let seq = 0;
  let state = null;
  let shownCount = 0;            // messages rendered so far
  let draftLoaded = false;       // the server's draft is put in the editor once, at the start
  let draftTimer = null;
  let sentDraft = null;
  let nameAsked = false;

  // -- server ------------------------------------------------------------------

  async function send(path, body) {
    try {
      await fetch(path, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        keepalive: true,
      });
    } catch (err) {
      // the next change sends the draft again
    }
  }

  function event(type, extra) {
    send('/ndrt/event', Object.assign({ type, editing: app.classList.contains('editing') }, extra || {}));
  }

  async function poll() {
    try {
      const res = await fetch(`/ndrt/state?seq=${seq}`, { cache: 'no-store' });
      const data = await res.json();
      seq = data.seq;
      if (data.changed) apply(data);
    } catch (err) {
      // experiment PC not reachable: try again
    }
    setTimeout(poll, POLL_MS);
  }

  // -- rendering ---------------------------------------------------------------

  function avatarColor(name) {
    let h = 0;
    for (const ch of name) h = (h * 31 + ch.codePointAt(0)) >>> 0;
    return AVATAR_COLORS[h % AVATAR_COLORS.length];
  }

  function timeText(iso) {
    const d = new Date(iso);
    const h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h < 12 ? '오전' : '오후'} ${h % 12 || 12}:${m}`;
  }

  function dateText(d) {
    const days = ['일', '월', '화', '수', '목', '금', '토'];
    return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 ${days[d.getDay()]}요일`;
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function render(messages) {
    messagesEl.textContent = '';
    if (messages.length) {
      const divider = el('div', 'date-divider');
      divider.appendChild(el('span', '', dateText(new Date(messages[0].time))));
      messagesEl.appendChild(divider);
    }
    let prev = null;
    for (const m of messages) {
      if (m.kind === 'notice' || !m.from) {
        const sys = el('div', 'system');
        sys.appendChild(el('span', '', m.text));
        messagesEl.appendChild(sys);
        prev = null;
        continue;
      }
      const cont = prev && prev.from === m.from && timeText(prev.time) === timeText(m.time);
      const row = el('div', cont ? 'msg cont' : 'msg');
      const avatar = el('div', 'avatar', m.from.trim().charAt(0));
      avatar.style.background = avatarColor(m.from);
      const body = el('div', 'msg-body');
      body.appendChild(el('div', 'sender', m.from));
      const line = el('div', 'line');
      line.appendChild(el('div', 'bubble', m.text));
      line.appendChild(el('span', 'time', timeText(m.time)));
      body.appendChild(line);
      row.appendChild(avatar);
      row.appendChild(body);
      messagesEl.appendChild(row);
      // the time shows only under the last bubble of a run, as in KakaoTalk
      if (cont && prev.row) prev.row.querySelector('.time').style.visibility = 'hidden';
      prev = Object.assign({ row }, m);
    }
  }

  function nearBottom() {
    return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
  }

  function apply(data) {
    const stick = !state || nearBottom();
    const before = shownCount;
    state = data;
    $('room-name').textContent = data.room;
    $('room-count').textContent = data.member_count;
    document.title = data.room;
    render(data.messages);
    shownCount = data.messages.length;
    if (stick) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    } else if (shownCount > before) {
      $('new-pill').hidden = false;
    }
    const banner = $('notice-banner');
    if (data.notice) {
      banner.hidden = false;
      $('notice-preview').textContent = data.notice.text.split('\n').find((l) => l.trim()) || data.notice.text;
      $('post-state').textContent = `${timeText(data.notice.time)} 등록됨`;
      postBtn.textContent = '수정';
    } else {
      banner.hidden = true;
    }
    if (!draftLoaded) {
      draftLoaded = true;
      if (data.draft && !draftEl.value) draftEl.value = data.draft;
      sentDraft = data.draft;
      updateEditor();
    }
    if (!data.name && !nameAsked) askName();
  }

  // -- name --------------------------------------------------------------------

  function askName() {
    nameAsked = true;
    $('name-dialog').hidden = false;
    $('name-input').focus();
  }

  $('name-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('name-input').value.trim();
    if (!name) return;
    $('name-dialog').hidden = true;
    await send('/ndrt/name', { name });
    seq = 0; // fetch everything again, with the name in the messages
  });

  // -- editor ------------------------------------------------------------------

  function updateEditor() {
    const text = draftEl.value;
    $('char-count').textContent = `${text.length}자`;
    const posted = state && state.notice ? state.notice.text : null;
    postBtn.disabled = !text.trim() || text === posted;
  }

  function sendDraft() {
    clearTimeout(draftTimer);
    draftTimer = null;
    const text = draftEl.value;
    if (text === sentDraft) return;
    sentDraft = text;
    send('/ndrt/draft', { text });
  }

  draftEl.addEventListener('input', () => {
    updateEditor();
    clearTimeout(draftTimer);
    draftTimer = setTimeout(sendDraft, DRAFT_DELAY_MS);
  });
  draftEl.addEventListener('blur', sendDraft);
  draftEl.addEventListener('focus', () => event('editor_focus'));

  postBtn.addEventListener('click', async () => {
    const text = draftEl.value;
    if (!text.trim()) return;
    sendDraft();
    await send('/ndrt/post', { text });
    seq = 0;
    if (app.classList.contains('editing')) closeEditor();
  });

  function openEditor() {
    app.classList.add('editing');
    event('editor_open');
    draftEl.focus();
  }

  function closeEditor() {
    sendDraft();
    app.classList.remove('editing');
    event('editor_close');
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  $('open-editor').addEventListener('click', openEditor);
  $('close-editor').addEventListener('click', closeEditor);
  $('notice-banner').addEventListener('click', () => {
    if (window.matchMedia('(max-width: 820px)').matches) openEditor();
    else draftEl.focus();
  });

  // -- chat scrolling ----------------------------------------------------------

  messagesEl.addEventListener('scroll', () => {
    if (nearBottom()) $('new-pill').hidden = true;
  });
  $('new-pill').addEventListener('click', () => {
    messagesEl.scrollTop = messagesEl.scrollHeight;
    $('new-pill').hidden = true;
  });

  // -- page events (logged: when the participant looks at the NDRT) ------------

  window.addEventListener('focus', () => event('focus'));
  window.addEventListener('blur', () => { sendDraft(); event('blur'); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) sendDraft();
    event(document.hidden ? 'hidden' : 'visible');
  });
  window.addEventListener('pagehide', sendDraft);

  event('load', { width: window.innerWidth, height: window.innerHeight });
  poll();
})();
