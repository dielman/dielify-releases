"""User settings stored as JSON in the app data folder.

Phase 4's GUI edits the same file through the same functions.
"""

from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .paths import app_data_dir, default_library_root

QUALITIES = ("auto", "high", "standard")
FORMATS = ("auto", "m4a", "opus")


@dataclass
class Settings:
    library_root: str = ""
    quality: str = "auto"         # auto = best available (Premium: ~256k Opus)
    preferred_format: str = "auto"  # auto keeps whatever is best; never re-encodes
    cache_limit_gb: float = 0.0    # 0 = unlimited (eviction arrives with the library)
    active_profile: str = "default"
    request_delay_s: float = 1.5   # keep traffic modest and human-like
    server_port: int = 4747
    # "auto" = this PC's home-network and Tailscale addresses (+ localhost), or a
    # comma-separated list of IPs. Never all interfaces, never a public address.
    server_bind: str = "auto"

    def __post_init__(self) -> None:
        if not self.library_root:
            self.library_root = str(default_library_root())

    def validate(self) -> None:
        if self.quality not in QUALITIES:
            raise ValueError(f"quality must be one of {QUALITIES}")
        if self.preferred_format not in FORMATS:
            raise ValueError(f"preferred_format must be one of {FORMATS}")
        if self.cache_limit_gb < 0:
            raise ValueError("cache_limit_gb cannot be negative")
        if self.request_delay_s < 0:
            raise ValueError("request_delay_s cannot be negative")
        if not 1024 <= self.server_port <= 65535:
            raise ValueError("server_port must be between 1024 and 65535")
        if self.server_bind != "auto":
            for ip in self.server_bind.split(","):
                check_bind_address(ip.strip())

    def profile_library(self, profile: str | None = None) -> Path:
        from .paths import safe_name
        return Path(self.library_root) / safe_name(profile or self.active_profile)


TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def is_allowed_bind(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Loopback, home-network (private) or Tailscale addresses only."""
    if ip.is_unspecified or ip.is_link_local:
        return False
    return ip.is_loopback or ip.is_private or ip in TAILSCALE_NET


def check_bind_address(text: str) -> None:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        raise ValueError(f"server_bind: '{text}' is not an IP address") from None
    if ip.is_unspecified:
        raise ValueError("server_bind: refusing to listen on all interfaces (0.0.0.0 / ::). "
                         "Use 'auto' or this PC's home-network / Tailscale address.")
    if not is_allowed_bind(ip):
        raise ValueError(f"server_bind: {ip} is not a private, Tailscale or loopback address; "
                         "ymp is never exposed to the public internet.")


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def load() -> Settings:
    path = settings_path()
    if not path.exists():
        return Settings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Settings)}
    s = Settings(**{k: v for k, v in raw.items() if k in known})
    s.validate()
    return s


def save(s: Settings) -> None:
    s.validate()
    path = settings_path()
    # write-then-rename so a crash never leaves a half-written settings file
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(s), f, indent=2)
    os.replace(tmp, path)


def set_value(key: str, value: str) -> Settings:
    s = load()
    types = {f.name: f.type for f in fields(Settings)}
    if key not in types:
        raise KeyError(f"Unknown setting '{key}'. Known: {', '.join(types)}")
    if key == "library_root":
        value = str(Path(value).expanduser().resolve())
    current = getattr(s, key)
    setattr(s, key, type(current)(value))
    save(s)
    return s
