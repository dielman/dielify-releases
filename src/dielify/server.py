"""The network server: Subsonic API now, our own /api endpoints from Phase 3.

Security: it listens only on loopback, home-network (private) and Tailscale
addresses, never on all interfaces. Request logs never include query strings,
because Subsonic clients put login tokens there.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from . import __version__
from .downloads import DownloadQueue
from .settings import Settings, check_bind_address, is_allowed_bind

log = logging.getLogger("dielify.server")

SHUTDOWN_GRACE_S = 3
UI_DIR = Path(__file__).with_name("ui")
# The desktop window holds the PC-only key, so its page may only run Dielify's own script
# and only show pictures from dielify and YouTube's image servers.
UI_CSP = ("default-src 'self'; script-src 'self'; connect-src 'self'; media-src 'self'; "
          "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
          "img-src 'self' data: https://*.googleusercontent.com https://*.ggpht.com https://*.ytimg.com "
          "https://music.youtube.com https://www.gstatic.com")


def create_app(queue: DownloadQueue | None = None) -> FastAPI:
    from .custom_api import router as custom_router
    from .custom_api import youtube
    from .desktop_api import router as desktop_router
    from .playlist_api import router as playlist_router
    from .remote import router as remote_router
    from .discovery import Discovery
    from .mixes import MixMaker
    from .playlists import Playlists
    from .subsonic_api import router as subsonic_router

    queue = queue or DownloadQueue()
    playlists = Playlists(youtube.call, queue)
    mix_maker = MixMaker(youtube.call)
    outside = Discovery(youtube.call)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        queue.start()
        playlists.start()
        mix_maker.start()
        outside.start()
        yield
        outside.stop()
        mix_maker.stop()
        playlists.stop()
        queue.stop()

    # /api/openapi.json is the Android app's contract (also saved in docs/openapi.json).
    app = FastAPI(title="Dielify", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.queue = queue
    app.state.playlists = playlists
    app.state.mixes = mix_maker
    app.state.discovery = outside
    app.include_router(subsonic_router)
    app.include_router(custom_router)
    app.include_router(playlist_router)
    app.include_router(remote_router)
    app.include_router(desktop_router)
    # The desktop app's screens. They hold no data; everything comes from /api with a key.
    app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        """Say what went wrong instead of a bare 500. The full details are only shown to
        the desktop window on this PC; phones get a short message."""
        from fastapi.responses import JSONResponse

        from .auth import is_desktop_token
        from .paths import app_data_dir
        bearer = request.headers.get("authorization", "")[7:] or request.query_params.get("token")
        if is_desktop_token(bearer):
            detail = (f"Dielify hit an error: {type(exc).__name__}: {exc}  "
                      f"(details in {app_data_dir() / 'logs' / 'server.log'})")
        else:
            detail = "Dielify hit an unexpected error on the PC."
        return JSONResponse({"detail": detail}, status_code=500)

    @app.get("/api/health", tags=["status"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        client = request.client.host if request.client else "?"
        try:
            response = await call_next(request)
        except Exception:
            log.exception("%s %s %s failed", client, request.method, request.url.path)
            raise
        # path only: the query string can hold passwords and tokens
        log.info("%s %s %s %d %.0fms", client, request.method, request.url.path,
                 response.status_code, (time.perf_counter() - start) * 1000)
        if request.url.path.startswith("/ui"):
            response.headers["Content-Security-Policy"] = UI_CSP
        return response

    return app


def lan_addresses() -> list[str]:
    """This PC's IPv4 addresses on home networks and Tailscale."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except socket.gaierror:
        pass
    allowed = [ip for ip in found
               if is_allowed_bind(ipaddress.ip_address(ip)) and not ipaddress.ip_address(ip).is_loopback]
    return sorted(allowed, key=ipaddress.ip_address)


def bind_addresses(s: Settings) -> list[str]:
    if s.server_bind == "auto":
        return ["127.0.0.1", *lan_addresses()]
    addrs = [a.strip() for a in s.server_bind.split(",") if a.strip()]
    for a in addrs:
        check_bind_address(a)  # never 0.0.0.0, never public
    return addrs


