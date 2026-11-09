@echo off
chcp 65001 >nul
rem mrbd-video 서버(http://localhost:8080)와 Cloudflare 고정 주소 터널(https://video.cocoju.dev)을 함께 켭니다.
rem 터널 설정: %USERPROFILE%\.cloudflared\config.yml (tunnel mrbd-video, protocol http2)
rem 끄려면 열린 두 창을 닫으세요.
cd /d "%~dp0"

rem server.py는 Python 3.10 이상 필요 (py 런처의 3.12 우선, 없으면 PATH의 python)
set PY=python
py -3.12 -c "" >nul 2>&1 && set PY=py -3.12

start "mrbd-video server" cmd /k %PY% server.py
start "mrbd-video tunnel" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel_watchdog.ps1"
echo 서버: http://localhost:8080   안경: https://video.cocoju.dev
