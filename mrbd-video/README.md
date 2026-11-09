# MRBD Video — Meta Ray-Ban Display용 영상 플레이어 웹앱

안경 화면(600×600)에서 영상을 보는 웹앱입니다. 두 가지 방법으로 볼 수 있습니다.

1. **유튜브 링크** – 안경에서 링크를 입력(말하기/손글씨)하거나, 폰 리모컨에서 링크를 보내면 바로 재생됩니다.
2. **안경에 저장** – 폰이나 PC에서 영상을 서버에 올린 뒤 안경에서 ⬇로 받아 두면, 안경 저장소(IndexedDB)에서 바로 재생됩니다. 네트워크가 없어도 끊기지 않습니다.

## 구조

```
server.py          Python 표준 라이브러리만 쓰는 서버 (설치할 것 없음)
public/index.html  안경 앱 (600x600, 방향키/Enter 조작)
public/app.js      화면 이동, 유튜브 IFrame 플레이어, IndexedDB 저장, SSE 수신
public/phone.html  폰/PC 리모컨 (유튜브 링크 전송, 영상 업로드)
public/sw.js       앱 셸 프리캐시 (오프라인에서 즉시 실행)
media/             업로드된 영상 보관 폴더
```

## 지연을 줄이는 방법

| 구간 | 방법 |
|---|---|
| 앱 실행 | 서비스워커가 HTML/JS/CSS를 캐시해 두므로 네트워크를 기다리지 않습니다. |
| 유튜브 첫 재생 | 앱이 켜질 때 IFrame 플레이어를 미리 만들어 두고, 재생할 때는 `loadVideoById`만 호출합니다. youtube.com에는 미리 연결(preconnect)해 둡니다. |
| 저장 영상 | IndexedDB에 든 Blob을 그대로 재생하므로 버퍼링이 없습니다. |
| 폰 → 안경 | Server-Sent Events로 링크를 밀어 넣어, 누르는 순간 안경에서 재생됩니다. |
| 이어보기 | 영상별 재생 위치를 3초마다 저장해 두고, 다시 열면 그 위치부터 재생합니다. |

## 실행

```bash
cd mrbd-video
python server.py            # http://<PC IP>:8080
```

안경 웹앱은 **HTTPS가 필요합니다.** 서비스워커가 HTTPS에서만 등록되기 때문입니다. 개발 중에는 터널을 쓰는 것이 가장 간단합니다.

```bash
cloudflared tunnel --url http://localhost:8080      # https://xxxx.trycloudflare.com 발급
```

인증서가 있으면 서버가 직접 HTTPS로 띄울 수도 있습니다: `python server.py --port 8443 --cert cert.pem --key key.pem`

**실험용 고정 주소 (권장)**: 안경 저장소(IndexedDB)는 주소별로 따로라, 임시 터널처럼 주소가 바뀌면 받아 둔 영상이 보이지 않고 실험 연동(SAGAT 일시정지)도 끊깁니다. 그래서 이름 있는 터널 `mrbd-video` → `https://video.cocoju.dev`를 씁니다. `start_video_server.bat`이 서버와 터널을 함께 켭니다. 터널 설정은 `%USERPROFILE%\.cloudflared\config.yml`에 있고, 랩실 Wi-Fi가 UDP(QUIC)를 막아 `protocol: http2`로 둡니다. `glasses_qr.png`가 이 주소의 설치 QR입니다. 터널은 `tunnel_watchdog.ps1`이 띄우고 지켜보다가, 공개 주소가 530(터널 끊김)을 1분 동안 돌려주거나 cloudflared가 꺼지면 다시 켭니다.

서버는 이 랩탑에서 돌리고, 실험 PC는 `_Experiment2/devices.json`의 `"video": "https://video.cocoju.dev"`로 접속합니다(랩실 PC 방화벽이 터널을 막아서). 서버를 다른 랩탑으로 옮겨도 주소가 같으므로 안경에 받은 영상은 그대로 쓸 수 있습니다. `%USERPROFILE%\.cloudflared\`의 파일 3개(`cert.pem`, `<터널 ID>.json`, `config.yml`)만 옮기면 되고, 터널은 한 번에 한 대에서만 켜야 합니다.

### 안경에 설치

1. Meta AI 앱에서 **개발자 모드**를 켭니다.
2. Meta 웹앱 시뮬레이터의 **View on Glasses QR**로 위 HTTPS 주소의 설치 QR을 만듭니다. 일반 URL을 그대로 담은 QR은 인식되지 않습니다.
3. 안경으로 QR을 스캔한 뒤 설치를 확인합니다.
4. 폰 브라우저에서 `https://<주소>/phone.html`을 열어 리모컨으로 씁니다.

## 조작 (Neural Band / 터치패드)

| 화면 | 스와이프 ▲▼ | 스와이프 ◀▶ | 핀치(Enter) | 뒤로 |
|---|---|---|---|---|
| 메뉴 | 항목 이동 | 같은 줄의 버튼(🗑, 스트림) | 선택 | 이전 화면 |
| 재생 중 | 볼륨 ±10 | 10초 뒤로/앞으로 | 재생/일시정지 | 목록으로 (위치 저장) |

## 영상 준비 팁

안경 화면(600px)에 맞춰 H.264 MP4, 30fps, faststart로 변환해 두세요. 원본은 `videos/`에 두고(git 제외) 결과만 `media/`에 넣으면 됩니다.

```bash
ffmpeg -i videos/in.mp4 -vf "fps=30,scale=600:-2,setsar=1" -c:v libx264 -profile:v main -preset veryfast \
       -crf 28 -maxrate 700k -bufsize 1400k -c:a aac -b:a 64k -ac 2 -movflags +faststart media/.tmp.mp4 \
  && mv media/.tmp.mp4 media/out_600p.mp4      # 점(.)으로 시작하는 임시 파일은 목록에 안 보임
```

1080p 50분 영상(약 1.3GB)이 약 120~150MB가 됩니다. 안경은 받은 영상을 4MB 조각으로 나눠 저장하므로 큰 파일도 메모리를 거의 쓰지 않습니다.

## 제약 / 주의

- 유튜브 영상 중 **퍼가기(embed)가 금지된 영상**은 재생되지 않습니다(오류 101/150). 이 경우 화면에 안내가 표시됩니다.
- 유튜브 영상을 내려받아 저장하는 것은 유튜브 약관 위반이라 지원하지 않습니다. 유튜브는 스트리밍만 됩니다. "안경에 저장"은 직접 가진 영상 파일만 대상으로 합니다.
- 서버에는 인증 기능이 없습니다. 같은 네트워크 또는 개인 터널에서만 쓰세요.
- 안경 웹앱 저장소는 앱을 지우면 함께 삭제될 수 있습니다(Meta 문서). 원본은 `media/` 폴더에 남습니다.
- 동영상 재생과 iframe은 Meta 문서에 명시적인 지원 범위가 나와 있지 않습니다. 실제 기기에서 먼저 확인하세요.
