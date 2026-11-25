"""EarthNG on Linux: the Map Builder page in the player's browser instead of a WebView2 window.

    ./EarthNG                                 (the Linux package's launcher, docs/LINUX.md)
    python earthng/app_web.py [--port N] [--no-browser]

The same page (app/ui) and the same service (app_service.py, JSON lines over pipes) as EarthNG.exe:
this file stands in for rust/crates/app. It serves the page and the OSM background tiles on
127.0.0.1, hands the page's messages to the service (POST /ipc) and streams the service's lines
back (GET /events, server-sent events). app/ui/web.js gives the page the window.ipc that WebView2
gives it in the exe.

Only this machine's browser may drive it: the server listens on 127.0.0.1, refuses a Host other
than its own loopback name and port (DNS rebinding), and /ipc and /events need the session key
that only the page served here carries (another site cannot read it, and the custom header makes
its requests preflighted, which this server never allows).

Data (PBF, tiles, packs, projects) live in ~/.local/share/EarthNG/data, logs and the tile cache
beside it ($XDG_DATA_HOME honoured, EARTHNG_LOCAL overrides). Run from a checkout (no
BUILD_INFO.json) the service keeps using the checkout, as the exe does.
"""
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
UI = ROOT / 'app' / 'ui'
TILE_SERVER = 'https://tile.openstreetmap.org'
TILE_MAX_AGE = 30 * 86400
TILE_LIMIT = 4 << 20
IDLE_SECONDS = 600          # no page open and no job: the server ends (a launcher without a terminal)
NEVER_OPENED_SECONDS = 1800
STEAM_BEAMNG = 'steam://rungameid/284160'
MIME = {'html': 'text/html; charset=utf-8', 'js': 'text/javascript; charset=utf-8', 'mjs': 'text/javascript; charset=utf-8',
        'css': 'text/css; charset=utf-8', 'json': 'application/json', 'png': 'image/png', 'svg': 'image/svg+xml',
        'ico': 'image/x-icon', 'woff2': 'font/woff2'}


def local(env=None):
    """~/.local/share/EarthNG: data, logs and caches of the Linux package (EARTHNG_LOCAL overrides)."""
    env = os.environ if env is None else env
    if env.get('EARTHNG_LOCAL'):
        return Path(env['EARTHNG_LOCAL'])
    if os.name == 'nt' and env.get('LOCALAPPDATA'):
        return Path(env['LOCALAPPDATA']) / 'EarthNG'
    base = Path(env['XDG_DATA_HOME']) if env.get('XDG_DATA_HOME') else Path.home() / '.local' / 'share'
    return base / 'EarthNG'


