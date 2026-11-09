"""Signing a TV in with a QR code (0.9.10; the "device code" pattern TVs use).

1. The TV asks to pair (no sign-in): it gets a long secret that only it keeps, and a short
   code (e.g. KDW7-RT3P) that it shows as a QR code and in text. Both last PAIR_TTL_S.
2. A parent's signed-in phone (or the PC app) looks the code up, sees the TV's name and
   address, picks the person the TV is for and allows it. That makes a normal device key
   for that person's phone login, held here until the TV collects it.
3. The TV asks with its secret every couple of seconds and collects the key, once.

The QR code holds only the short code: on its own it grants nothing. Everything is in
memory: a pairing that isn't finished when the server restarts simply starts again.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

PAIR_TTL_S = 10 * 60
MAX_PENDING = 5            # pairings waiting at once (starting one needs no sign-in)
STARTS_PER_ADDRESS = 10    # per address per PAIR_TTL_S
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: easy to read off a TV


class PairError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


@dataclass
class Pairing:
    code: str
    secret_hash: str
    device_name: str
    address: str
    created: float
    status: str = "waiting"           # waiting | approved | refused
    token: str | None = None          # set when approved, handed over once
    device_id: int | None = None
    username: str | None = None
    profile: str | None = None
    approved_by: str | None = None

    @property
    def expires_at(self) -> float:
        return self.created + PAIR_TTL_S


@dataclass
class _State:
    pending: dict[str, Pairing] = field(default_factory=dict)   # by code
    starts: dict[str, list[float]] = field(default_factory=dict)  # by address


_state = _State()
_lock = threading.Lock()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def normalise(code: str) -> str:
    """'kdw7 rt3p', 'KDW7-RT3P' and a scanned 'dielify://pair/KDW7-RT3P' are the same code."""
    code = (code or "").strip()
    if "/" in code:
        code = code.rstrip("/").rsplit("/", 1)[-1]
    raw = "".join(c for c in code.upper() if c.isalnum())
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 8 else raw


def _sweep(now: float) -> None:
    for code, p in list(_state.pending.items()):
        if now > p.expires_at:
            del _state.pending[code]
    for addr, times in list(_state.starts.items()):
        times[:] = [t for t in times if now - t < PAIR_TTL_S]
        if not times:
            del _state.starts[addr]


def start(device_name: str, address: str) -> tuple[str, Pairing]:
    """A new pairing: (secret for the TV, the pairing with its short code)."""
    now = time.time()
    name = " ".join((device_name or "").split())[:60] or "TV"
    with _lock:
        _sweep(now)
        recent = _state.starts.setdefault(address, [])
        if len(recent) >= STARTS_PER_ADDRESS:
            raise PairError("Too many pairing codes from this device. Try again in a few minutes.", 429)
        if len(_state.pending) >= MAX_PENDING:
            raise PairError("Too many TVs are waiting to be paired. Try again in a few minutes.", 429)
        recent.append(now)
        while True:
            raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
            code = f"{raw[:4]}-{raw[4:]}"
            if code not in _state.pending:
                break
        secret = secrets.token_urlsafe(32)
        p = Pairing(code=code, secret_hash=_hash(secret), device_name=name, address=address, created=now)
        _state.pending[code] = p
        return secret, p


def find(code: str) -> Pairing:
    with _lock:
        _sweep(time.time())
        p = _state.pending.get(normalise(code))
    if p is None or p.status != "waiting":
        raise PairError("That code isn't waiting any more. Show a new code on the TV.", 404)
    return p


def approve(code: str, make_token) -> Pairing:
    """make_token(pairing) -> (device_id, token, username, profile) for the chosen person."""
    with _lock:
        _sweep(time.time())
        p = _state.pending.get(normalise(code))
        if p is None or p.status != "waiting":
            raise PairError("That code isn't waiting any more. Show a new code on the TV.", 404)
        p.status = "approved"  # nobody else can approve it meanwhile
    try:
        p.device_id, p.token, p.username, p.profile = make_token(p)
    except Exception:
        with _lock:
            p.status = "waiting"
        raise
    return p


def refuse(code: str) -> None:
    with _lock:
        p = _state.pending.get(normalise(code))
        if p is not None and p.status == "waiting":
            p.status = "refused"


def poll(secret: str) -> Pairing | None:
    """The TV asking. None: unknown or expired. An approved pairing is handed over once
    (then forgotten), so a second ask gets None."""
    h = _hash(secret or "")
    with _lock:
        _sweep(time.time())
        for code, p in list(_state.pending.items()):
            if hmac.compare_digest(p.secret_hash, h):
                if p.status in ("refused",) or (p.status == "approved" and p.token):
                    del _state.pending[code]
                return p
    return None


def forget_all() -> None:
    with _lock:
        _state.pending.clear()
        _state.starts.clear()
