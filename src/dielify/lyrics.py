"""Song lyrics, synced to the music when possible.

Sources, in order: YouTube Music's own lyrics (often timed, from Musixmatch / LyricFind),
then LRCLIB (lrclib.net, free, no account; only the artist, title, album and length are
sent). Results are kept in the `lyrics` table, so they show offline; songs get theirs when
they're downloaded. "None found" is remembered too, and looked up again after NONE_RETRY_S.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Callable

import requests

from . import __version__
from .library import connect

log = logging.getLogger(__name__)

LRCLIB = "https://lrclib.net/api/get"
NONE_RETRY_S = 14 * 86400
_LRC_LINE = re.compile(r"^((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+)(.*)$")
_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def key_of(video_id: str | None, track_id: int | None) -> str | None:
    return video_id or (f"tr-{track_id}" if track_id else None)


def cached(key: str) -> tuple[bool, dict | None]:
    """(known, lyrics). known=False: never looked, or "none found" long enough ago to retry."""
    with connect() as conn:
        row = conn.execute("SELECT body, source, fetched_at FROM lyrics WHERE key = ?", (key,)).fetchone()
    if row is None:
        return False, None
    if row["body"] is None:
        return time.time() - row["fetched_at"] < NONE_RETRY_S, None
    body = json.loads(row["body"])
    body["source"] = row["source"]
    return True, body


def store(key: str, found: dict | None) -> None:
    body = json.dumps({"lines": found["lines"], "text": found["text"]}) if found else None
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO lyrics (key, body, source, fetched_at) VALUES (?,?,?,?)",
                     (key, body, found["source"] if found else None, time.time()))


def parse_lrc(text: str) -> list[tuple[int, str]]:
    """LRC ("[01:02.34] words") -> [(ms, words)], in time order."""
    out = []
    for line in (text or "").splitlines():
        m = _LRC_LINE.match(line.strip())
        if not m:
            continue
        words = m.group(2).strip()
        for mm, ss, frac in _LRC_TIME.findall(m.group(1)):
            ms = (int(mm) * 60 + int(ss)) * 1000 + (int(frac.ljust(3, "0")[:3]) if frac else 0)
            out.append((ms, words))
    return sorted(out, key=lambda x: x[0])


def from_lrclib(artist: str, title: str, album: str | None, duration_s: int | None) -> dict | None:
    params = {"artist_name": artist, "track_name": title}
    if album:
        params["album_name"] = album
    if duration_s:
        params["duration"] = int(duration_s)
    headers = {"User-Agent": f"Dielify/{__version__} (self-hosted music player)"}
    r = requests.get(LRCLIB, params=params, headers=headers, timeout=10)
    if r.status_code == 404 and (album or duration_s):  # the exact match failed: try title + artist only
        r = requests.get(LRCLIB, params={"artist_name": artist, "track_name": title}, headers=headers, timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()
    if d.get("instrumental"):
        return {"lines": None, "text": "♪ Instrumental ♪", "source": "LRCLIB"}
    lines = parse_lrc(d.get("syncedLyrics") or "")
    if lines:
        return {"lines": lines, "text": "\n".join(t for _, t in lines if t), "source": "LRCLIB"}
    plain = (d.get("plainLyrics") or "").strip()
    return {"lines": None, "text": plain, "source": "LRCLIB"} if plain else None


class Busy(Exception):
    """Too many lyrics lookups at once: ask again later."""


# Looking lyrics up waits for YouTube (one call at a time per sign-in) and LRCLIB. A phone
# saving 165 songs asked for all their lyrics at once (9 Nov 2026): every server thread
# ended up waiting here and the PC stopped answering anything. So: two lookups at a time,
# and a request that can't get a turn soon is told to try later (cached lyrics are instant).
_lookups = threading.BoundedSemaphore(2)
WAIT_S = 4.0


def find(key: str, youtube: Callable[[], dict | None] | None, artist: str | None, title: str | None,
         album: str | None = None, duration_s: int | None = None, fresh: bool = False,
         wait_s: float = WAIT_S) -> dict | None:
    """Cached lyrics, else YouTube Music (if `youtube` is given), else LRCLIB; the result
    (or "none") is kept. Synced lyrics from LRCLIB win over YouTube's unsynced ones.
    Raises Busy when two other lookups are running for longer than wait_s."""
    if not fresh:
        known, body = cached(key)
        if known:
            return body
    if not _lookups.acquire(timeout=wait_s):
        raise Busy("Busy looking up other lyrics: try again in a minute")
    try:
        return _look_up(key, youtube, artist, title, album, duration_s)
    finally:
        _lookups.release()


def _look_up(key, youtube, artist, title, album, duration_s) -> dict | None:
    found = None
    try:
        found = youtube() if youtube else None
    except Exception as e:  # noqa: BLE001
        log.info("Lyrics: YouTube had none for %s (%s)", key, e)
    if (found is None or not found["lines"]) and artist and title:
        try:
            lrc = from_lrclib(artist.split(",")[0].strip(), title, album, duration_s)
            if lrc and (found is None or lrc["lines"]):
                found = lrc
        except requests.RequestException as e:
            log.info("Lyrics: LRCLIB didn't answer for %s (%s)", key, e)
            if found is None:
                return None  # don't remember "none" when we couldn't ask
    store(key, found)
    return found