def _listen(addr: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in addr else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no port hijacking by other apps
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind((addr, port))
    sock.listen(128)
    sock.setblocking(False)
    return sock


def setup_file_logging() -> Path:
    """Server requests -> %LOCALAPPDATA%\\Dielify\\logs\\server.log (no secrets)."""
    from .paths import app_data_dir
    logs = app_data_dir() / "logs"
    logs.mkdir(exist_ok=True)
    fh = RotatingFileHandler(logs / "server.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(fh)
    if root.level > logging.WARNING or root.level == logging.NOTSET:
        root.setLevel(logging.WARNING)
    for name in ("dielify.server", "dielify.subsonic_api", "dielify.downloads", "dielify.remote"):
        logging.getLogger(name).setLevel(logging.INFO)
    return logs / "server.log"


def _sockets(s: Settings, addrs: list[str]) -> list[socket.socket]:
    sockets = []
    for a in addrs:
        try:
            sockets.append(_listen(a, s.server_port))
        except OSError as e:
            log.warning("Can't listen on %s:%d (%s)", a, s.server_port, e)
    if not sockets:
        raise OSError(f"Could not listen on any address (port {s.server_port} in use?)")
    return sockets


def _config(queue: DownloadQueue | None = None) -> uvicorn.Config:
    # A paused phone holds its stream open without reading, so a graceful shutdown
    # would wait for it forever: give open connections a few seconds, then close them.
    logging.getLogger("uvicorn.error").addFilter(_ExpectedShutdownNoise())
    # log_config=None: uvicorn's own logging setup checks the console for colour
    # support and crashes when there is no console (the installed app). Its messages
    # then go to our log file through the root logger instead.
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    return uvicorn.Config(create_app(queue), access_log=False, log_config=None, use_colors=False,
                          server_header=False, timeout_graceful_shutdown=SHUTDOWN_GRACE_S)


ADDRESS_CHECK_S = 30


class AddressWatcher:
    """Also listen on addresses that appear after start-up. Tailscale often connects
    after Dielify has started with Windows; without this, phones away from home could
    never reach the PC until Dielify was restarted. Only with server_bind = "auto",
    and only ever on loopback, home-network or Tailscale addresses."""

    def __init__(self, s: Settings, app, bound: list[str]):
        self.s, self.app, self.bound = s, app, set(bound)
        self.extra: list[uvicorn.Server] = []
        self._stop = threading.Event()

    def start(self) -> None:
        if self.s.server_bind == "auto":
            threading.Thread(target=self._loop, name="dielify-addresses", daemon=True).start()

    def check(self) -> list[str]:
        added = []
        for addr in bind_addresses(self.s):  # never 0.0.0.0, never public
            if addr in self.bound:
                continue
            try:
                sock = _listen(addr, self.s.server_port)
            except OSError as e:
                log.warning("Can't listen on new address %s:%d (%s)", addr, self.s.server_port, e)
                continue
            # Same app, its own small server; lifespan off so the download queue isn't
            # started a second time.
            srv = uvicorn.Server(uvicorn.Config(
                self.app, lifespan="off", access_log=False, log_config=None, use_colors=False,
                server_header=False, timeout_graceful_shutdown=SHUTDOWN_GRACE_S))
            threading.Thread(target=srv.run, kwargs={"sockets": [sock]}, daemon=True,
                             name=f"dielify-server-{addr}").start()
            self.extra.append(srv)
            self.bound.add(addr)
            added.append(addr)
            log.info("Now also listening on %s:%d", addr, self.s.server_port)
        return added

    def _loop(self) -> None:
        while not self._stop.wait(ADDRESS_CHECK_S):
            try:
                self.check()
            except Exception:
                log.exception("Address check failed")

    def stop(self) -> None:
        self._stop.set()
        for srv in self.extra:
            srv.should_exit = True


def run(s: Settings, addrs: list[str]) -> None:
    """`dielify serve`: run in the foreground until Ctrl+C."""
    sockets = _sockets(s, addrs)
    config = _config()
    watcher = AddressWatcher(s, config.app, [sk.getsockname()[0] for sk in sockets])
    watcher.start()
    try:
        _Server(config).run(sockets=sockets)
    finally:
        watcher.stop()


def start_background(s: Settings, addrs: list[str]) -> uvicorn.Server:
    """The desktop app: run the server on a background thread. Stop it with
    `server.should_exit = True`. Raises OSError if the port is taken."""
    if "127.0.0.1" not in addrs:
        addrs = ["127.0.0.1", *addrs]  # the desktop window talks to localhost
    sockets = _sockets(s, addrs)
    if not any(sk.getsockname()[0] == "127.0.0.1" for sk in sockets):
        for sk in sockets:
            sk.close()
        raise OSError(f"Port {s.server_port} is already in use on this PC")
    srv = uvicorn.Server(_config())
    thread = threading.Thread(target=srv.run, kwargs={"sockets": sockets}, name="dielify-server", daemon=True)
    thread.start()
    for _ in range(100):  # wait until it's accepting connections
        if srv.started:
            break
        time.sleep(0.05)
    srv.watcher = AddressWatcher(s, srv.config.app, [sk.getsockname()[0] for sk in sockets])
    srv.watcher.start()
    return srv


class _Server(uvicorn.Server):
    def handle_exit(self, sig, frame) -> None:
        if not self.should_exit:
            print(f"Stopping… (open phone connections are closed within {SHUTDOWN_GRACE_S} s; "
                  "press Ctrl+C again to stop at once)", flush=True)
        super().handle_exit(sig, frame)


class _ExpectedShutdownNoise(logging.Filter):
    """Cutting off a paused phone's stream on shutdown is normal, not an error."""
    def filter(self, record: logging.LogRecord) -> bool:
        return "timeout graceful shutdown exceeded" not in record.getMessage()
