"""Dielify-made mixes: genre, decade and vibe playlists built from your library, your
plays and a few new finds, rebuilt weekly.

Genres come from the artists' MusicBrainz tags (tags.py). Mixes are stored as read-only
playlists (kind='mix', one per mix_key), so every app shows them like playlists and
Subsonic apps see them too. Each rebuild keeps a mix's id, so open screens keep working.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from . import library, tags
from .library import connect
from .yt_adapter import YTItem

log = logging.getLogger(__name__)

SIZE = 50
NEW_FINDS = 10
MIN_GENRE_TRACKS = 15
MIN_OTHER_TRACKS = 20
MAX_GENRES = 6
MAX_DECADES = 3
REBUILD_EVERY_S = 7 * 86400

# Vibes are guessed from genre words (MusicBrainz rarely tags moods).
VIBES = {
    "Chill": ["ambient", "chill", "lo-fi", "downtempo", "trip hop", "acoustic", "folk", "dream pop",
              "bedroom pop", "neo soul", "jazz", "soft rock", "chamber pop", "slowcore", "bossa nova"],
    "High energy": ["hard rock", "metal", "punk", "drum and bass", "electro house", "edm", "house", "techno",
                    "trap", "gangsta rap", "dubstep", "big beat", "hardcore", "grime", "garage rock", "drill"],
    "Feel good": ["funk", "disco", "dance-pop", "pop rock", "indie pop", "motown", "reggae", "synth-pop",
                  "ska", "soul", "power pop", "pop rap", "surf"],
}


@dataclass
class Mix:
    key: str
    name: str
    description: str
    track_ids: list[int]
    new_finds: list[YTItem] = field(default_factory=list)


def _tracks(profile: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT t.id, t.video_id, t.title, t.artist, t.year, t.duration_s, li.play_count, al.name AS album, "
            "ar.name AS album_artist FROM library_items li JOIN tracks t ON t.id = li.track_id "
            "JOIN albums al ON al.id = t.album_id "
            "JOIN artists ar ON ar.id = t.artist_id WHERE li.profile = ? AND t.video_id IS NOT NULL", (profile,)).fetchall()
    from .ratings import Ratings
    r = Ratings(profile)
    out = []
    for row in rows:
        t = dict(row)
        t["factor"] = r.factor(t["video_id"], t["artist"], t["id"])
        if t["factor"] > 0:  # banned songs/artists never go in a mix
            out.append(t)
    return out


def _pick(tracks: list[dict], seed: str, size: int = SIZE) -> list[dict]:
    """A weighted sample: songs you play more are more likely, but it changes weekly."""
    rnd = random.Random(seed)
    keyed = [(rnd.random() ** (1.0 / ((1 + (t["play_count"] or 0)) * t.get("factor", 1.0))), t) for t in tracks]
    return [t for _, t in sorted(keyed, key=lambda k: -k[0])[:size]]


def plan(profile: str, week: str) -> list[tuple[str, str, str, list[dict]]]:
    """(key, name, description, tracks) for every mix this library supports."""
    tracks = _tracks(profile)
    names = {n for t in tracks for n in [t["album_artist"], *tags.split_artists(t["artist"])]}
    genres_of_artist = tags.tags_for(list(names))
    by_genre: dict[str, list[dict]] = {}
    for t in tracks:
        g: list[str] = []
        for n in [t["album_artist"], *tags.split_artists(t["artist"])]:
            for tag in genres_of_artist.get(n, []):
                if tag not in g:
                    g.append(tag)
        t["genres"] = g
        for tag in g:
            by_genre.setdefault(tag, []).append(t)

    out = []
    chosen: list[set[int]] = []
    for genre, members in sorted(by_genre.items(), key=lambda kv: -len(kv[1])):
        if len(members) < MIN_GENRE_TRACKS or len(chosen) >= MAX_GENRES:
            break
        ids = {t["id"] for t in members}
        if any(len(ids & c) > 0.6 * min(len(ids), len(c)) for c in chosen):
            continue  # mostly the same songs as a mix we already have
        chosen.append(ids)
        title = genre.title().replace("Edm", "EDM").replace("Rnb", "R&B")
        out.append((f"genre:{genre}", f"{title} mix", f"{title} from your library",
                    _pick(members, f"{week}:{genre}")))

    decades: dict[int, list[dict]] = {}
    for t in tracks:
        if t["year"] and 1940 <= t["year"] <= 2100:
            decades.setdefault(t["year"] // 10 * 10, []).append(t)
    top = sorted((d for d in decades if len(decades[d]) >= MIN_OTHER_TRACKS), key=lambda d: -len(decades[d]))
    for d in sorted(top[:MAX_DECADES]):
        label = f"{str(d)[2:]}s" if d < 2000 else f"{d}s"
        out.append((f"decade:{d}", f"Your {label}", f"Songs from the {label} in your library",
                    _pick(decades[d], f"{week}:{d}")))

    for vibe, words in VIBES.items():
        members = [t for t in tracks if any(w in g for g in t["genres"] for w in words)]
        if len(members) >= MIN_OTHER_TRACKS:
            out.append((f"vibe:{vibe.lower()}", vibe, f"{vibe} picks from your library (guessed from genres)",
                        _pick(members, f"{week}:{vibe}")))
    return out


def _week() -> str:
    """This week, e.g. 2026-W45: mixes change once a week, not on every rebuild."""
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


def _new_finds(similar: Callable[[str], list[YTItem]] | None, seeds: list[dict], have: set[str]) -> list[YTItem]:
    if similar is None:
        return []
    found, seen = [], set(have)
    for t in seeds:
        try:
            items = similar(t["video_id"])
        except Exception as e:  # offline / signed out: the mix is still fine without
            log.info("No new finds for a mix: %s", e)
            return found
        for it in items:
            if it.type in ("song", "video") and it.id not in seen:
                seen.add(it.id)
                found.append(it)
                if len(found) >= NEW_FINDS:
                    return found
    return found


def rebuild(profile: str, similar: Callable[[str], list[YTItem]] | None = None) -> int:
    """Build this week's mixes for one profile. Returns how many there are."""
    week = _week()
    with connect() as conn:
        have = {r[0] for r in conn.execute("SELECT t.video_id FROM library_items li JOIN tracks t ON t.id = li.track_id "
                                           "WHERE li.profile = ? AND t.video_id IS NOT NULL",
                                           (profile,))}
    mixes = plan(profile, week)
    now = time.time()
    keys = []
    for key, name, description, picked in mixes:
        seeds = sorted(picked, key=lambda t: -(t["play_count"] or 0))[:2]
        finds = _new_finds(similar, seeds, have) if key.startswith("genre:") else []
        if finds:
            from .ratings import DOWN, Ratings
            r = Ratings(profile)
            finds = [f for f in r.arrange(finds) if r.value(f.id, f.artists) != DOWN]
        if finds:
            description += f", plus {len(finds)} new finds"
        entries = [YTItem("song", t["video_id"], t["title"], tags.split_artists(t["artist"])[:3] or [t["artist"]],
                          t["album"], duration_s=t["duration_s"]) for t in picked]
        for n, f in enumerate(finds):
            entries.insert(min(len(entries), 4 + n * 5), f)  # sprinkled in, not all at the end
        keys.append(key)
        with connect() as conn:
            row = conn.execute("SELECT id FROM playlists WHERE profile = ? AND kind = 'mix' AND mix_key = ?",
                               (profile, key)).fetchone()
            if row:
                pid = row["id"]
                conn.execute("UPDATE playlists SET name = ?, description = ?, updated_at = ?, synced_at = ? WHERE id = ?",
                             (name, description, now, now, pid))
                conn.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (pid,))
            else:
                pid = conn.execute(
                    "INSERT INTO playlists (profile, name, kind, mix_key, description, read_only, created_at, "
                    "updated_at, synced_at) VALUES (?,?,?,?,?,1,?,?,?)",
                    (profile, name, "mix", key, description, now, now, now)).lastrowid
            for pos, it in enumerate(entries, start=1):
                conn.execute(
                    "INSERT INTO playlist_items (playlist_id, position, video_id, title, artist, album, duration_s, "
                    "thumbnail, added_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (pid, pos, it.id, it.title, ", ".join(it.artists) or None, it.album, it.duration_s,
                     it.thumbnail, now))
    with connect() as conn:
        stale = conn.execute("SELECT id, mix_key FROM playlists WHERE profile = ? AND kind = 'mix'", (profile,)).fetchall()
        for r in stale:
            if r["mix_key"] not in keys:
                conn.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (r["id"],))
                conn.execute("DELETE FROM playlists WHERE id = ?", (r["id"],))
    log.info("Built %d mixes for %s", len(keys), profile)
    return len(keys)


