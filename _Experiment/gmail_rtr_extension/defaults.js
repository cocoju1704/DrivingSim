// Defaults shared by the service worker and the options page.
// Task context = Notion "NDRT 및 개입 예시(이메일 가정)" 1절, 세트 1(팀 워크숍 공지).

export const DEFAULT_TASK_CONTEXT = `과제: 마케팅팀 대리가 출장 중인 김 팀장 대신 팀원 8명에게 보낼 "하반기 팀 워크숍 공지" 메일을 작성한다.

반영 항목 7개 (항목 이름 / 정보 카드 내용):
① 날짜: 워크숍이 11/20–21에서 11/27(목)–28(금)로 연기됨
② 장소: 가평 솔숲리조트 세미나동 B홀, 객실 체크인 15시
③ 출발: 본사 정문 앞 버스. 팀장 메모는 8:30, 버스회사 문자로 9:00으로 조정됨
④ 숙박비: 2인 1실 1실 16만 원, 회사 지원 1인 5만 원 → 1인 개인 부담 계산 필요
⑤ 발표: 파트별 하반기 회고 15분, 순서 기획 → 디자인 → 운영
⑥ 자료 마감: 발표 자료 11/25(화)까지 공유 드라이브 업로드
⑦ 저녁: 첫날 저녁 바비큐, 채식 메뉴 따로 준비`;

// Strings that must never appear in the summary: values of items the participant
// has not finished yet would leak answers and contaminate NDRT performance.
export const DEFAULT_BANNED_TERMS = '3만, 30,000, 30000, 9시, 9:00, 8:30, 16만, 5만, 8만, B홀, 15시, 11/25, 11/27, 15분, 바비큐, 채식';

export const DEFAULT_SETTINGS = {
  apiKey: '',
  model: 'gpt-5.5',
  effort: 'low',
  taskContext: DEFAULT_TASK_CONTEXT,
  bannedTerms: DEFAULT_BANNED_TERMS,
  showPanel: true,
  showButton: true,
  scenario: 1,
  // takeover_experiment.py's rtr_bridge.py, e.g. http://192.168.0.10:5008 ('' = off)
  bridgeUrl: 'http://127.0.0.1:5008',
};

export async function loadSettings() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULT_SETTINGS));
  if (stored.model?.startsWith('claude')) delete stored.model; // saved before the switch to OpenAI
  return { ...DEFAULT_SETTINGS, ...stored };
}
