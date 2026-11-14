# NDRT 영상 (휴대폰 앱)

휴대폰 조건에서 NDRT 영상을 휴대폰으로 재생하는 Android 앱입니다. 안경 앱(`public/app.js`)과 같은 방식으로
mrbd-video 서버의 이벤트(`/api/events`)를 받아 실험(`_Experiment2/video_link.py`)이 보내는 명령을 따릅니다.

| 명령 | 휴대폰에서 |
|---|---|
| play {file, t} | 블록 시작: 영상을 열고(휴대폰에 저장된 파일, 없으면 서버에서 스트리밍) t초로 이동해 재생. t가 0이면 지난번에 멈춘 곳부터, `restart`가 오면(세트 클립, 영상 질문이 있을 때) 처음부터 (v2) |
| freeze | SAGAT·TOR: 일시정지 + 검은 화면으로 가림, 터치·버튼 막힘 (볼륨 키만 됨) |
| resume | 가림 해제, 정지 전에 재생 중이었으면 이어 재생 |
| alert {text} / alert_off | 가림 위에 빨간 문구 / 문구만 지움 |
| pause / seek | 블록 끝 / 이동 |

**v4: 시선 분석용 마커.** 영상 화면의 네 모서리(세로 영상의 위·아래 검은 부분)에 ArUco 마커 4개(DICT_4X4_50, 왼쪽 위 20, 오른쪽 위 21, 오른쪽 아래 22, 왼쪽 아래 23)를 흰 여백과 함께 늘 띄웁니다. 한 변은 1.6 cm이고, 검은 부분이 짧으면 줄이되 1.2 cm 아래로는 줄이지 않습니다. 실제 크기는 화면 dpi로 맞춥니다. 마커는 SAGAT·TOR 가림 위에도 보입니다. 앱은 보고마다 `layout`(화면 크기, 영상 사각형, 마커 위치, 폰 px)을 함께 보내고, 실험이 이것을 블록 폴더의 `phone_screen.json`에 적습니다(`_Experiment2/mirror_aoi.py`가 사용). 조작 버튼은 아래 마커 위로 올라갑니다.

명령에는 블록의 조건(`device`)이 실려 오고, 앱은 `phone` 조건의 명령만 따릅니다. 글래스·HUD 블록에서
앱을 켜 두어도 영상이 재생되지 않습니다. 앱은 2초마다(그리고 명령마다) 서버에 상태를 보고하고(`device: phone`),
실험 로그와 `preflight.bat`이 이것을 읽습니다. 서버는 기기별로 마지막 보고를 따로 보관하므로(`/api/state?device=phone`)
**영상 서버 노트북의 `server.py`도 이 버전이어야** 안경 보고와 섞이지 않습니다.

## 설치 (USB로 연결한 휴대폰)

휴대폰: 설정 → 휴대전화 정보 → 소프트웨어 정보 → 빌드번호 7번 → 개발자 옵션 → USB 디버깅 켜기,
PC에 연결해 "USB 디버깅 허용"을 누릅니다.

```bash
python build.py --install --videos   # 빌드, 설치, 실행, ../media/*.mp4(세트 클립)를 앱 폴더로 복사 (이미 있으면 건너뜀)
python build.py --videos-only        # 영상만 다시 복사 (media/에 없는 영상은 휴대폰에서 지움)
```

Gradle·Android Studio 없이 Android SDK(build-tools, platform)와 JDK 11+만으로 빌드합니다
(`%LOCALAPPDATA%\Android\Sdk`, `~/.jdks`에서 찾음). 영상은 휴대폰의
`Android/data/com.drivingsim.ndrtvideo/files/Movies/`에 들어가며, 앱 목록 화면에서 서버의 영상을 직접 받을 수도 있습니다.

## 사용

1. 앱 목록 화면에서 서버 주소 확인(기본 `https://video.cocoju.dev`, 시작 창의 "NDRT 영상 서버"와 같게), "● 서버 연결됨"인지 봅니다.
2. 쓸 영상을 **선택**(✓)합니다. 시작 창에서 영상 파일(`--video-file`)을 정했으면 그 영상이 열립니다.
3. 이 화면을 켜 둔 채로 블록을 시작하면 영상이 자동으로 열리고 재생됩니다. 화면은 꺼지지 않습니다.
4. 영상 화면을 누르면 조작 버튼(10초 앞/뒤, 재생/정지, 목록)이 나옵니다. "처음부터"는 이어보기 위치를 지웁니다.
