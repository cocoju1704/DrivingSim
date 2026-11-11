'use strict';
/* MRBD Video — 시선 보정 (Tobii Pro Glasses 2 <-> 안경 화면)
 * app.js 다음에 읽힘: app.js의 $, mode, P (재생 중이면 멈춤), report를 씀.
 *   calibDot(dot)  실험 PC의 /api/control {action: 'calib', dot} (app.js control()이 부름):
 *                  검은 화면(안경에서 투명)에 점 하나. c, tl, tr, br, bl = 중심, 네 꼭짓점 (g2_calibrate.py),
 *                  px:X,Y = 600x600 화면의 한 점 (g2_calibrate.py, g2_validate.py),
 *                  blank = 점 없이 화면만 비움 (보정·검증 동안 메뉴가 안 보이게), off = 끔
 *                  text (선택) = 가운데에 안내 문구 ("이제 글래스를 보세요"); 점·blank와 함께
 *   calibState()   /api/state 보고에 넣는 점의 위치·색 (점이 안 보일 때 원격으로 확인)
 *   홈의 '보정 점 시험' 버튼: 서버 없이 점 5개를 차례로 */

// 시선 보정 점: 화면(600x600) 가장자리에서 CALIB_INSET px 안쪽의 꼭짓점, 또는 중심
const CALIB_INSET = 30;
// The look is set here too (inline), so the dot shows even with an old style.css in the glasses' cache.
function calibDot(dot, text) {
  const box = $('#calib');
  if (!dot || dot === 'off') { box.hidden = true; box.style.display = 'none'; return; }
  if (mode && !P.paused()) P.pause();
  const el = $('#calib-dot');
  el.style.display = dot === 'blank' ? 'none' : 'block';
  let label = $('#calib-text');
  if (!label) { label = document.createElement('div'); label.id = 'calib-text'; box.appendChild(label); }
  Object.assign(label.style, { position: 'absolute', left: '0', right: '0', top: '42%', textAlign: 'center',
    color: '#ff4040', font: 'bold 44px sans-serif', display: text ? 'block' : 'none' });
  label.textContent = text || '';
  const w = window.innerWidth, h = window.innerHeight, i = CALIB_INSET;
  // 'px:X,Y': any point in the 600x600 display px (g2_validate.py's check points)
  const px = typeof dot === 'string' && dot.startsWith('px:') ? dot.slice(3).split(',').map(Number) : null;
  const at = px && px.length === 2 && px.every(isFinite) ? [px[0] * w / 600, px[1] * h / 600]
    : { c: [w / 2, h / 2], tl: [i, i], tr: [w - i, i], br: [w - i, h - i], bl: [i, h - i] }[dot] || [w / 2, h / 2];
  Object.assign(box.style, { display: 'block', position: 'fixed', left: '0', top: '0', width: w + 'px',
    height: h + 'px', background: '#000', zIndex: '110' });
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

function calibState() {
  const box = $('#calib'), el = $('#calib-dot');
  if (!box || box.hidden) return null;
  const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
  return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
    border: cs.borderTopColor, bg: cs.backgroundColor, boxDisplay: getComputedStyle(box).display,
    win: [window.innerWidth, window.innerHeight] };
}
