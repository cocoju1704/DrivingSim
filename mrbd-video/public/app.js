'use strict';
/* MRBD Video — Meta Ray-Ban Display용 영상 플레이어
 * 입력: 안경 OS가 Neural Band/터치패드 제스처를 ArrowUp/Down/Left/Right + Enter 로 전달.
 * 지연 최소화:
 *   - 앱 셸은 서비스워커로 프리캐시 → 오프라인에서도 즉시 시작
 *   - 유튜브 IFrame 플레이어를 앱 시작 시 미리 만들어 두고 loadVideoById 로 재사용
 *   - "안경에 저장"한 영상은 IndexedDB의 Blob을 바로 재생 → 네트워크 버퍼링 0
 */

const $ = (s, r = document) => r.querySelector(s);
const SCREENS = ['home', 'yt', 'lib', 'player'];
const LS_VER = 1;
const APP_VERSION = 10;  // shown on the home screen and sent in /api/state: which app files the glasses run
let current = 'home';
let lastPopAt = 0;
const lastFocusKey = {};

/* ---------------- 저장소 (localStorage, 스키마 버전 포함) ---------------- */
const store = {
  get(key, def) {
    try {
      const v = JSON.parse(localStorage.getItem(key));
      return v && v.v === LS_VER ? v.d : def;
    } catch { return def; }
  },
  set(key, d) {
    try { localStorage.setItem(key, JSON.stringify({ v: LS_VER, d })); } catch { /* 용량 초과 등 무시 */ }
  },
};

/* ---------------- 화면 전환 / 히스토리 ---------------- */
function show(name) {
  if (current === 'player' && name !== 'player') stopPlayback();
  rememberFocus();
  for (const s of SCREENS) $('#' + s).hidden = s !== name;
  current = name;
  if (name === 'yt') renderYT();
  else if (name === 'lib') renderLib();
  else if (name === 'player') { $('#player').focus(); return; }
  restoreFocus();
}

function go(name) {
  history.pushState({ s: name }, '');
  show(name);
}

function goBack() {
  if (!history.state || history.state.s === 'home') return; // 홈에서는 시스템 메뉴에 맡김
  const t = Date.now();
  // 시스템 Back이 이미 history.back()을 호출했다면 중복 실행하지 않음
  setTimeout(() => { if (lastPopAt < t) history.back(); }, 80);
}

window.addEventListener('popstate', (e) => {
  lastPopAt = Date.now();
  show((e.state && e.state.s) || 'home');
});

/* ---------------- 포커스 이동 (행/열 기반) ---------------- */
function rows() {
  const items = [...$('#' + current).querySelectorAll('.item')].filter((el) => !el.disabled);
  const out = [];
  let lastRow = null;
  for (const el of items) {
    const row = el.closest('.row') || el;
    if (row !== lastRow) { out.push([]); lastRow = row; }
    out[out.length - 1].push(el);
  }
  return out;
}

function locate(rs, el) {
  for (let r = 0; r < rs.length; r++) {
    const c = rs[r].indexOf(el);
    if (c >= 0) return [r, c];
  }
  return [-1, -1];
}

function focusEl(el) {
  if (!el) return;
  el.focus({ preventScroll: true });
  el.scrollIntoView({ block: 'nearest' });
}

function moveV(d) {
  const rs = rows();
  if (!rs.length) return;
  const [r, c] = locate(rs, document.activeElement);
  if (r < 0) return focusEl(rs[0][0]);
  const nr = Math.max(0, Math.min(rs.length - 1, r + d));
  focusEl(rs[nr][Math.min(c, rs[nr].length - 1)]);
}

function moveH(d) {
  const rs = rows();
  const [r, c] = locate(rs, document.activeElement);
  if (r < 0) return;
  const nc = c + d;
  if (nc >= 0 && nc < rs[r].length) focusEl(rs[r][nc]);
}

function rememberFocus() {
  const a = document.activeElement;
  if (a && a.dataset && a.dataset.key) lastFocusKey[current] = a.dataset.key;
}

function restoreFocus() {
  const scr = $('#' + current);
  const key = lastFocusKey[current];
  const el = (key && scr.querySelector(`[data-key="${CSS.escape(key)}"]`)) || scr.querySelector('.item');
  focusEl(el);
}

