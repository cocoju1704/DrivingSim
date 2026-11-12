@echo off
rem SAGAT questions on a laptop (instead of the iPad). Copy this one file to the laptop; nothing else
rem is needed there. Both machines on the same network (the phone hotspot, or mocap Wi-Fi). The
rem experiment PC serves the page (sagat_server.py, port 5011) while a block runs; this looks for it
rem on the laptop's network by itself (the hotspot gives new addresses on every reconnect), waits
rem until it answers, then opens the page full screen (Edge or Chrome kiosk, with its own profile).
rem Leave it open between blocks: the page shows a small "disconnected" note while no block runs
rem and comes back by itself. Close it with Alt+F4.
rem
rem     sagat_laptop.bat                    find the experiment PC (the last one found is tried first)
rem     sagat_laptop.bat 192.168.0.70       only this address (the launcher window shows it)
rem
rem Set the laptop's screen and sleep timeouts to "never" (on battery too) for the session.

setlocal
set "PC=%~1"
set "LAST=%TEMP%\sagat_laptop_last.txt"
title SAGAT laptop

echo Waiting for the experiment PC (start a block there)...
:wait
if not "%~1"=="" (
    curl -s -o nul -m 2 "http://%PC%:5011/state" && goto open
    timeout /t 2 /nobreak >nul
    goto wait
)
rem the address found last time first, then the whole network (every address, port 5011)
if exist "%LAST%" (
    set /p PC=<"%LAST%"
    call :try && goto open
)
set "PC="
for /f "usebackq delims=" %%a in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = Get-Content -LiteralPath '%~f0' -Raw; Invoke-Expression $s.Substring($s.IndexOf('#PS' + 'SCAN'))"`) do set "PC=%%a"
if defined PC (
    > "%LAST%" echo %PC%
    goto open
)
timeout /t 2 /nobreak >nul
goto wait

:try
curl -s -o nul -m 2 "http://%PC%:5011/state"
goto :eof

:open
set "URL=http://%PC%:5011/"
title SAGAT laptop - %URL%
echo Found: %URL%
echo Opening full screen (Alt+F4 closes it).
set "BROWSER="
call :find "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
call :find "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
call :find "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
call :find "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
call :find "%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER (
    echo No Edge or Chrome found: opening the default browser, press F11 there for full screen.
    start "" "%URL%"
    goto :eof
)
start "" "%BROWSER%" --kiosk "%URL%" --edge-kiosk-type=fullscreen --no-first-run --disable-pinch --overscroll-history-navigation=0 --user-data-dir="%TEMP%\sagat_browser"
goto :eof

:find
if not defined BROWSER if exist "%~1" set "BROWSER=%~1"
goto :eof

rem The scan (PowerShell, read from this file above): every address of the laptop's networks
rem (/24), port 5011 at once; the first that answers /state as the SAGAT server is printed.
#PSSCAN
$found = $null
$mine = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } | ForEach-Object { $_.IPAddress }
foreach ($me in $mine) {
    $prefix = $me -replace '\.\d+$', '.'
    $tries = foreach ($n in 1..254) {
        $client = New-Object System.Net.Sockets.TcpClient
        [pscustomobject]@{ ip = $prefix + $n; client = $client; task = $client.ConnectAsync($prefix + $n, 5011) }
    }
    Start-Sleep -Milliseconds 700
    foreach ($t in $tries) {
        if (-not $found -and $t.task.Status -eq 'RanToCompletion' -and $t.client.Connected) {
            try {
                $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 ("http://{0}:5011/state" -f $t.ip)
                if ($r.Content -match 'phase') { $found = $t.ip }
            } catch {}
        }
        $t.client.Dispose()
    }
    if ($found) { break }
}
if ($found) { $found }
