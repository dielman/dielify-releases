"""Remote control between devices (Spotify-Connect style).

Every player (the PC app, phones) keeps a WebSocket open to /api/remote while it can
and reports what it is playing. Devices of the same profile see each other and can send
each other commands: play, pause, next, previous, seek, volume, load a queue, or move
playback ("transfer") from one device to another with the same queue and position.

Nothing is stored: the list lives in memory and a device disappears when its connection
closes. The PC is always reachable; phones are while Dielify runs on them.

Messages, device -> PC:
  {"type": "hello", "device": "<stable id>", "name": "Pixel 9 Pro", "kind": "phone"|"pc"}
  {"type": "state", "state": {...}}          see State below; sent on every change
  {"type": "command", "to": "<device>", "command": {...}}
  {"type": "transfer", "from": "<device>", "to": "<device>"}
PC -> device:
  {"type": "devices", "you": "<device>", "devices": [{device, name, kind, state, age_ms}]}
  {"type": "command", "from": "<name>", "command": {...}}
  {"type": "error", "message": "..."}

Commands: {"action": "play"|"pause"|"next"|"previous"}, {"action": "seek", "position_ms"},
{"action": "volume", "value": 0..1}, {"action": "load", "queue": [Song], "index",
"position_ms", "playing"}.  A Song is {track_id?, video_id?, title, artist, album,
duration_s?, thumbnail?}: library songs by track id, anything else by YouTube video id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth
from . import settings as settings_mod
from . import custom_api

log = logging.getLogger(__name__)
router = APIRouter()

ACTIONS = {"play", "pause", "next", "previous", "seek", "volume", "load"}
MAX_QUEUE = 1000
MAX_MESSAGE = 512 * 1024
SONG_KEYS = ("track_id", "video_id", "title", "artist", "album", "duration_s", "thumbnail")


def clean_song(s) -> dict | None:
    if not isinstance(s, dict) or not (s.get("track_id") or s.get("video_id")):
        return None
    out = {k: s.get(k) for k in SONG_KEYS if s.get(k) is not None}
    for k in ("title", "artist", "album", "video_id", "thumbnail"):
        if k in out:
            out[k] = str(out[k])[:500]
    for k in ("track_id", "duration_s"):
        if k in out:
            try:
                out[k] = int(out[k])
            except (TypeError, ValueError):
                out.pop(k)
    return out if (out.get("track_id") or out.get("video_id")) else None


def clean_state(s) -> dict:
    """What a device says it's doing: playing, position_ms, duration_ms, volume, index,
    queue (songs). Unknown keys are dropped; sizes are capped."""
    if not isinstance(s, dict):
        return {}
    queue = [q for q in (clean_song(x) for x in (s.get("queue") or [])[:MAX_QUEUE]) if q]
    index = s.get("index") if isinstance(s.get("index"), int) else -1
    return {
        "playing": bool(s.get("playing")),
        "position_ms": max(0, int(s.get("position_ms") or 0)),
        "duration_ms": max(0, int(s.get("duration_ms") or 0)) or None,
        "volume": min(1.0, max(0.0, float(s.get("volume") if s.get("volume") is not None else 1.0))),
        "index": index if 0 <= index < len(queue) else -1,
        "queue": queue,
    }


def clean_command(c) -> dict | None:
    if not isinstance(c, dict) or c.get("action") not in ACTIONS:
        return None
    a = c["action"]
    if a == "seek":
        return {"action": a, "position_ms": max(0, int(c.get("position_ms") or 0))}
    if a == "volume":
        return {"action": a, "value": min(1.0, max(0.0, float(c.get("value") or 0)))}
    if a == "load":
        st = clean_state(c)
        if not st["queue"]:
            return None
        return {"action": a, "queue": st["queue"], "index": max(0, st["index"]),
                "position_ms": st["position_ms"], "playing": c.get("playing", True) is not False}
    return {"action": a}


def now_position(state: dict, received: float) -> int:
    """Where the song is now, from the last report."""
    pos = state.get("position_ms") or 0
    if state.get("playing"):
        pos += int((time.monotonic() - received) * 1000)
    dur = state.get("duration_ms")
    return min(pos, dur) if dur else pos


@dataclass
class Device:
    ws: WebSocket
    profile: str
    device: str
    name: str
    kind: str
    state: dict = field(default_factory=dict)
    received: float = field(default_factory=time.monotonic)

    def public(self) -> dict:
        st = dict(self.state)
        if st:
            st["position_ms"] = now_position(self.state, self.received)
        return {"device": self.device, "name": self.name, "kind": self.kind, "state": st or None}


class Hub:
    def __init__(self):
        self.devices: dict[tuple[str, str], Device] = {}
        self.lock = asyncio.Lock()

    def of(self, profile: str) -> list[Device]:
        return [d for (p, _), d in self.devices.items() if p == profile]

    async def send(self, d: Device, msg: dict) -> None:
        try:
            await d.ws.send_text(json.dumps(msg))
        except Exception:  # closed meanwhile: its own loop cleans up
            pass

    async def broadcast(self, profile: str) -> None:
        devs = self.of(profile)
        listing = [d.public() for d in devs]
        await asyncio.gather(*(self.send(d, {"type": "devices", "you": d.device, "devices": listing}) for d in devs))

    async def join(self, d: Device) -> None:
        old = self.devices.get((d.profile, d.device))
        self.devices[(d.profile, d.device)] = d
        if old is not None and old.ws is not d.ws:
            try:
                await old.ws.close(code=4000, reason="Connected again elsewhere")
            except Exception:
                pass
        log.info("Remote: %s (%s) connected", d.name, d.kind)
        await self.broadcast(d.profile)

    async def leave(self, d: Device) -> None:
        if self.devices.get((d.profile, d.device)) is d:
            del self.devices[(d.profile, d.device)]
            log.info("Remote: %s left", d.name)
            await self.broadcast(d.profile)

    def find(self, profile: str, device) -> Device | None:
        return self.devices.get((profile, str(device)))

    async def handle(self, d: Device, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "state":
            d.state, d.received = clean_state(msg.get("state")), time.monotonic()
            await self.broadcast(d.profile)
        elif kind == "command":
            target, cmd = self.find(d.profile, msg.get("to")), clean_command(msg.get("command"))
            if target is None or cmd is None:
                await self.send(d, {"type": "error", "message": "That device isn't connected" if cmd else "Unknown command"})
                return
            await self.send(target, {"type": "command", "from": d.name, "command": cmd})
        elif kind == "transfer":
            src, dst = self.find(d.profile, msg.get("from")), self.find(d.profile, msg.get("to"))
            if src is None or dst is None or src is dst:
                await self.send(d, {"type": "error", "message": "That device isn't connected"})
                return
            st = src.state
            if not st.get("queue") or st.get("index", -1) < 0:
                await self.send(d, {"type": "error", "message": f"Nothing is playing on {src.name}"})
                return
            await self.send(dst, {"type": "command", "from": d.name, "command": {
                "action": "load", "queue": st["queue"], "index": st["index"],
                "position_ms": now_position(st, src.received), "playing": True}})
            await self.send(src, {"type": "command", "from": d.name, "command": {"action": "pause"}})


hub = Hub()


def _authenticate(ws: WebSocket) -> tuple[str, bool] | None:
    """(profile this connection acts for, is it the PC app), or None. Token in the query (browsers can't
    set headers on WebSockets) or the Authorization header."""
    client = ws.client.host if ws.client else "?"
    lockout = custom_api.lockout  # (looked up each time: tests replace it)
    if lockout.is_locked(client):
        return None
    header = ws.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ws.query_params.get("token")
    if not token:
        return None
    if auth.is_desktop_token(token):
        return settings_mod.load().active_profile, True
    found = auth.check_token(token)
    if found is None:
        lockout.failed(client)
        return None
    return found[0].profile, False


@router.websocket("/api/remote")
async def remote(ws: WebSocket) -> None:
    who = _authenticate(ws)
    if who is None:
        await ws.close(code=4401, reason="Sign in first")
        return
    profile, desktop = who
    await ws.accept()
    d: Device | None = None
    try:
        hello = json.loads(await asyncio.wait_for(ws.receive_text(), 15))
        if hello.get("type") != "hello" or not hello.get("device"):
            await ws.close(code=4400, reason="Say hello first")
            return
        name = str(hello.get("name") or "")[:60] or ((platform.node() or "PC") if desktop else "Phone")
        d = Device(ws, profile, str(hello["device"])[:100], name, "pc" if desktop or hello.get("kind") == "pc" else "phone")
        if isinstance(hello.get("state"), dict):
            d.state = clean_state(hello["state"])
        await hub.join(d)
        while True:
            text = await ws.receive_text()
            if len(text) > MAX_MESSAGE:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if isinstance(msg, dict):
                await hub.handle(d, msg)
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, RuntimeError):
        pass
    finally:
        if d is not None:
            await hub.leave(d)