/* ---------------- 키 입력 ---------------- */
document.addEventListener('keydown', (e) => {
  const k = e.key;
  if (held && held.frozen) { e.preventDefault(); return; } // SAGAT 중에는 조작 불가
  if (current === 'player') return playerKey(e);
  const a = document.activeElement;
  const inInput = a && a.tagName === 'INPUT';

  if (k === 'ArrowUp' || k === 'ArrowDown') {
    e.preventDefault();
    moveV(k === 'ArrowDown' ? 1 : -1);
  } else if ((k === 'ArrowLeft' || k === 'ArrowRight') && !inInput) {
    e.preventDefault();
    moveH(k === 'ArrowRight' ? 1 : -1);
  } else if (k === 'Enter' && a && a.tagName === 'BUTTON') {
    e.preventDefault();
    a.click();
  } else if (k === 'Escape' || (k === 'Backspace' && !inInput)) {
    e.preventDefault();
    goBack();
  }
});

document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-go]');
  if (b) go(b.dataset.go);
});

/* ---------------- 유틸 ---------------- */
function fmtTime(s) {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
}
function fmtSize(b) {
  if (!b) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(i >= 2 ? 1 : 0) + u[i];
}
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'dataset') Object.assign(n.dataset, v);
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of kids) if (c != null) n.append(c);
  return n;
}
function setStatus(msg, ms = 3000) {
  const s = $('#status');
  s.textContent = msg;
  clearTimeout(setStatus.t);
  if (ms) setStatus.t = setTimeout(() => { s.textContent = ''; }, ms);
}
const posKey = (key) => 'pos:' + key;

