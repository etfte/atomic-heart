# -*- coding: utf-8 -*-
"""
Atomic Heart Achievement Tracker - Background Sync Server with System Tray.
Enterprise 3826 Edition (Local Desktop Version).
"""

import gzip
import http.server
import math
import os
import re
import socket
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from PIL import Image, ImageDraw
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

if getattr(sys, "frozen", False):
    HERE = Path(sys.executable).resolve().parent
    MEIPASS = Path(getattr(sys, "_MEIPASS", HERE))
else:
    HERE = Path(__file__).resolve().parent
    MEIPASS = HERE

SAVE_PATH = Path.home() / ".atomic_heart_save.json"


def find_app_file():
    """
    Динамически находит актуальный HTML-файл трекера ачивок.
    Приоритет:
    1. 'Ачивки Atomic Heart.html' / 'index.html' рядом с exe или на Рабочем столе
    2. Вшитый внутри exe файл из временной папки PyInstaller (_MEIPASS)
    3. Любой самый свежий .html с 'atomic' или 'ачив' в названии
    """
    candidate_names = [
        "Ачивки Atomic Heart.html",
        "index.html",
        "Ачивки Атомное сердце.html",
    ]

    search_dirs = [
        HERE,
        HERE.parent,
        Path.home() / "Desktop",
        Path.home() / "Desktop" / "Запуск ачивок",
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "OneDrive" / "Desktop" / "Запуск ачивок",
        MEIPASS,
    ]

    # 1. Поиск по списку точных приоритетных имен
    for d in search_dirs:
        if d and d.is_dir():
            for name in candidate_names:
                p = d / name
                if p.is_file() and p.stat().st_size > 50000:
                    return p

    # 2. Поиск любого самого свежего подходящего HTML
    found = []
    for d in search_dirs:
        if d and d.is_dir():
            try:
                for p in d.glob("*.html"):
                    low = p.name.lower()
                    if ("atomic" in low or "ачив" in low) and p.stat().st_size > 50000:
                        found.append(p)
            except Exception:
                pass

    if found:
        found.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return found[0]

    # Фолбэк на вшитый файл
    bundled = MEIPASS / "Ачивки Atomic Heart.html"
    if bundled.is_file():
        return bundled

    return HERE / "Ачивки Atomic Heart.html"


PORT = 8765
APP_ID = 668580
ID_RE = re.compile(r"^\d{17}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")
GLOBAL_URL = "https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v0002/?gameid=%d&format=json" % APP_ID
CACHE_SECONDS = 60
_CACHE = {}


