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

  let instance = null;           // the server run this page belongs to
  let seq = 0;
  let state = null;
  let shownCount = 0;            // messages rendered so far
  let draftLoaded = false;       // the server's draft is put in the editor once, at the start
  let draftTimer = null;
  let sentDraft = null;
  let nameAsked = false;

  // -- message sound -------------------------------------------------------------
  // "카톡" when a message from someone else comes in (not for the chat already there at the start).
  // kakao.mp3 next to this page if it is there, else two short tones made here. Browsers play
  // sound only after the participant has clicked or typed on the page once (the name dialog does).

  const SOUND_FILE = 'kakao.mp3';
  const SOUND_VOLUME = 0.8;      // of the file's own loudness
  let soundFile = new Audio(SOUND_FILE);
  soundFile.volume = SOUND_VOLUME;
  soundFile.addEventListener('error', () => { soundFile = null; });
  let audioCtx = null;

  function unlockSound() {
    if (!audioCtx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) audioCtx = new Ctx();
    }
    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
  }
  window.addEventListener('pointerdown', unlockSound);
  window.addEventListener('keydown', unlockSound);

  // Test button for the experimenter, only with ?test in the address (http://localhost:5008/?test)
  if (new URLSearchParams(location.search).has('test')) {
    const testBtn = $('sound-test');
    testBtn.hidden = false;
    testBtn.addEventListener('click', () => {
      unlockSound();
      playMessageSound();
      testBtn.textContent = soundFile ? '🔔 kakao.mp3 재생' : '🔔 합성음 재생 (kakao.mp3 없음)';
    });
  }

  function tone(freq, start, length) {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    const t = audioCtx.currentTime + start;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.4 * SOUND_VOLUME, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + length);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(t);
    osc.stop(t + length + 0.02);
  }

  function playMessageSound() {
    if (soundFile) {
      soundFile.currentTime = 0;
      soundFile.play().catch(() => {});
      return;
    }
    unlockSound();
    if (!audioCtx || audioCtx.state !== 'running') return;
    tone(1318.5, 0.0, 0.12); // E6: "카"
    tone(1046.5, 0.13, 0.22); // C6: "톡"
  }

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
      if (instance && data.instance !== instance) {
        // kakao_ndrt.py was restarted (next participant): start over, without the old draft
        draftEl.value = '';
        location.reload();
        return;
      }
      instance = data.instance;
      seq = data.seq;
      if (data.changed) apply(data);
    } catch (err) {
      // experiment PC not reachable: try again
    }
    setTimeout(poll, POLL_MS);
  }

  // -- rendering ---------------------------------------------------------------

  const avatarColors = new Map(); // in order of first appearance: no two members share a color
  function avatarColor(name) {
    if (!avatarColors.has(name)) avatarColors.set(name, AVATAR_COLORS[avatarColors.size % AVATAR_COLORS.length]);
    return avatarColors.get(name);
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
    const first = !state;          // the chat opens at its first message, read from the top
    const stick = !first && nearBottom();
    const before = shownCount;
    state = data;
    $('room-name').textContent = data.room;
    $('room-count').textContent = data.member_count;
    document.title = data.room;
    if (data.placeholder) draftEl.placeholder = data.placeholder;
    render(data.messages);
    // new messages from the others since the last poll (not at the first load); the nudges during
    // the pre-alert sound on the simulator PC instead (takeover_experiment.py)
    if (before > 0 && data.messages.slice(before).some((m) => m.from && m.kind !== 'notice' && m.phase !== 'nudge'
                                                         && m.from !== data.name)) {
      playMessageSound();
      event('message_sound');
    }
    shownCount = data.messages.length;
    if (first) {
      messagesEl.scrollTop = 0;
    } else if (stick) {
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

  draftEl.value = ''; // never a draft the browser kept: the server's draft comes with the first poll
  event('load', { width: window.innerWidth, height: window.innerHeight });
  poll();
})();
