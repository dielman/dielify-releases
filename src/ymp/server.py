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

from fastapi import FastAPI, Request

from . import __version__
from .settings import Settings, check_bind_address, is_allowed_bind

log = logging.getLogger("ymp.server")


def create_app() -> FastAPI:
    from .subsonic_api import router as subsonic_router

    # Docs stay off until Phase 3 defines our own API (the Android app's contract).
    app = FastAPI(title="ymp", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.include_router(subsonic_router)

    @app.get("/api/health")
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
    import uvicorn

    sockets = []
    for a in addrs:
        try:
            sockets.append(_listen(a, s.server_port))
        except OSError as e:
            log.warning("Can't listen on %s:%d (%s)", a, s.server_port, e)
    if not sockets:
        raise OSError(f"Could not listen on any address (port {s.server_port} in use?)")
    config = uvicorn.Config(create_app(), access_log=False, log_level="warning",
                            server_header=False)
    uvicorn.Server(config).run(sockets=sockets)