def last_built(profile: str) -> float | None:
    with connect() as conn:
        return conn.execute("SELECT MAX(updated_at) FROM playlists WHERE profile = ? AND kind = 'mix'",
                            (profile,)).fetchone()[0]


class MixMaker:
    """Background: look up genres, then (re)build mixes weekly."""

    def __init__(self, call: Callable[..., object] | None = None):
        self.call = call
        self.mb = tags.MusicBrainz()
        self._stop = threading.Event()
        self._busy = threading.Lock()

    def _similar(self, profile: str):
        if self.call is None:
            return None
        from . import kids
        if kids.is_child(profile):  # a kids account's new finds pass the parent's controls
            f = lambda: kids.KidFilter(profile, lambda fn, *a: self.call(profile, fn, *a), lookups=6)  # noqa: E731
            return lambda vid: f().items(self.call(profile, "similar", vid, 25))[:15]
        return lambda vid: self.call(profile, "similar", vid, 15)

    def run_once(self, force: bool = False) -> None:
        from . import settings as settings_mod
        if not self._busy.acquire(blocking=False):
            return
        try:
            if not settings_mod.load().offline:
                tags.tag_some(self.mb, self._stop)
            st = tags.status()
            ready = st["artists"] and st["looked_up"] >= 0.8 * st["artists"]
            profiles = library.profiles()
            for p in profiles:
                built = last_built(p)
                if force or (ready and (built is None or time.time() - built > REBUILD_EVERY_S)):
                    rebuild(p, None if settings_mod.load().offline else self._similar(p))
        except Exception:
            log.exception("Making mixes failed")
        finally:
            self._busy.release()

    def refresh_soon(self) -> None:
        threading.Thread(target=self.run_once, kwargs={"force": True}, daemon=True, name="dielify-mixes-now").start()

    def _loop(self) -> None:
        self._stop.wait(120)
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(30 * 60)

    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="dielify-mixes").start()

    def stop(self) -> None:
        self._stop.set()