def generate_tray_image():
    for base in [HERE, MEIPASS]:
        ico_candidate = base / "icon.ico"
        if ico_candidate.exists():
            try:
                return Image.open(ico_candidate)
            except Exception:
                pass
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 4
    d.ellipse((pad, pad, size - pad, size - pad), fill=(26, 21, 16, 255), outline=(229, 90, 60, 255), width=3)
    inner_pad = 10
    d.ellipse((inner_pad, inner_pad, size - inner_pad, size - inner_pad), outline=(246, 207, 122, 180), width=2)
    cx, cy = size / 2, size / 2
    r_out = size * 0.32
    r_in = size * 0.13
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        angle = -math.pi / 2 + i * (math.pi / 5)
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d.polygon(pts, fill=(234, 179, 8, 255), outline=(254, 240, 138, 255))
    return img


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/progress":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b"{}"
                if len(body) > 2:
                    SAVE_PATH.write_bytes(body)
                    try:
                        (HERE / "atomic_heart_save.json").write_bytes(body)
                    except Exception:
                        pass
                self._send(200, b'{"status": "saved"}', "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, f'{{"error": "{str(e)}"}}\n'.encode("utf-8"), "application/json; charset=utf-8")
        else:
            self._send(404, "Не найдено".encode("utf-8"), "text/plain; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            app_file = find_app_file()
            if app_file and app_file.is_file():
                try:
                    data = app_file.read_bytes()
                    self._send(200, data, "text/html; charset=utf-8")
                except Exception as e:
                    self._send(500, f"Ошибка чтения HTML: {e}".encode("utf-8"), "text/plain; charset=utf-8")
            else:
                self._send(404, "HTML-файл трекера не найден".encode("utf-8"), "text/plain; charset=utf-8")
        elif url.path == "/api/progress":
            if SAVE_PATH.is_file():
                try:
                    data = SAVE_PATH.read_bytes()
                    self._send(200, data, "application/json; charset=utf-8")
                    return
                except Exception:
                    pass
            loc_save = HERE / "atomic_heart_save.json"
            if loc_save.is_file():
                try:
                    data = loc_save.read_bytes()
                    self._send(200, data, "application/json; charset=utf-8")
                    return
                except Exception:
                    pass
            self._send(200, b"{}", "application/json; charset=utf-8")
        elif url.path == "/steam":
            self._steam(parse_qs(url.query))
        elif url.path == "/steam_global":
            self._proxy(GLOBAL_URL, "application/json; charset=utf-8")
        elif url.path == "/steam_profile":
            self._profile(parse_qs(url.query))
        elif url.path == "/ping":
            self._send(200, b"pong", "text/plain; charset=utf-8")
        elif url.path == "/api/file_path":
            app_file = find_app_file()
            self._send(200, str(app_file).encode("utf-8"), "text/plain; charset=utf-8")
        elif url.path == "/api/lan_ip":
            self._send(200, get_lan_ip().encode("utf-8"), "text/plain; charset=utf-8")
        elif url.path == "/api/qr":
            data = parse_qs(url.query).get("data", [""])[0] or ("http://%s:%d/" % (get_lan_ip(), PORT))
            try:
                import io, qrcode
                qr = qrcode.QRCode(box_size=6, border=2)
                qr.add_data(data)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#fcd34d", back_color="#18130d")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                self._send(200, buf.getvalue(), "image/png")
            except Exception as e:
                self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8")
        else:
            self._send(404, "Не найдено".encode("utf-8"), "text/plain; charset=utf-8")

    def _steam(self, query):
        target = self._profile_target(query)
        if target is None:
            return
        self._proxy(target + "/stats/%d/?xml=1" % APP_ID, "application/xml; charset=utf-8")

    def _profile(self, query):
        target = self._profile_target(query)
        if target is None:
            return
        self._proxy(target + "/?xml=1", "application/xml; charset=utf-8")

    def _profile_target(self, query):
        steam_id = (query.get("steamid", [""])[0] or query.get("id", [""])[0] or "").strip()
        custom_url = (query.get("customurl", [""])[0] or query.get("name", [""])[0] or "").strip()

        if steam_id and ID_RE.match(steam_id):
            return "https://steamcommunity.com/profiles/%s" % steam_id
        if custom_url and NAME_RE.match(custom_url):
            return "https://steamcommunity.com/id/%s" % custom_url

        self._send(400, "Укажите steamid (17 цифр) или customurl".encode("utf-8"), "text/plain; charset=utf-8")
        return None

    def _proxy(self, target, content_type):
        cached = _CACHE.get(target)
        if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
            self._send(200, cached[1], content_type)
            return
        wait = None
        for attempt in range(3):
            if wait:
                time.sleep(min(max(wait, 1), 10))
            wait = None
            request = urllib.request.Request(
                target,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept-Encoding": "identity"
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
            except urllib.error.HTTPError as error:
                if error.code == 429 and attempt < 2:
                    raw = error.headers.get("Retry-After") if error.headers else ""
                    wait = int(raw.strip()) if raw and raw.strip().isdigit() else 2 + 3 * attempt
                    continue
                self._send(error.code, ("Стим ответил кодом %d" % error.code).encode("utf-8"), "text/plain; charset=utf-8")
                return
            except Exception:
                self._send(502, "Стим недоступен".encode("utf-8"), "text/plain; charset=utf-8")
                return
            _CACHE[target] = (time.monotonic(), body)
            self._send(200, body, content_type)
            return
        self._send(502, "Стим недоступен".encode("utf-8"), "text/plain; charset=utf-8")

    def log_message(self, format, *args):
        return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    port = PORT
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                pass

    if is_port_in_use(port):
        if "--no-browser" not in sys.argv:
            webbrowser.open("http://127.0.0.1:%d/" % port)
        sys.exit(0)

    try:
        server = Server(("0.0.0.0", port), Handler)
    except OSError:
        if "--no-browser" not in sys.argv:
            webbrowser.open("http://127.0.0.1:%d/" % port)
        sys.exit(0)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def open_browser(icon=None, item=None):
        webbrowser.open(f"http://127.0.0.1:{port}/")

    def sync_browser(icon=None, item=None):
        webbrowser.open(f"http://127.0.0.1:{port}/?sync=1")

    def open_folder(icon=None, item=None):
        try:
            os.startfile(str(HERE))
        except Exception:
            pass

    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, open_browser).start()

    if HAS_TRAY:
        icon_img = generate_tray_image()

        def exit_app(icon, item):
            try:
                icon.stop()
            except Exception:
                pass
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("🌐 Открыть трекер в браузере", open_browser, default=True),
            pystray.MenuItem("🔄 Синхронизировать со Steam", sync_browser),
            pystray.MenuItem("📂 Открыть папку с трекером", open_folder),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"ℹ️ Статус: Порт {port} активен", lambda i, it: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Закрыть лаунчер", exit_app),
        )

        icon = pystray.Icon("AtomicHeartLauncher", icon_img, "Atomic Heart: Синхронизатор 3826", menu=menu)
        try:
            icon.run()
            return
        except Exception:
            pass

    try:
        while server_thread.is_alive():
            server_thread.join(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
