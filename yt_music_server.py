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


def get_audio_stream_url(vid):
    """
    Extract direct audio URL trying multiple player clients.
    Android and VisionOS bypass Google's datacenter bot challenge.
    """
    clients = ['android', 'visionos', 'ios', 'web']
    cookie_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    has_cookies = os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 100

    errors = []
    for client in clients:
        try:
            ydl_opts = {
                'quiet': True,
                'format': 'bestaudio/best',
                'no_warnings': True,
                'noplaylist': True,
                'js_runtimes': {'deno': {'path': None}, 'node': {'path': None}},
                'extractor_args': {
                    'youtube': {
                        'player_client': [client]
                    }
                }
            }
            if client == 'web' and has_cookies:
                ydl_opts['cookiefile'] = cookie_path

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
                if not info:
                    continue

                # 1. Primary url field
                raw_url = info.get('url')

                # 2. Check formats list if top-level url is empty
                if not raw_url and 'formats' in info:
                    audio_fmts = [
                        f for f in info['formats']
                        if f.get('acodec') != 'none' and f.get('url')
                    ]
                    if audio_fmts:
                        # Pick best audio quality
                        audio_fmts.sort(key=lambda x: (x.get('abr') or 0, x.get('tbr') or 0))
                        raw_url = audio_fmts[-1]['url']

                if raw_url:
                    headers = info.get('http_headers', {})
                    ua = headers.get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
                    return raw_url, ua, client, None
        except Exception as e:
            err_msg = str(e).split('\n')[0]
            errors.append(f"{client}: {err_msg}")
            print(f"[YT Server] Client '{client}' failed for {vid}: {err_msg}")

    return None, None, None, "; ".join(errors)


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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ["/", "/health"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "service": "YouTube Music Bridge Cloud"}).encode('utf-8'))
            return

        elif parsed.path == "/diag":
            vid = params.get("v", ["488ceQWoGGw"])[0].strip()
            raw_url, ua, client, err = get_audio_stream_url(vid)
            resp = {
                "success": bool(raw_url),
                "video_id": vid,
                "client": client,
                "url_preview": (raw_url[:60] + "...") if raw_url else None,
                "error": err,
                "yt_dlp_version": yt_dlp.__version__
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(resp, indent=2).encode('utf-8'))
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
                'js_runtimes': {'deno': {'path': None}, 'node': {'path': None}},
            }
            try:
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
            except Exception as e:
                print(f"[YT Server] Error resolving {query}: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

        elif parsed.path == "/stream":
            vid = params.get("v", [""])[0].strip()
            if not vid:
                self.send_response(400)
                self.end_headers()
                return

            print(f"[YT Server] Streaming YouTube video ID: {vid}")
            raw_audio_url, ua, client_used, err = get_audio_stream_url(vid)

            if not raw_audio_url:
                print(f"[YT Server] Failed to extract audio for {vid}: {err}")
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Failed to extract audio stream", "details": err}).encode('utf-8'))
                return

            print(f"[YT Server] Transcoding audio for {vid} via client '{client_used}'...")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                # Launch ffmpeg with user_agent to transcode live to 128k MP3
                ffmpeg_cmd = [
                    FFMPEG_EXE,
                    "-loglevel", "quiet",
                    "-user_agent", ua,
                    "-reconnect", "1",
                    "-reconnect_streamed", "1",
                    "-reconnect_delay_max", "5",
                    "-i", raw_audio_url,
                    "-vn",
                    "-acodec", "libmp3lame",
                    "-b:a", "128k",
                    "-ar", "44100",
                    "-ac", "2",
                    "-f", "mp3",
                    "pipe:1"
                ]

                proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=32768
                )

                try:
                    while True:
                        chunk = proc.stdout.read(16384)
                        if not chunk:
                            break
                        # HTTP Chunked transfer
                        hex_len = f"{len(chunk):X}\r\n".encode('ascii')
                        self.wfile.write(hex_len + chunk + b"\r\n")
                        self.wfile.flush()
                    # End chunk
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    print(f"[YT Server] Client disconnected from stream {vid}")
                finally:
                    proc.kill()
                    proc.wait()

            except Exception as e:
                print(f"[YT Server] Stream error for {vid}: {e}")
                traceback.print_exc()
                try:
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(f"Stream error: {str(e)}".encode('utf-8'))
                except Exception:
                    pass
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
