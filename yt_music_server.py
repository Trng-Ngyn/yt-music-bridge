import http.server
import socketserver
import urllib.parse
import json
import subprocess
import os
import sys
import shutil
import traceback
import yt_dlp

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

PORT = int(os.environ.get("PORT", "8080"))

# Locate ffmpeg
FFMPEG_EXE = shutil.which("ffmpeg")
if not FFMPEG_EXE:
    try:
        import imageio_ffmpeg
        FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG_EXE = "ffmpeg"

import time
LATEST_TELEMETRY = {
    "status": "online",
    "ssid": "Hotspot Di Động",
    "ip": "Unknown",
    "rssi": -55,
    "temp": 42.0,
    "heap": 85000,
    "last_updated": time.time()
}


class YouTubeMusicHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[YT Server] {format % args}\n")

    def get_public_base_url(self):
        proto = self.headers.get("X-Forwarded-Proto", "http")
        host = self.headers.get("Host", f"localhost:{PORT}")
        if any(d in host for d in [".onrender.com", ".koyeb.app", ".hf.space", ".railway.app", ".fly.dev"]):
            proto = "https"
        return f"{proto}://{host}"

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_POST(self):
        global LATEST_TELEMETRY
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/telemetry":
            length = int(self.headers.get('Content-Length', 0))
            if length > 0:
                body = self.rfile.read(length)
                try:
                    data = json.loads(body.decode('utf-8'))
                    data['last_updated'] = time.time()
                    LATEST_TELEMETRY.update(data)
                    print(f"[Telemetry POST] Received: {data}")
                except Exception as e:
                    print(f"[Telemetry POST] Error: {e}")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        try:
            self._handle_get()
        except Exception as e:
            traceback.print_exc()
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e), "traceback": traceback.format_exc()}).encode('utf-8'))
            except Exception:
                pass

    def _handle_get(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ["/", "/health"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "service": "YouTube Music Bridge Cloud"}).encode('utf-8'))
            return

        elif parsed.path == "/telemetry":
            global LATEST_TELEMETRY
            # If query params passed from ESP32, update telemetry
            if params:
                for k, v in params.items():
                    LATEST_TELEMETRY[k] = v[0]
                LATEST_TELEMETRY['last_updated'] = time.time()
                print(f"[Telemetry GET] Updated: {LATEST_TELEMETRY}")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(LATEST_TELEMETRY, ensure_ascii=False).encode('utf-8'))
            return

        elif parsed.path == "/telegram/send":
            msg_text = params.get("text", [""])[0].strip()
            if not msg_text:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Missing text"}')
                return
            token = "9297115289:AAGCQQQB5RUTxuApFeAeE-gSvs2xVLsQ46c"
            chat_id = "5670587722"
            t_url = f"https://api.telegram.org/bot{token}/sendMessage"
            req_data = json.dumps({
                "chat_id": chat_id,
                "text": f"🤖 **[Tin nhắn từ Robot Lily]:**\n\n{msg_text}",
                "parse_mode": "Markdown"
            }).encode('utf-8')
            req = urllib.request.Request(t_url, data=req_data, headers={'Content-Type': 'application/json', 'User-Agent': 'LilyServer'})
            try:
                with urllib.request.urlopen(req, timeout=10) as t_res:
                    res_body = t_res.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(res_body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        elif parsed.path == "/resolve":
            query = params.get("q", [""])[0].strip()
            if not query:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error": "Missing query"}')
                return

            print(f"[YT Server] Searching YouTube for: {query}")
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'no_warnings': True,
                'noplaylist': True,
                'remote_components': ['ejs:github'],
                'js_runtimes': {'deno': {'path': None}, 'node': {'path': None}},
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_query = f"ytsearch1:{query}"
                res = ydl.extract_info(search_query, download=False)
                entries = res.get('entries', [])
                if not entries:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b'{"error": "No results"}')
                    return

                entry = entries[0]
                vid = entry.get('id')
                title = entry.get('title', 'YouTube Music')

                base_url = self.get_public_base_url()
                stream_url = f"{base_url}/stream?v={vid}"

                resp_data = {
                    "success": True,
                    "title": title,
                    "video_id": vid,
                    "url": stream_url
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(resp_data, ensure_ascii=False).encode('utf-8'))
                print(f"[YT Server] Resolved: '{title}' -> {stream_url}")

        elif parsed.path == "/stream":
            vid = params.get("v", [""])[0].strip()
            if not vid:
                self.send_response(400)
                self.end_headers()
                return

            print(f"[YT Server] Live streaming YouTube video ID: {vid}")

            # Send HTTP headers first
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            # Pipe yt-dlp stdout directly into ffmpeg stdin to transcode to 128k MP3
            cookie_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
            has_cookies = os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 100

            ytdl_cmd = [
                sys.executable, "-m", "yt_dlp",
                "-f", "bestaudio/best",
                "-o", "-",
                "--quiet",
                "--no-warnings",
                "--remote-components", "ejs:github",
                "--js-runtimes", "node",
                "--extractor-args", "youtube:player_client=android,visionos,web",
            ]
            if has_cookies:
                ytdl_cmd.extend(["--cookies", cookie_path])
            ytdl_cmd.append(f"https://www.youtube.com/watch?v={vid}")

            ffmpeg_cmd = [
                FFMPEG_EXE,
                "-loglevel", "quiet",
                "-i", "pipe:0",
                "-vn",
                "-af", "highpass=f=180,lowshelf=g=-5:f=250,equalizer=f=3200:t=q:w=1.2:g=2.5,volume=0.85",
                "-acodec", "libmp3lame",
                "-b:a", "128k",
                "-ar", "44100",
                "-ac", "2",
                "-f", "mp3",
                "pipe:1"
            ]

            p_ytdl = subprocess.Popen(ytdl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p_ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=p_ytdl.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p_ytdl.stdout.close()

            try:
                while True:
                    chunk = p_ffmpeg.stdout.read(16384)
                    if not chunk:
                        break
                    hex_len = f"{len(chunk):X}\r\n".encode('ascii')
                    self.wfile.write(hex_len + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                print(f"[YT Server] Client disconnected from stream {vid}")
            finally:
                p_ffmpeg.kill()
                p_ytdl.kill()
                p_ffmpeg.wait()
                p_ytdl.wait()

        else:
            self.send_response(404)
            self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    print(f"=== YouTube Music Bridge Cloud ===")
    print(f"Listening on 0.0.0.0:{PORT}...")
    server = ThreadedHTTPServer(("0.0.0.0", PORT), YouTubeMusicHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()