def build_info():
    try:
        return json.loads((ROOT / 'BUILD_INFO.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def version():
    found = build_info().get('version')
    if found:
        return found
    try:
        text = (ROOT / 'rust' / 'crates' / 'app' / 'Cargo.toml').read_text(encoding='utf-8')
        return re.search(r'^version = "([^"]+)"', text, re.M).group(1)
    except (OSError, AttributeError):
        return 'dev'


def log(text):
    folder = local() / 'logs'
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'app.log').open('a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {text}\n')
    except OSError:
        pass


# ---------------------------------------------------------------------- tiles (rust/crates/app/src/tiles.rs)
def tile_key(rest):
    """(z, x, y) of "<z>/<x>/<y>.png", or None."""
    m = re.fullmatch(r'(\d{1,2})/(\d{1,7})/(\d{1,7})\.png', rest)
    if not m:
        return None
    z, x, y = (int(v) for v in m.groups())
    if z > 19 or x >= 1 << z or y >= 1 << z:
        return None
    return z, x, y


def fetch_tile(z, x, y):
    agent = f'EarthNG-MapBuilder/{version()} (+https://github.com/Alezx311/earthng)'
    request = urllib.request.Request(f'{TILE_SERVER}/{z}/{x}/{y}.png', headers={'User-Agent': agent})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https host
        return response.read(TILE_LIMIT)


def serve_tile(rest, cache=None, fetch=fetch_tile):
    """(status, body): the disk copy while fresh, else the server's (kept), else an old copy."""
    key = tile_key(rest)
    if key is None:
        return 400, b'bad tile'
    z, x, y = key
    path = (Path(cache) if cache else local() / 'cache' / 'osm') / str(z) / str(x) / f'{y}.png'
    try:
        if time.time() - path.stat().st_mtime < TILE_MAX_AGE:
            return 200, path.read_bytes()
    except OSError:
        pass
    try:
        body = fetch(z, x, y)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        try:
            return 200, path.read_bytes()       # offline: an old copy is better than a hole
        except OSError:
            return 502, str(exc).encode('utf-8', 'replace')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix('.part')
        part.write_bytes(body)
        os.replace(part, path)
    except OSError:
        pass
    return 200, body


# ---------------------------------------------------------------------- the service and its listeners
class Hub:
    """The service's lines for every open page; the last 'ready' is replayed to a new one."""

    def __init__(self):
        self.lock = threading.Lock()
        self.queues = []
        self.ready = None
        self.busy = False
        self.had_page = False
        self.idle_since = time.monotonic()

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self.queues.append(q)
            self.had_page = True
            if self.ready:
                q.put(self.ready)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.queues:
                self.queues.remove(q)
            if not self.queues:
                self.idle_since = time.monotonic()

    def publish(self, line):
        try:
            message = json.loads(line)
        except ValueError:
            message = None
        if isinstance(message, dict):
            if message.get('event') == 'ready':
                self.ready = line
            elif message.get('event') == 'done':
                self.busy = False
            elif message.get('ok') and message.get('job'):
                self.busy = True
        with self.lock:
            for q in self.queues:
                q.put(line)

    def pages(self):
        with self.lock:
            return len(self.queues)


class ServiceProcess:
    def __init__(self, hub, home=None, package=False):
        self.hub = hub
        self.lock = threading.Lock()
        logs = local() / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'}
        if home is not None:
            Path(home).mkdir(parents=True, exist_ok=True)
            env['EARTHNG_HOME'] = str(home)
        if package:
            env['EARTHNG_PACKAGE'] = 'linux'
        self.stderr = (logs / 'service.log').open('w', encoding='utf-8')
        self.process = subprocess.Popen(  # noqa: S603 - our own interpreter and script
            [sys.executable, '-X', 'utf8', str(HERE / 'app_service.py')], cwd=ROOT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            text=True, encoding='utf-8', errors='replace', bufsize=1)
        threading.Thread(target=self.relay, daemon=True).start()

    def relay(self):
        for line in self.process.stdout:
            if line.strip():
                self.hub.publish(line.strip())
        self.hub.publish(json.dumps({'event': 'service_exit'}))

    def send(self, text):
        with self.lock:
            if self.process.poll() is not None or self.process.stdin is None:
                return False
            try:
                self.process.stdin.write(text.rstrip('\n') + '\n')
                self.process.stdin.flush()
                return True
            except OSError:
                return False

    def stop(self):
        """stdin closed: the service stops its job; its build processes end with it."""
        with self.lock:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.stderr.close()


def open_external(url):
    """Pages and BeamNG.drive through Steam ("Start BeamNG.drive" after a build); nothing else."""
    if url.startswith('https://'):
        webbrowser.open(url)
    elif url == STEAM_BEAMNG:
        opener = 'open' if sys.platform == 'darwin' else ('xdg-open' if os.name != 'nt' else None)
        if opener and shutil.which(opener):
            subprocess.Popen([opener, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,  # noqa: S603
                             stderr=subprocess.DEVNULL, start_new_session=True)
        elif os.name == 'nt':
            os.startfile(url)  # noqa: S606


def app_command(message, hub):
    """A message for the window itself ({"to": "app"}): what rust/crates/app main.rs answers."""
    cmd, rid = message.get('cmd'), message.get('id')
    if cmd == 'open_url':
        open_external(str(message.get('url') or ''))
    elif cmd == 'version':
        hub.publish(json.dumps({'id': rid, 'ok': True, 'version': version()}))
    elif cmd == 'apply_update':
        hub.publish(json.dumps({'id': rid, 'ok': False,
                                'error': 'On Linux, download the new EarthNG package from the release page.'}))


def index_html(key):
    """app/ui/index.html with the browser transport (web.js) and this session's key ahead of the
    page's own scripts."""
    text = (UI / 'index.html').read_text(encoding='utf-8')
    inject = f'<script>window.EARTHNG_KEY={json.dumps(key)};</script>\n<script src="web.js"></script>\n'
    at = text.find('<script src=')
    return (text[:at] + inject + text[at:]) if at >= 0 else text.replace('</body>', inject + '</body>')


def ui_file(path):
    """A file of the page under app/ui, never outside it; None when there is none."""
    rel = urllib.parse.unquote(path).lstrip('/') or 'index.html'
    parts = rel.split('/')
    if any(p in ('', '.', '..') or '\\' in p or ':' in p for p in parts):
        return None
    candidate = UI.joinpath(*parts)
    try:
        candidate.resolve().relative_to(UI.resolve())
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = 'EarthNG'
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):  # noqa: A002 - the base class's name
        pass

    # -- checks
    def host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get('Host', '') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def key_ok(self, given):
        return secrets.compare_digest(str(given or ''), self.server.key)

    def reply(self, status, body=b'', kind='text/plain; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    # -- verbs
    def do_GET(self):  # noqa: N802 - http.server's name
        if not self.host_ok():
            return self.reply(HTTPStatus.FORBIDDEN, b'wrong host')
        url = urllib.parse.urlsplit(self.path)
        if url.path.startswith('/tile/'):
            status, body = serve_tile(url.path[len('/tile/'):], self.server.tile_cache)
            return self.reply(status, body, 'image/png' if status == 200 else 'text/plain; charset=utf-8')
        if url.path == '/events':
            query = urllib.parse.parse_qs(url.query)
            if not self.key_ok((query.get('k') or [''])[0]):
                return self.reply(HTTPStatus.FORBIDDEN, b'no key')
            return self.events()
        if url.path in ('/', '/index.html'):
            return self.reply(HTTPStatus.OK, index_html(self.server.key).encode('utf-8'), MIME['html'])
        found = ui_file(url.path)
        if found is None:
            return self.reply(HTTPStatus.NOT_FOUND, b'not found')
        return self.reply(HTTPStatus.OK, found.read_bytes(), MIME.get(found.suffix.lstrip('.'), 'application/octet-stream'))

    do_HEAD = do_GET

    def do_POST(self):  # noqa: N802
        if not self.host_ok():
            return self.reply(HTTPStatus.FORBIDDEN, b'wrong host')
        if urllib.parse.urlsplit(self.path).path != '/ipc':
            return self.reply(HTTPStatus.NOT_FOUND, b'not found')
        if not self.key_ok(self.headers.get('X-EarthNG-Key')):
            return self.reply(HTTPStatus.FORBIDDEN, b'no key')
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if not 0 < length <= 1 << 22:
            return self.reply(HTTPStatus.BAD_REQUEST, b'bad length')
        text = self.rfile.read(length).decode('utf-8', 'replace')
        try:
            message = json.loads(text)
        except ValueError:
            return self.reply(HTTPStatus.BAD_REQUEST, b'not json')
        if not isinstance(message, dict):
            return self.reply(HTTPStatus.BAD_REQUEST, b'not an object')
        if message.get('to') == 'app':
            app_command(message, self.server.hub)
        elif not self.server.service.send(json.dumps(message, ensure_ascii=False)):
            self.server.hub.publish(json.dumps({'id': message.get('id'), 'ok': False, 'error': 'the service is not running'}))
        return self.reply(HTTPStatus.NO_CONTENT)

    def events(self):
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        q = self.server.hub.subscribe()
        try:
            self.wfile.write(b'retry: 2000\n\n')
            self.wfile.flush()
            while not self.server.stopping.is_set():
                try:
                    line = q.get(timeout=15)
                    chunk = f'data: {line}\n\n'
                except queue.Empty:
                    chunk = ': ping\n\n'
                self.wfile.write(chunk.encode('utf-8'))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.hub.unsubscribe(q)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def make_server(port=0, home=None, package=False, tile_cache=None, start_service=True):
    server = Server(('127.0.0.1', port), Handler)
    server.key = secrets.token_urlsafe(24)
    server.hub = Hub()
    server.stopping = threading.Event()
    server.tile_cache = tile_cache
    server.service = ServiceProcess(server.hub, home, package) if start_service else None
    return server


def watch_idle(server, idle=IDLE_SECONDS, never=NEVER_OPENED_SECONDS):
    """End the server when no page has been open for a while and no job runs."""
    started = time.monotonic()
    while not server.stopping.wait(5):
        hub = server.hub
        if hub.pages() or hub.busy:
            continue
        quiet = time.monotonic() - (hub.idle_since if hub.had_page else started)
        if quiet > (idle if hub.had_page else never):
            log('no page open: stopping')
            threading.Thread(target=server.shutdown, daemon=True).start()
            return


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--port', type=int, default=0, help='127.0.0.1 port (default: any free one)')
    p.add_argument('--no-browser', action='store_true', help='print the address, do not open a browser')
    p.add_argument('--stay', action='store_true', help='keep running with no page open')
    a = p.parse_args(argv)
    package = (ROOT / 'BUILD_INFO.json').is_file()
    home = (Path(os.environ['EARTHNG_HOME']) if os.environ.get('EARTHNG_HOME')
            else (local() / 'data' if package else None))
    server = make_server(a.port, home, package)
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    log(f'EarthNG {version()} at {url} (code {ROOT}, data {home or ROOT})')
    print(f'EarthNG {version()} is open at {url}', flush=True)
    print('Keep this window open while you build maps; close it or press Ctrl+C to stop.', flush=True)
    if not a.stay:
        threading.Thread(target=watch_idle, args=(server,), daemon=True).start()
    if not a.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping.set()
        server.service.stop()
        server.server_close()


if __name__ == '__main__':
    main()
