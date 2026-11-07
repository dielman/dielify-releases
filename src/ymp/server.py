"""The network server: Subsonic API now, our own /api endpoints from Phase 3.

Security: it listens only on loopback, home-network (private) and Tailscale
addresses, never on all interfaces. Request logs never include query strings,
because Subsonic clients put login tokens there.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request

from . import __version__
from .downloads import DownloadQueue
from .settings import Settings, check_bind_address, is_allowed_bind

log = logging.getLogger("ymp.server")

SHUTDOWN_GRACE_S = 3


def create_app(queue: DownloadQueue | None = None) -> FastAPI:
    from .custom_api import router as custom_router
    from .subsonic_api import router as subsonic_router

    queue = queue or DownloadQueue()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        queue.start()
        yield
        queue.stop()

    # /api/openapi.json is the Android app's contract (also saved in docs/openapi.json).
    app = FastAPI(title="ymp", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.queue = queue
    app.include_router(subsonic_router)
    app.include_router(custom_router)

    @app.get("/api/health", tags=["status"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        client = request.client.host if request.client else "?"
        # path only: the query string can hold passwords and tokens
        log.info("%s %s %s %d %.0fms", client, request.method, request.url.path,
                 response.status_code, (time.perf_counter() - start) * 1000)
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


def run(s: Settings, addrs: list[str]) -> None:
    sockets = []
    for a in addrs:
        try:
            sockets.append(_listen(a, s.server_port))
        except OSError as e:
            log.warning("Can't listen on %s:%d (%s)", a, s.server_port, e)
    if not sockets:
        raise OSError(f"Could not listen on any address (port {s.server_port} in use?)")
    # A paused phone holds its stream open without reading, so a graceful shutdown
    # would wait for it forever: give open connections a few seconds, then close them.
    config = uvicorn.Config(create_app(), access_log=False, log_level="warning",
                            server_header=False, timeout_graceful_shutdown=SHUTDOWN_GRACE_S)
    logging.getLogger("uvicorn.error").addFilter(_ExpectedShutdownNoise())
    _Server(config).run(sockets=sockets)


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
