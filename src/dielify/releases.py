"""New releases from your artists ("New for you").

Watched artists = the ones you follow + your 20 most-played (left-out-of-taste plays don't
count). Once a day each one's YouTube Music page is read (artists.read_page) in the
background, at a quiet moment, and new albums and singles are remembered. "New for you"
lists what turned up in the last 60 days (on the very first look: this year's releases),
leaving out albums already in your library.

Optional, per person (not kids accounts): download new albums automatically. Only releases
that appear after the first look are downloaded, never an artist's back catalogue.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

from . import artists, history, library
from .library import connect, library_for
from .ratings import BAN, Ratings, artist_key
from .yt_adapter import YTItem

log = logging.getLogger(__name__)

TOP = 20
NEW_DAYS = 60
CHECK_EVERY_S = 20 * 3600
LIST_LIMIT = 30


# --- per-person settings ----------------------------------------------------------------

def pref(profile: str, key: str, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM prefs WHERE profile = ? AND key = ?", (profile, key)).fetchone()
    return json.loads(row["value"]) if row else default


def set_pref(profile: str, key: str, value) -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO prefs (profile, key, value) VALUES (?,?,?)",
                     (profile, key, json.dumps(value)))


def auto_download(profile: str) -> bool:
    return bool(pref(profile, "new_releases_auto", False))


# --- follows ----------------------------------------------------------------------------

def follows(profile: str) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT key, name, channel_id, added_at FROM follows WHERE profile = ? ORDER BY name COLLATE NOCASE",
            (profile,))]


def set_follow(profile: str, name: str, on: bool, channel_id: str | None = None) -> None:
    key = artist_key(name)
    with connect() as conn:
        if on:
            conn.execute("INSERT OR REPLACE INTO follows (profile, key, name, channel_id, added_at) VALUES (?,?,?,?,?)",
                         (profile, key, name[:300], channel_id, time.time()))
        else:
            conn.execute("DELETE FROM follows WHERE profile = ? AND key = ?", (profile, key))


def is_followed(profile: str, name: str) -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM follows WHERE profile = ? AND key = ?",
                            (profile, artist_key(name))).fetchone() is not None


def watched(profile: str) -> list[tuple[str, str | None]]:
    """(name, channel id if known) of every artist watched for this person."""
    out = {f["key"]: (f["name"], f["channel_id"]) for f in follows(profile)}
    r = Ratings(profile)
    for name in history.top_artists(library_for(profile), limit=TOP):
        k = artist_key(name)
        if k not in out and r.value(None, [name]) != BAN:
            out[k] = (name, None)
    return list(out.values())


# --- the list -----------------------------------------------------------------------------

def _channels(profile: str) -> dict[str, str]:
    """channel id -> artist name, for the watched artists already found on YouTube."""
    names = watched(profile)
    keys = [artist_key(n) for n, _ in names]
    out = {c: n for n, c in names if c}
    if keys:
        with connect() as conn:
            marks = ",".join("?" * len(keys))
            for r in conn.execute(f"SELECT name, channel_id FROM yt_artists WHERE key IN ({marks}) "
                                  f"AND channel_id IS NOT NULL", keys):
                out.setdefault(r["channel_id"], r["name"])
    return out


def new_for_you(profile: str, days: int = NEW_DAYS, limit: int = LIST_LIMIT) -> list[YTItem]:
    """Releases from your artists that turned up lately, newest first (albums already in
    your library left out). Kids accounts: the API filters these like any other album."""
    channels = _channels(profile)
    if not channels:
        return []
    with connect() as conn:
        marks = ",".join("?" * len(channels))
        rows = conn.execute(
            f"SELECT * FROM artist_releases WHERE channel_id IN ({marks}) AND first_seen >= ? "
            f"ORDER BY first_seen DESC, year DESC LIMIT ?",
            (*channels, time.time() - days * 86400, limit * 3)).fetchall()
        have = {(r["album"] or "").casefold() for r in conn.execute(
            "SELECT DISTINCT al.name AS album FROM library_items li JOIN tracks t ON t.id = li.track_id "
            "JOIN albums al ON al.id = t.album_id WHERE li.profile = ?", (profile,))}
    out = []
    for r in rows:
        if r["title"].casefold() in have:
            continue
        out.append(YTItem("album", r["browse_id"], r["title"], [r["artist"]], year=r["year"],
                          thumbnail=r["thumbnail"], subtitle=r["kind"],
                          explicit=None if r["explicit"] is None else bool(r["explicit"])))
    return out[:limit]


# --- the daily check ----------------------------------------------------------------------

def check(profile: str, call: Callable[..., object], queue=None, force: bool = False,
          stop: threading.Event | None = None) -> int:
    """Read the watched artists' pages that weren't read lately. Returns how many were read.
    New albums are queued for download when the person turned that on."""
    read = 0
    for name, channel in watched(profile):
        if stop is not None and stop.is_set():
            break
        try:
            channel = channel or artists.channel_for(call, name)
            if not channel:
                continue
            with connect() as conn:
                row = conn.execute("SELECT page_at FROM yt_artists WHERE channel_id = ?", (channel,)).fetchone()
            if not force and row and row["page_at"] and time.time() - row["page_at"] < CHECK_EVERY_S:
                continue
            if row is None:  # a followed artist's channel came from YouTube directly
                with connect() as conn:
                    conn.execute("INSERT OR IGNORE INTO yt_artists (key, name, channel_id, checked_at) VALUES (?,?,?,?)",
                                 (artist_key(name), name, channel, time.time()))
            page, fresh = artists.read_page(call, channel, name)
            read += 1
        except Exception as e:  # noqa: BLE001  (offline, signed out, YouTube trouble: try tomorrow)
            log.info("New releases: couldn't read %r: %s", name, e)
            return read
        if fresh and queue is not None and auto_download(profile) and library.person(profile)["role"] != "child":
            for browse_id in fresh:
                try:
                    info, tracks = call("album", browse_id)
                    if tracks:
                        queue.enqueue(profile, tracks, "album", info.title, "new releases")
                        log.info("New releases: downloading %s by %s", info.title, name)
                except Exception as e:  # noqa: BLE001
                    log.info("New releases: couldn't queue %s: %s", browse_id, e)
    if read:
        log.info("New releases: read %d artist pages for %s", read, profile)
    return read


class ReleaseWatcher:
    """Background thread: checks everyone's artists a few minutes after start, then every
    few hours (each artist at most once a day)."""

    def __init__(self, call: Callable[[str], Callable[..., object]], queue=None):
        self.call = call      # profile -> call(fn_name, *args)
        self.queue = queue
        self._stop = threading.Event()
        self._busy = threading.Lock()

    def run_once(self, profiles: list[str] | None = None, force: bool = False) -> None:
        from . import settings as settings_mod
        if settings_mod.load().offline or not self._busy.acquire(blocking=False):
            return
        try:
            for p in profiles or library.profiles():
                check(p, self.call(p), self.queue, force=force, stop=self._stop)
        except Exception:
            log.exception("Checking new releases failed")
        finally:
            self._busy.release()

    def refresh_soon(self, profile: str) -> None:
        threading.Thread(target=self.run_once, kwargs={"profiles": [profile], "force": True}, daemon=True,
                         name="dielify-releases-now").start()

    def _loop(self) -> None:
        self._stop.wait(5 * 60)
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(3 * 3600)

    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="dielify-releases").start()

    def stop(self) -> None:
        self._stop.set()
