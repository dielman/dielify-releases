"""Remote control between devices (Spotify-Connect style).

Every player (the PC app, phones) keeps a WebSocket open to /api/remote while it can
and reports what it is playing. Like Spotify Connect, each profile has one *active*
device: the one playing (or that last played). Every app's player shows and controls the
active device, wherever it is; starting music on one device pauses the one that was
playing. Picking a device in the list moves the music there (same queue and position).

Nothing is stored: the list lives in memory and a device disappears when its connection
closes. The PC is always reachable; phones are while Dielify runs on them.

Messages, device -> PC:
  {"type": "hello", "device": "<stable id>", "name": "Pixel 9 Pro", "kind": "phone"|"pc"|"tv"}
  {"type": "state", "state": {...}}          see State below; sent on every change
  {"type": "command", "to": "<device>", "command": {...}}
  {"type": "transfer", "from": "<device>", "to": "<device>"}
  {"type": "select", "device": "<device>"}  make it the active device (moves the music)
PC -> device:
  {"type": "devices", "you": "<device>", "active": "<device>"|null, "devices": [{device, name, kind, state}]}
  {"type": "command", "from": "<name>", "command": {...}}
  {"type": "error", "message": "..."}

Apps treat an active device that has been paused for IDLE_S (idle_s in the list) as gone
and play on themselves again, like Spotify, so the phone in the car doesn't start the PC.

Commands: {"action": "play"|"pause"|"next"|"previous"}, {"action": "seek", "position_ms"},
{"action": "jump", "index", "position_ms"} (another song in the queue),
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

# queue: new list around the song playing now (index = where that song is in it); the
# song keeps playing, only what comes after/before changes ("Up next" edits).
ACTIONS = {"play", "pause", "next", "previous", "seek", "volume", "load", "jump", "queue"}
MAX_QUEUE = 1000
PAUSE_GRACE_S = 3.0
MAX_MESSAGE = 512 * 1024
SONG_KEYS = ("track_id", "video_id", "title", "artist", "album", "duration_s", "thumbnail", "gain_db")


def clean_song(s) -> dict | None:
    if not isinstance(s, dict) or not (s.get("track_id") or s.get("video_id")):
        return None
    out = {k: s.get(k) for k in SONG_KEYS if s.get(k) is not None}
    for k in ("title", "artist", "album", "video_id", "thumbnail"):
        if k in out:
            out[k] = str(out[k])[:500]
    if "gain_db" in out:
        try:
            out["gain_db"] = max(-20.0, min(8.0, float(out["gain_db"])))
        except (TypeError, ValueError):
            out.pop("gain_db")
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
    if a == "jump":
        try:
            index = max(0, int(c.get("index") or 0))
        except (TypeError, ValueError):
            return None
        return {"action": a, "index": index, "position_ms": max(0, int(c.get("position_ms") or 0))}
    if a == "volume":
        return {"action": a, "value": min(1.0, max(0.0, float(c.get("value") or 0)))}
    if a == "load":
        st = clean_state(c)
        if not st["queue"]:
            return None
        return {"action": a, "queue": st["queue"], "index": max(0, st["index"]),
                "position_ms": st["position_ms"], "playing": c.get("playing", True) is not False}
    if a == "queue":
        st = clean_state(c)
        if not st["queue"] or not 0 <= st["index"] < len(st["queue"]):
            return None
        return {"action": a, "queue": st["queue"], "index": st["index"]}
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
    paused_at: float = field(default_factory=time.monotonic)
    told_pause_at: float = 0.0  # when the hub last told it to pause (0 = it has since)

    def public(self) -> dict:
        st = dict(self.state)
        if st:
            st["position_ms"] = now_position(self.state, self.received)
        idle = 0 if self.state.get("playing") else int(time.monotonic() - self.paused_at)
        return {"device": self.device, "name": self.name, "kind": self.kind, "state": st or None, "idle_s": idle}


class Hub:
    def __init__(self):
        self.devices: dict[tuple[str, str], Device] = {}
        self.active: dict[str, str] = {}  # profile -> device id
        self._tasks: set[asyncio.Task] = set()
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
        active = self.active.get(profile)
        await asyncio.gather(*(self.send(d, {"type": "devices", "you": d.device, "active": active, "devices": listing})
                               for d in devs))

    async def tell(self, dev: Device, sender: str, cmd: dict) -> None:
        """Send a command to a device, remembering pauses: a report saying "playing" that
        was already on its way when the pause went out must not count as a new start."""
        if cmd["action"] == "pause":
            dev.told_pause_at = time.monotonic()
            if dev.state.get("playing"):
                dev.state["playing"] = False
                dev.paused_at = dev.told_pause_at
        elif cmd["action"] in ("play", "load", "jump"):
            dev.told_pause_at = 0.0
        log.info("Remote: %s -> %s: %s", sender, dev.name, cmd["action"])
        await self.send(dev, {"type": "command", "from": sender, "command": cmd})

    async def make_active(self, d: Device) -> None:
        """`d` is playing now: it becomes the active device and the one before it stops."""
        before = self.find(d.profile, self.active.get(d.profile))
        self.active[d.profile] = d.device
        if before is not None and before is not d and before.state.get("playing"):
            await self.tell(before, d.name, {"action": "pause"})

    async def transfer(self, by: Device, src: Device, dst: Device) -> bool:
        st = src.state
        if not st.get("queue") or st.get("index", -1) < 0:
            return False
        self.active[by.profile] = dst.device
        log.info("Remote: music moves from %s to %s", src.name, dst.name)
        await self.tell(dst, by.name, {
            "action": "load", "queue": st["queue"], "index": st["index"],
            "position_ms": now_position(st, src.received), "playing": True})
        if st.get("playing"):
            await self.tell(src, by.name, {"action": "pause"})
        return True

    async def join(self, d: Device) -> None:
        old = self.devices.get((d.profile, d.device))
        self.devices[(d.profile, d.device)] = d
        if old is not None and old.ws is not d.ws:
            try:
                await old.ws.close(code=4000, reason="Connected again elsewhere")
            except Exception:
                pass
        log.info("Remote: %s (%s) connected", d.name, d.kind)
        if d.state.get("playing"):
            await self.make_active(d)
        elif d.profile not in self.active and d.state.get("queue"):
            self.active[d.profile] = d.device
        await self.broadcast(d.profile)

    async def leave(self, d: Device) -> None:
        if self.devices.get((d.profile, d.device)) is d:
            del self.devices[(d.profile, d.device)]
            if self.active.get(d.profile) == d.device:
                del self.active[d.profile]
            log.info("Remote: %s left", d.name)
            # its own task: a connection can end by cancellation, which would cancel this too
            task = asyncio.get_running_loop().create_task(self.broadcast(d.profile))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def find(self, profile: str, device) -> Device | None:
        return self.devices.get((profile, str(device)))

    async def handle(self, d: Device, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "state":
            was_playing = d.state.get("playing")
            st = clean_state(msg.get("state"))
            if d.told_pause_at:
                if not st["playing"] or time.monotonic() - d.told_pause_at > PAUSE_GRACE_S:
                    d.told_pause_at = 0.0
                else:
                    st["playing"] = False  # an old report, sent before our pause arrived
            d.state, d.received = st, time.monotonic()
            if was_playing and not d.state["playing"]:
                d.paused_at = d.received
            if d.state["playing"] and (not was_playing or self.active.get(d.profile) != d.device):
                await self.make_active(d)
            elif d.profile not in self.active and d.state["queue"]:
                self.active[d.profile] = d.device
            await self.broadcast(d.profile)
        elif kind == "command":
            target, cmd = self.find(d.profile, msg.get("to")), clean_command(msg.get("command"))
            if target is None or cmd is None:
                await self.send(d, {"type": "error", "message": "That device isn't connected" if cmd else "Unknown command"})
                return
            await self.tell(target, d.name, cmd)
        elif kind == "transfer":
            src, dst = self.find(d.profile, msg.get("from")), self.find(d.profile, msg.get("to"))
            if src is None or dst is None or src is dst:
                await self.send(d, {"type": "error", "message": "That device isn't connected"})
                return
            if not await self.transfer(d, src, dst):
                await self.send(d, {"type": "error", "message": f"Nothing is playing on {src.name}"})
                return
            await self.broadcast(d.profile)
        elif kind == "note":  # a device explaining itself, for the log
            log.info("Remote: %s says: %s", d.name, str(msg.get("text") or "")[:200])
        elif kind == "select":
            dst = self.find(d.profile, msg.get("device"))
            if dst is None:
                await self.send(d, {"type": "error", "message": "That device isn't connected"})
                return
            src = self.find(d.profile, self.active.get(d.profile))
            if src is not None and src is not dst and await self.transfer(d, src, dst):
                pass
            else:
                self.active[d.profile] = dst.device
            await self.broadcast(d.profile)


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
        kind = "pc" if desktop or hello.get("kind") == "pc" else "tv" if hello.get("kind") == "tv" else "phone"
        d = Device(ws, profile, str(hello["device"])[:100], name, kind)
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
