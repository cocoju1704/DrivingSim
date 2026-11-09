"""MRBD Video - Meta Ray-Ban Display 영상 시청 웹앱 서버 (Python 표준 라이브러리만 사용)

  python server.py                       # http://0.0.0.0:8080
  python server.py --port 8443 --cert cert.pem --key key.pem   # HTTPS

역할
  /              안경용 웹앱 (public/index.html, 600x600)
  /phone.html    폰/PC용 리모컨 (영상 업로드, 유튜브 링크 전송)
  /media/<file>  업로드한 영상 (Range 지원 → 스트리밍/다운로드)
  /api/videos    영상 목록 (GET), 삭제 (DELETE /api/videos/<name>)
  /api/upload    업로드 (PUT /api/upload?name=<filename>, body = 파일)
  /api/push      유튜브 링크를 안경으로 전송 (POST {"url": "...", "autoplay": true})
  /api/events    안경이 구독하는 Server-Sent Events 스트림
"""
import argparse
import json
import mimetypes
import os
import queue
import re
import socket
import ssl
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(ROOT, "public")
MEDIA = os.path.join(ROOT, "media")
VIDEO_EXT = {".mp4", ".m4v", ".webm", ".mov"}
CHUNK = 1024 * 256

os.makedirs(MEDIA, exist_ok=True)
mimetypes.add_type("video/mp4", ".m4v")
mimetypes.add_type("video/quicktime", ".mov")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")

_clients: set[queue.Queue] = set()
_clients_lock = threading.Lock()


def broadcast(event: str, data: dict) -> int:
    msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
    with _clients_lock:
        for q in list(_clients):
            q.put(msg)
        return len(_clients)


def safe_name(name: str) -> str | None:
    name = os.path.basename(urllib.parse.unquote(name or "")).strip()
    name = re.sub(r"[^\w.\-() ]", "_", name)
    if not name or name.startswith("."):
        return None
    if os.path.splitext(name)[1].lower() not in VIDEO_EXT:
        return None
    return name


def list_videos() -> list[dict]:
    out = []
    for f in sorted(os.listdir(MEDIA)):
        p = os.path.join(MEDIA, f)
        if os.path.isfile(p) and os.path.splitext(f)[1].lower() in VIDEO_EXT:
            st = os.stat(p)
            out.append({"name": f, "size": st.st_size, "mtime": int(st.st_mtime),
                        "url": "/media/" + urllib.parse.quote(f)})
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MRBDVideo/1.0"

    def log_message(self, fmt, *args):
        if "/api/events" not in (self.path or ""):
            super().log_message(fmt, *args)

    # ---------- helpers ----------
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cache="no-cache"):
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                a, b = m.groups()
                if a == "" and b:
                    start = max(0, size - int(b))
                else:
                    start = int(a or 0)
                    end = min(int(b), size - 1) if b else size - 1
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            try:
                while remaining > 0:
                    buf = f.read(min(CHUNK, remaining))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    remaining -= len(buf)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    # ---------- routes ----------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(url.path)

        if path == "/api/videos":
            return self.send_json(list_videos())

        if path == "/api/events":
            return self.sse()

        if path.startswith("/media/"):
            name = safe_name(path[len("/media/"):])
            p = os.path.join(MEDIA, name) if name else None
            if not p or not os.path.isfile(p):
                return self.send_json({"error": "not found"}, 404)
            return self.send_file(p, cache="public, max-age=31536000, immutable")

        if path in ("/", ""):
            path = "/index.html"
        p = os.path.normpath(os.path.join(PUBLIC, path.lstrip("/")))
        if not p.startswith(PUBLIC) or not os.path.isfile(p):
            return self.send_json({"error": "not found"}, 404)
        return self.send_file(p)

    def do_PUT(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != "/api/upload":
            return self.send_json({"error": "not found"}, 404)
        qs = urllib.parse.parse_qs(url.query)
        name = safe_name((qs.get("name") or [""])[0])
        if not name:
            return self.send_json({"error": "mp4/webm/m4v/mov 파일만 가능합니다"}, 400)
        total = int(self.headers.get("Content-Length") or 0)
        final = os.path.join(MEDIA, name)
        tmp = final + ".part"
        received = 0
        with open(tmp, "wb") as f:
            while received < total:
                buf = self.rfile.read(min(CHUNK, total - received))
                if not buf:
                    break
                f.write(buf)
                received += len(buf)
        if received != total:
            os.remove(tmp)
            return self.send_json({"error": "업로드가 중단되었습니다"}, 400)
        os.replace(tmp, final)
        broadcast("library", {"name": name})
        return self.send_json({"ok": True, "name": name, "size": total})

    def do_DELETE(self):
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if not path.startswith("/api/videos/"):
            return self.send_json({"error": "not found"}, 404)
        name = safe_name(path[len("/api/videos/"):])
        p = os.path.join(MEDIA, name) if name else None
        if not p or not os.path.isfile(p):
            return self.send_json({"error": "not found"}, 404)
        os.remove(p)
        broadcast("library", {"removed": name})
        return self.send_json({"ok": True})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/push":
            return self.send_json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send_json({"error": "bad json"}, 400)
        link = str(data.get("url", "")).strip()
        if not link:
            return self.send_json({"error": "url이 비어 있습니다"}, 400)
        n = broadcast("push", {"url": link, "autoplay": bool(data.get("autoplay", True)),
                               "ts": int(time.time() * 1000)})
        return self.send_json({"ok": True, "delivered": n})

    def sse(self):
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q: queue.Queue = queue.Queue()
        with _clients_lock:
            _clients.add(q)
        try:
            self.wfile.write(b"retry: 1500\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    msg = b": ping\n\n"
                self.wfile.write(msg)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with _clients_lock:
                _clients.discard(q)


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--cert")
    ap.add_argument("--key")
    args = ap.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    scheme = "http"
    if args.cert and args.key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    ip = lan_ip()
    print(f"MRBD Video 서버 실행 중")
    print(f"  안경 앱 : {scheme}://{ip}:{args.port}/")
    print(f"  리모컨  : {scheme}://{ip}:{args.port}/phone.html")
    print(f"  영상 폴더: {MEDIA}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