/* ================= 유튜브 ================= */
function parseT(t) {
  if (!t) return 0;
  if (/^\d+s?$/.test(t)) return parseInt(t, 10);
  const m = t.match(/(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?/);
  return m ? (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (+m[3] || 0) : 0;
}

function parseYT(s) {
  s = (s || '').trim();
  if (/^[\w-]{11}$/.test(s)) return { id: s, start: 0 };
  let u;
  try { u = new URL(/^https?:\/\//i.test(s) ? s : 'https://' + s); } catch { return null; }
  const h = u.hostname.replace(/^(www|m|music)\./, '');
  let id = null;
  if (h === 'youtu.be') id = u.pathname.slice(1, 12);
  else if (h === 'youtube.com' || h === 'youtube-nocookie.com') {
    if (u.pathname === '/watch') id = u.searchParams.get('v');
    else {
      const m = u.pathname.match(/^\/(shorts|embed|live|v)\/([\w-]{11})/);
      if (m) id = m[2];
    }
  }
  if (!id || !/^[\w-]{11}$/.test(id)) return null;
  return { id, start: parseT(u.searchParams.get('t') || u.searchParams.get('start')) };
}

const recents = {
  all: () => store.get('yt:recent', []),
  add(id, title) {
    const list = recents.all().filter((r) => r.id !== id);
    const prev = store.get('yt:recent', []).find((r) => r.id === id);
    list.unshift({ id, title: title || (prev && prev.title) || '', ts: Date.now() });
    store.set('yt:recent', list.slice(0, 30));
  },
  setTitle(id, title) {
    const list = recents.all();
    const r = list.find((x) => x.id === id);
    if (r && title && r.title !== title) { r.title = title; store.set('yt:recent', list); }
  },
  remove(id) { store.set('yt:recent', recents.all().filter((r) => r.id !== id)); },
};

function renderYT() {
  const list = $('#yt-list');
  list.replaceChildren();
  const items = recents.all();
  if (!items.length) {
    list.append(el('p', { class: 'empty' }, '아직 없음 — 위에 링크를 입력하거나 폰 리모컨(/phone.html)에서 보내세요.'));
  }
  for (const r of items) {
    const pos = store.get(posKey('yt:' + r.id), 0);
    list.append(el('div', { class: 'row' },
      el('button', { class: 'item grow', dataset: { key: 'yt:' + r.id }, onclick: () => playYouTube({ id: r.id }) },
        el('span', { class: 'ico' }, '▶'),
        el('span', { class: 'name' }, r.title || r.id),
        pos > 5 ? el('span', { class: 'meta' }, fmtTime(pos) + '부터') : null),
      el('button', { class: 'item small danger', dataset: { key: 'ytdel:' + r.id },
        onclick: () => { recents.remove(r.id); renderYT(); restoreFocus(); } }, '✕')));
  }
}

$('#yt-input').addEventListener('change', (e) => {
  const v = e.target.value;
  const info = parseYT(v);
  if (!info) { e.target.value = ''; e.target.placeholder = '유튜브 링크가 아니에요. 다시 입력'; return; }
  e.target.value = '';
  playYouTube(info);
});

/* ---- IFrame 플레이어 미리 준비 (첫 재생 지연 제거) ---- */
let ytPlayer = null, ytReady = false, ytPending = null, ytCurrent = null;

window.onYouTubeIframeAPIReady = () => {
  ytPlayer = new YT.Player('yt-frame', {
    width: 600, height: 600,
    host: 'https://www.youtube.com',
    playerVars: {
      controls: 0, disablekb: 1, fs: 0, playsinline: 1, rel: 0,
      iv_load_policy: 3, modestbranding: 1, cc_load_policy: 0,
      origin: location.origin,
    },
    events: {
      onReady() {
        ytReady = true;
        const f = ytPlayer.getIframe();
        f.tabIndex = -1;
        if (ytPending) { const p = ytPending; ytPending = null; startYT(p); }
      },
      onStateChange(e) {
        if (e.data === YT.PlayerState.PLAYING) {
          const d = ytPlayer.getVideoData && ytPlayer.getVideoData();
          if (d && d.title && ytCurrent) {
            recents.setTitle(ytCurrent.id, d.title);
            $('#osd-title').textContent = d.title;
          }
          flash('▶');
        } else if (e.data === YT.PlayerState.PAUSED) flash('❚❚', true);
        else if (e.data === YT.PlayerState.ENDED && ytCurrent) {
          store.set(posKey('yt:' + ytCurrent.id), 0);
          flash('■', true);
        }
      },
      onError(e) {
        const msg = { 2: '잘못된 영상 ID', 5: '재생 불가 (HTML5)', 100: '삭제되었거나 비공개 영상',
          101: '이 영상은 외부 재생이 허용되지 않음', 150: '이 영상은 외부 재생이 허용되지 않음' }[e.data] || '재생 오류 ' + e.data;
        $('#osd-title').textContent = '⚠ ' + msg;
        flash('⚠', true);
      },
    },
  });
};
(function loadYTApi() {
  const s = document.createElement('script');
  s.src = 'https://www.youtube.com/iframe_api';
  s.async = true;
  s.onerror = () => setStatus('유튜브 연결 실패 (오프라인?) — 저장된 영상은 재생 가능', 0);
  document.head.append(s);
})();

function startYT(info) {
  const saved = store.get(posKey('yt:' + info.id), 0);
  const start = info.start || (saved > 5 ? saved : 0);
  ytPlayer.loadVideoById({ videoId: info.id, startSeconds: start });
  ytPlayer.unMute && ytPlayer.unMute();
}

function playYouTube(info) {
  stopPlayback();
  ytCurrent = info;
  recents.add(info.id);
  mode = 'yt';
  $('#player').className = 'screen mode-yt';
  $('#osd-title').textContent = (recents.all()[0] || {}).title || '유튜브 불러오는 중…';
  enterPlayer();
  if (ytReady) startYT(info);
  else { ytPending = info; flash('…', true); }
}

/* ================= 저장된 영상 (IndexedDB) ================= */
const DB = {
  _db: null,
  open() {
    if (this._db) return Promise.resolve(this._db);
    return new Promise((res, rej) => {
      const r = indexedDB.open('mrbd-video', 2);
      r.onupgradeneeded = () => {
        const db = r.result, have = db.objectStoreNames;
        if (!have.contains('meta')) db.createObjectStore('meta', { keyPath: 'id' });
        if (!have.contains('blob')) db.createObjectStore('blob', { keyPath: 'id' });   // v1: 영상 하나 = Blob 하나
        if (!have.contains('part')) db.createObjectStore('part', { keyPath: ['id', 'i'] }); // v2: 조각 저장
      };
      r.onsuccess = () => { this._db = r.result; res(r.result); };
      r.onerror = () => rej(r.error);
    });
  },
  async tx(stores, mode, fn) {
    const db = await this.open();
    return new Promise((res, rej) => {
      const t = db.transaction(stores, mode);
      const out = fn(t);
      t.oncomplete = () => res(out && 'result' in out ? out.result : undefined);
      t.onerror = () => rej(t.error);
      t.onabort = () => rej(t.error || new Error('저장 공간 부족'));
    });
  },
  list() { return this.tx(['meta'], 'readonly', (t) => t.objectStore('meta').getAll()); },
  parts: (id) => IDBKeyRange.bound([id, 0], [id, Infinity]),
  /* 조각들을 디스크에 둔 채 하나의 Blob으로 묶음 (메모리로 읽어 들이지 않음) */
  async blob(meta) {
    if (!meta.parts) {
      const rec = await this.tx(['blob'], 'readonly', (t) => t.objectStore('blob').get(meta.id));
      return rec && rec.blob;
    }
    const recs = await this.tx(['part'], 'readonly', (t) => t.objectStore('part').getAll(this.parts(meta.id)));
    if (!recs || recs.length !== meta.parts) return null;
    return new Blob(recs.map((p) => p.blob), { type: meta.type });
  },
  putPart(id, i, blob) {
    return this.tx(['part'], 'readwrite', (t) => { t.objectStore('part').put({ id, i, blob }); });
  },
  putMeta(meta) {
    return this.tx(['meta'], 'readwrite', (t) => { t.objectStore('meta').put(meta); });
  },
  del(id) {
    return this.tx(['meta', 'blob', 'part'], 'readwrite', (t) => {
      t.objectStore('meta').delete(id);
      t.objectStore('blob').delete(id);
      t.objectStore('part').delete(this.parts(id));
    });
  },
};

const downloading = new Map(); // id -> 진행률(0~100)

async function fetchServerList() {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 8000); // 받는 중엔 회선이 붐벼 늦게 올 수 있음
  try {
    const r = await fetch('/api/videos', { signal: ctl.signal, cache: 'no-store' });
    return r.ok ? await r.json() : [];
  } catch { return null; } finally { clearTimeout(t); }
}

let libRenderSeq = 0;
async function renderLib() {
  const seq = ++libRenderSeq;
  const [local, server] = await Promise.all([DB.list().catch(() => []), fetchServerList()]);
  if (seq !== libRenderSeq || current !== 'lib') return;
  rememberFocus();
  const list = $('#lib-list');
  list.replaceChildren();
  local.sort((a, b) => b.addedAt - a.addedAt);

  list.append(el('p', { class: 'sub' }, '안경에 저장됨 · 즉시 재생'));
  if (!local.length) list.append(el('p', { class: 'empty' }, '아직 없음 — 아래 목록에서 받아 오세요.'));
  for (const m of local) {
    const pos = store.get(posKey(m.id), 0);
    list.append(el('div', { class: 'row' },
      el('button', { class: 'item grow', dataset: { key: m.id }, onclick: () => playStored(m) },
        el('span', { class: 'ico' }, '▶'),
        el('span', { class: 'name' }, m.name),
        el('span', { class: 'meta' }, pos > 5 ? fmtTime(pos) + '부터' : fmtSize(m.size))),
      el('button', { class: 'item small danger', dataset: { key: 'del:' + m.id },
        onclick: async () => { await DB.del(m.id); store.set(posKey(m.id), 0); renderLib(); } }, '🗑')));
  }

  list.append(el('p', { class: 'sub' }, server === null ? '서버 연결 안 됨 (오프라인)' : '서버 영상 · 받기 또는 스트리밍'));
  const have = new Set(local.map((m) => m.id));
  for (const v of server || []) {
    const id = 'srv:' + v.name + ':' + v.size;
    if (have.has(id)) continue;
    const pct = downloading.get(id);
    list.append(el('div', { class: 'row' },
      el('button', { class: 'item grow', dataset: { key: id }, onclick: () => download(id, v.name, v.url, v.size) },
        el('span', { class: 'ico' }, '⬇'),
        el('span', { class: 'name' }, v.name),
        el('span', { class: 'meta', 'data-prog': id }, pct != null ? pct + '%' : fmtSize(v.size))),
      el('button', { class: 'item small', dataset: { key: 'st:' + id },
        onclick: () => playUrl(v.url, v.name, id) }, '스트림')));
  }

  list.append(el('div', { class: 'row' },
    el('input', { class: 'item grow', type: 'url', placeholder: '+ 영상 URL(mp4)로 저장', dataset: { key: 'addurl' },
      onchange: (e) => {
        const u = e.target.value.trim();
        e.target.value = '';
        if (!u) return;
        const name = decodeURIComponent(u.split('?')[0].split('/').pop() || 'video.mp4');
        download('url:' + u, name, u, 0);
      } })));

  restoreFocus();
  updateUsage();
}

async function updateUsage() {
  if (!navigator.storage || !navigator.storage.estimate) return;
  const { usage, quota } = await navigator.storage.estimate();
  $('#lib-usage').textContent = `${fmtSize(usage)} / ${fmtSize(quota)}`;
}

/* 받기: 한 번에 하나씩(대역폭을 나누지 않음), 끊기면 받은 조각은 남겨 두고 Range로 이어받음.
   앱을 껐다 켠 뒤 ⬇를 다시 눌러도 남은 조각 다음부터 이어받는다. */
let downloadQueue = Promise.resolve();
function download(id, name, url, sizeHint) {
  if (downloading.has(id)) return;
  downloading.set(id, 0);
  const l = document.querySelector(`[data-prog="${CSS.escape(id)}"]`);
  if (l) l.textContent = '대기';
  downloadQueue = downloadQueue.then(() => downloadOne(id, name, url, sizeHint));
}

async function downloadOne(id, name, url, sizeHint) {
  const label = () => document.querySelector(`[data-prog="${CSS.escape(id)}"]`);
  const PART = 4 * 1024 * 1024; // 4MB씩 IndexedDB에 기록 → 영상 전체를 메모리에 올리지 않음 (안경 RAM 2GB)
  const MAX_TRIES = 40;
  let tries = 0;
  try {
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
    for (;;) {
      try {
        await downloadAttempt(id, name, url, sizeHint, PART, label);
        setStatus('저장 완료: ' + name);
        return;
      } catch (err) {
        if (err && err.fatal) throw err;
        if (++tries >= MAX_TRIES) throw err;
        const wait = Math.min(15000, 1000 * 2 ** Math.min(tries, 4));
        setStatus(`연결 끊김, ${Math.round(wait / 1000)}초 뒤 이어받기 (${tries}/${MAX_TRIES})`, wait);
        const lb = label();
        if (lb) lb.textContent = (downloading.get(id) || 0) + '% ↻';
        await new Promise((r) => setTimeout(r, wait));
      }
    }
  } catch (err) {
    // 받은 조각은 지우지 않음: 다시 ⬇를 누르면 이어받는다
    setStatus('받기 중단: ' + (err.message || err) + ' — ⬇를 다시 누르면 이어받기', 6000);
    const lb = label();
    if (lb) lb.textContent = '중단';
  } finally {
    downloading.delete(id);
    if (current === 'lib') renderLib();
  }
}

async function downloadAttempt(id, name, url, sizeHint, PART, label) {
  // 이미 받아 둔 조각: 0번부터 빈틈없이 이어진 것만 인정, 마지막 조각이 4MB 미만이면 버리고 다시 받음
  const have = await DB.tx(['part'], 'readonly', (t) => t.objectStore('part').getAll(DB.parts(id)));
  let parts = 0, got = 0;
  for (const p of have || []) {
    if (p.i !== parts || p.blob.size !== PART) break;
    parts++; got += p.blob.size;
  }
  if ((have || []).length !== parts) {
    await DB.tx(['part'], 'readwrite', (t) => t.objectStore('part').delete(IDBKeyRange.bound([id, parts], [id, Infinity])));
  }
  if (sizeHint && got === sizeHint) { // 조각은 다 받았는데 목록 기록 전에 멈춘 경우
    await DB.putMeta({ id, name, size: got, type: 'video/mp4', parts, addedAt: Date.now() });
    return;
  }

  const ctl = new AbortController();
  let idle = setTimeout(() => ctl.abort(), 20000); // 20초 동안 아무것도 안 오면 끊긴 것으로 보고 이어받기
  const kick = () => { clearTimeout(idle); idle = setTimeout(() => ctl.abort(), 20000); };
  try {
    const res = await fetch(url, { signal: ctl.signal, cache: 'no-store',
                                   headers: got ? { Range: `bytes=${got}-` } : {} });
    if (res.status === 416 || res.status === 404) {
      await DB.del(id);
      throw Object.assign(new Error('서버에 파일이 없거나 바뀜 (HTTP ' + res.status + ')'), { fatal: true });
    }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    if (got && res.status !== 206) { // 서버가 이어받기를 지원하지 않음 → 처음부터
      await DB.del(id);
      parts = 0; got = 0;
    }
    const range = /\/(\d+)$/.exec(res.headers.get('content-range') || '');
    const total = range ? +range[1] : (+res.headers.get('content-length') || sizeHint || 0);
    const type = (res.headers.get('content-type') || 'video/mp4').split(';')[0];
    const reader = res.body.getReader();
    let chunks = [], buffered = 0, lastPaint = 0;
    const flush = async () => {
      if (!buffered) return;
      const b = new Blob(chunks, { type });
      chunks = []; buffered = 0;
      await DB.putPart(id, parts++, b);
    };
    for (;;) {
      const { done, value } = await reader.read();
      kick();
      if (done) break;
      chunks.push(value);
      buffered += value.length;
      got += value.length;
      if (buffered >= PART) {
        // 조각 경계를 정확히 4MB로 맞춤 (이어받기 위치 계산이 단순해짐)
        const all = new Uint8Array(buffered);
        let o = 0;
        for (const c of chunks) { all.set(c, o); o += c.length; }
        chunks = [all.subarray(0, PART)];
        const rest = all.subarray(PART);
        buffered = PART;
        await flush();
        if (rest.length) { chunks = [rest]; buffered = rest.length; }
      }
      const now = performance.now();
      if (now - lastPaint > 250) {
        lastPaint = now;
        const pct = total ? Math.floor((got / total) * 100) : 0;
        downloading.set(id, pct);
        const l = label();
        if (l) l.textContent = total ? pct + '%' : fmtSize(got);
      }
    }
    if (total && got !== total) throw new Error(`중간에 끊김 (${fmtSize(got)} / ${fmtSize(total)})`);
    await flush();
    await DB.putMeta({ id, name, size: got, type, parts, addedAt: Date.now() }); // 목록엔 다 받은 뒤에만 표시
  } finally {
    clearTimeout(idle);
  }
}

/* ================= 로컬/스트림 재생 ================= */
const video = $('#video');
let mode = null;       // 'yt' | 'local'
let localKey = null;   // 이어보기 키
let blobUrl = null;

async function playStored(meta) {
  const blob = await DB.blob(meta);
  if (!blob) { setStatus('파일이 없어요. 다시 받아 주세요.'); return renderLib(); }
  blobUrl = URL.createObjectURL(blob);
  playVideoSrc(blobUrl, meta.name, meta.id);
}

function playUrl(url, title, key) { playVideoSrc(url, title, key || url); }

function playVideoSrc(src, title, key) {
  const keepBlob = blobUrl;
  blobUrl = null;
  stopPlayback();
  blobUrl = keepBlob;
  mode = 'local';
  localKey = key;
  $('#player').className = 'screen mode-local';
  $('#osd-title').textContent = title;
  video.src = src;
  video.play().catch(() => flash('❚❚', true));
  enterPlayer();
}

video.addEventListener('loadedmetadata', () => {
  const saved = store.get(posKey(localKey), 0);
  if (saved > 5 && saved < video.duration - 10) video.currentTime = saved;
});
video.addEventListener('playing', () => flash('▶'));
video.addEventListener('pause', () => { if (!video.ended) flash('❚❚', true); });
video.addEventListener('waiting', () => flash('…', true));
video.addEventListener('ended', () => { store.set(posKey(localKey), 0); flash('■', true); });
video.addEventListener('error', () => {
  if (!video.getAttribute('src')) return;
  $('#osd-title').textContent = '⚠ 재생할 수 없는 형식 (H.264 MP4 권장)';
  flash('⚠', true);
});

/* ================= 플레이어 공통 ================= */
function enterPlayer() {
  if (current === 'player') { $('#player').focus(); return; }
  go('player');
}

const P = {
  time() { return mode === 'yt' ? (ytReady ? ytPlayer.getCurrentTime() : 0) : video.currentTime; },
  dur() { return mode === 'yt' ? (ytReady ? ytPlayer.getDuration() : 0) : (video.duration || 0); },
  paused() { return mode === 'yt' ? !(ytReady && ytPlayer.getPlayerState() === 1) : video.paused; },
  toggle() {
    if (mode === 'yt') { if (!ytReady) return; P.paused() ? ytPlayer.playVideo() : ytPlayer.pauseVideo(); }
    else video.paused ? video.play().catch(() => {}) : video.pause();
  },
  seek(d) { P.seekTo(P.time() + d); },
  seekTo(t) {
    t = Math.max(0, Math.min(P.dur() || Infinity, t));
    if (mode === 'yt') ytReady && ytPlayer.seekTo(t, true);
    else video.currentTime = t;
  },
  pause() {
    if (mode === 'yt') ytReady && ytPlayer.pauseVideo();
    else if (mode) video.pause();
  },
  play() {
    if (mode === 'yt') ytReady && ytPlayer.playVideo();
    else if (mode) video.play().catch(() => {});
  },
  vol(d) {
    let v;
    if (mode === 'yt') {
      if (!ytReady) return 0;
      v = Math.max(0, Math.min(100, ytPlayer.getVolume() + d * 100));
      ytPlayer.setVolume(v);
      if (v > 0) ytPlayer.unMute();
      return Math.round(v);
    }
    video.volume = Math.max(0, Math.min(1, video.volume + d));
    return Math.round(video.volume * 100);
  },
};

function savePos() {
  const key = mode === 'yt' ? ytCurrent && 'yt:' + ytCurrent.id : localKey;
  if (!key) return;
  const t = P.time(), d = P.dur();
  if (d && t > 5 && t < d - 10) store.set(posKey(key), Math.floor(t));
}
setInterval(() => { if (current === 'player' && !P.paused()) savePos(); }, 3000);

function stopPlayback() {
  if (!mode) return;
  savePos();
  if (mode === 'yt') {
    ytPending = null;
    if (ytReady) ytPlayer.stopVideo();
    ytCurrent = null;
  } else {
    video.pause();
    video.removeAttribute('src');
    video.load();
    localKey = null;
  }
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null; }
  mode = null;
  $('#osd').classList.remove('show');
}

function playerKey(e) {
  const k = e.key;
  const handled = ['Enter', ' ', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Escape', 'Backspace'];
  if (!handled.includes(k)) return;
  e.preventDefault();
  if (k === 'Enter' || k === ' ') { P.toggle(); flash(P.paused() ? '▶' : '❚❚', true); }
  else if (k === 'ArrowLeft') { P.seek(-10); flash('⏪ 10'); }
  else if (k === 'ArrowRight') { P.seek(10); flash('10 ⏩'); }
  else if (k === 'ArrowUp') flash('🔊 ' + P.vol(0.1));
  else if (k === 'ArrowDown') flash('🔉 ' + P.vol(-0.1));
  else goBack();
}

/* 유튜브 iframe으로 포커스가 넘어가면 키 입력을 잃으므로 즉시 되찾음 */
window.addEventListener('blur', () => {
  setTimeout(() => { if (current === 'player') { window.focus(); $('#player').focus(); } }, 0);
});
$('#player').tabIndex = -1;

/* OSD (진행바/상태) */
let osdTimer = null;
function paintOsd() {
  const t = P.time(), d = P.dur();
  $('#osd-fill').style.width = d ? (t / d) * 100 + '%' : '0';
  $('#osd-time').textContent = fmtTime(t) + ' / ' + (d ? fmtTime(d) : '--:--');
}
function flash(icon, sticky) {
  if (current !== 'player') return;
  $('#osd-state').textContent = icon || '';
  paintOsd();
  const osd = $('#osd');
  osd.classList.add('show');
  clearTimeout(osdTimer);
  if (!sticky) osdTimer = setTimeout(() => { if (!P.paused()) osd.classList.remove('show'); }, 2200);
}
setInterval(() => { if (current === 'player' && $('#osd').classList.contains('show')) paintOsd(); }, 500);

/* ================= 폰 리모컨 → 안경 (SSE) ================= */
function connectEvents() {
  if (!window.EventSource) return;
  const es = new EventSource('/api/events');
  es.addEventListener('push', (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    const info = parseYT(d.url);
    if (info) {
      recents.add(info.id);
      if (current === 'yt') renderYT();
      if (d.autoplay) playYouTube(info);
      else setStatus('새 링크 도착 → 유튜브 목록');
    } else if (/^https?:\/\/.+\.(mp4|m4v|webm|mov)(\?|$)/i.test(d.url)) {
      if (d.autoplay) playUrl(d.url, d.url.split('/').pop());
    }
  });
  es.addEventListener('library', () => { if (current === 'lib') renderLib(); });
  es.addEventListener('control', (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }
    control(d);
  });
}

/* ================= 실험 연동 (CARLA, SAGAT) =================
 * 실험 PC가 /api/control 로 보냄:
 *   freeze  일시정지 + 화면 가림 (SAGAT 시작), 조작도 막음
 *   resume  가림 해제 + freeze 전에 재생 중이었으면 이어 재생
 *   alert {text}  TOR: 일시정지 + 가림 + 빨간 경고 문구 (깜빡임)
 *   alert_off     경고 문구만 지움 (가림·정지는 그대로: 블록 끝까지 수동 운전)
 *   pause / play / seek {t}   블록 시작·끝
 *   calib {dot}   시선 보정: 검은 화면에 점 하나 (c, tl, tr, br, bl = 중심, 네 꼭짓점; px:X,Y = 600x600 화면의 한 점; off = 끔)
 * 처리 후 /api/state 로 상태(재생 위치 등)를 보고 -> 실험 로그에 남음 */
let held = null; // freeze/pause 동안: { wasPlaying, frozen }

function control(d) {
  const a = d.action;
  if (a === 'freeze' || a === 'pause' || a === 'alert') {
    if (!held) held = { wasPlaying: !!mode && !P.paused(), frozen: false };
    P.pause();
    if (a === 'freeze' || a === 'alert') { held.frozen = true; $('#freeze').hidden = false; }
    if (a === 'alert') { $('#freeze').textContent = d.text || '지금 직접 운전하세요'; $('#freeze').classList.add('alert'); }
  } else if (a === 'alert_off') {
    $('#freeze').textContent = '';
    $('#freeze').classList.remove('alert');
  } else if (a === 'resume') {
    const h = held;
    held = null;
    $('#freeze').hidden = true;
    $('#freeze').textContent = '';
    $('#freeze').classList.remove('alert');
    if (mode && (!h || h.wasPlaying)) P.play();
  } else if (a === 'play') {
    held = null;
    $('#freeze').hidden = true;
    $('#freeze').textContent = '';
    $('#freeze').classList.remove('alert');
    P.play();
  } else if (a === 'seek') {
    P.seekTo(+d.t || 0);
  } else if (a === 'calib') {
    calibDot(d.dot);
  }
  report(a, d.id);
}

// 시선 보정 점: 화면(600x600) 가장자리에서 CALIB_INSET px 안쪽의 꼭짓점, 또는 중심
const CALIB_INSET = 30;
// The look is set here too (inline), so the dot shows even with an old style.css in the glasses' cache.
function calibDot(dot) {
  const box = $('#calib');
  if (!dot || dot === 'off') { box.hidden = true; box.style.display = 'none'; return; }
  if (mode && !P.paused()) P.pause();
  const w = window.innerWidth, h = window.innerHeight, i = CALIB_INSET;
  // 'px:X,Y': any point in the 600x600 display px (g2_validate.py's check points)
  const px = typeof dot === 'string' && dot.startsWith('px:') ? dot.slice(3).split(',').map(Number) : null;
  const at = px && px.length === 2 && px.every(isFinite) ? [px[0] * w / 600, px[1] * h / 600]
    : { c: [w / 2, h / 2], tl: [i, i], tr: [w - i, i], br: [w - i, h - i], bl: [i, h - i] }[dot] || [w / 2, h / 2];
  Object.assign(box.style, { display: 'block', position: 'fixed', left: '0', top: '0', width: w + 'px',
    height: h + 'px', background: '#000', zIndex: '110' });
  const el = $('#calib-dot');
  Object.assign(el.style, { position: 'absolute', width: '28px', height: '28px', margin: '-14px 0 0 -14px',
    borderRadius: '50%', boxSizing: 'border-box', border: '5px solid #ff2a2a', background: '#fff',
    left: at[0] + 'px', top: at[1] + 'px' });
  box.hidden = false;
}

// Home: 보정 점 시험 = the five dots here, without the server (1.5 s each)
let calibTest = null;
const calibTestButton = $('#calib-test');  // null with an old index.html in the cache
if (calibTestButton) calibTestButton.addEventListener('click', () => {
  clearTimeout(calibTest);
  const seq = ['c', 'tl', 'tr', 'br', 'bl', 'off'];
  const step = (k) => { calibDot(seq[k]); report('calib_test', seq[k]); if (k < seq.length - 1) calibTest = setTimeout(() => step(k + 1), 1500); };
  step(0);
});
if ($('#app-ver')) $('#app-ver').textContent = 'v' + APP_VERSION;

function calibState() {
  const box = $('#calib'), el = $('#calib-dot');
  if (!box || box.hidden) return null;
  const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
  return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
    border: cs.borderTopColor, bg: cs.backgroundColor, boxDisplay: getComputedStyle(box).display,
    win: [window.innerWidth, window.innerHeight] };
}

function report(action, id) {
  const body = {
    action: action || 'status', id: id || '', screen: current, mode: mode || '',
    title: $('#osd-title').textContent || '', t: mode ? Math.round(P.time() * 1000) / 1000 : null,
    paused: mode ? P.paused() : null, frozen: !!(held && held.frozen), ts: Date.now(),
    v: APP_VERSION, calib: calibState(),
  };
  fetch('/api/state', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), keepalive: true }).catch(() => {});
}
setInterval(() => report('status'), 2000);

/* ================= 시작 ================= */
history.replaceState({ s: 'home' }, '');
show('home');
connectEvents();
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
