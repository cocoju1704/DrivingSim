# Cloudflare 터널(mrbd-video -> https://video.cocoju.dev)을 띄우고 지켜봄.
# 공개 주소가 530(터널 연결 없음)을 3번 연속(약 1분) 돌려주면 cloudflared를 다시 시작한다.
# (랩실 Wi-Fi에서 연결이 끊긴 뒤 막힌 Cloudflare 서버로만 재시도하며 멈춘 적이 있음)
# 실행: start_video_server.bat 이 띄움. 끄려면 이 창을 닫으면 cloudflared도 같이 꺼짐.

$url = 'https://video.cocoju.dev/api/state'
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) { $cf = 'C:\Program Files (x86)\cloudflared\cloudflared.exe' }

function Start-Tunnel {
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host ("[{0:HH:mm:ss}] 터널 시작" -f (Get-Date))
    Start-Process $cf -ArgumentList 'tunnel', 'run', 'mrbd-video' -NoNewWindow -PassThru
}

$proc = Start-Tunnel
$bad = 0
try {
    while ($true) {
        Start-Sleep -Seconds 20
        $code = 0
        try {
            $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 10
            $code = [int]$r.StatusCode
        } catch {
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode } else { $code = -1 }
        }
        # 530: Cloudflare에 터널 연결이 없음. 502 등은 서버(server.py) 쪽 문제라 터널은 그대로 둠.
        if ($code -eq 530 -or $proc.HasExited) { $bad++ } else { $bad = 0 }
        if ($bad -ge 3 -or $proc.HasExited) {
            Write-Host ("[{0:HH:mm:ss}] 터널 끊김 (HTTP {1}) - 다시 시작" -f (Get-Date), $code)
            $proc = Start-Tunnel
            $bad = 0
        }
    }
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}
