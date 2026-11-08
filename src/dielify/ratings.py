"""Thumbs up / down and bans, per profile, for songs and artists.

- Thumbs up: more of it (mixes pick it more often).
- Thumbs down: still allowed, but it goes to the back of discovery lists and mixes rarely
  pick it.
- Ban ("mega dislike", hold the thumb down): never again. Left out of discovery and
  mixes, and the players skip it in any list.

A song is keyed by its YouTube video id (or "tr-<id>" for a library file without one);
an artist by `artist_key(name)`. The apps use the same key rule (app.js, Ratings.kt).
"""

from __future__ import annotations

import re
import time
import unicodedata

from .library import connect
from .yt_adapter import YTItem

UP, DOWN, BAN = 1, -1, -2
VALUES = (UP, DOWN, BAN)
FACTOR = {UP: 3.0, DOWN: 0.2, BAN: 0.0}  # how much more/less likely in mixes

_SPLIT = re.compile(r",|;| & | x | feat\.? | ft\.? | featuring | with ", re.I)


def artist_key(name: str) -> str:
    """Same in the apps: NFKC, lower case, '&' -> 'and', single spaces."""
    text = unicodedata.normalize("NFKC", name or "").lower().replace("&", "and")
    return re.sub(r"\s+", " ", text).strip()


def song_key(video_id: str | None = None, track_id: int | None = None) -> str | None:
    return video_id or (f"tr-{track_id}" if track_id else None)


def split_artists(text: str | None) -> list[str]:
    return [p.strip() for p in _SPLIT.split(text or "") if p.strip()]


def set_rating(profile: str, kind: str, key: str, name: str, value: int) -> None:
    """value 0 clears it."""
    with connect() as conn:
        if value == 0:
            conn.execute("DELETE FROM ratings WHERE profile = ? AND kind = ? AND key = ?", (profile, kind, key))
        else:
            conn.execute("INSERT OR REPLACE INTO ratings (profile, kind, key, name, value, updated_at) "
                         "VALUES (?,?,?,?,?,?)", (profile, kind, key, name[:300], value, time.time()))


def listing(profile: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT kind, key, name, value, updated_at FROM ratings WHERE profile = ? "
                            "ORDER BY updated_at DESC", (profile,)).fetchall()
    return [dict(r) for r in rows]


class Ratings:
    """A profile's ratings, loaded once for one list/mix build."""

    def __init__(self, profile: str):
        self.songs: dict[str, int] = {}
        self.artists: dict[str, int] = {}
        for r in listing(profile):
            (self.songs if r["kind"] == "song" else self.artists)[r["key"]] = r["value"]

    def value(self, video_id: str | None, artists: list[str] | str | None, track_id: int | None = None) -> int:
        """Ban wins over everything; otherwise the song's own rating, else its artists'."""
        names = split_artists(artists) if isinstance(artists, str) else (artists or [])
        a_vals = [self.artists.get(artist_key(n), 0) for n in names]
        s_val = self.songs.get(song_key(video_id, track_id) or "", 0)
        if s_val == BAN or BAN in a_vals:
            return BAN
        if s_val:
            return s_val
        return min(a_vals) if DOWN in a_vals else max(a_vals, default=0)

    def factor(self, video_id, artists, track_id=None) -> float:
        return FACTOR.get(self.value(video_id, artists, track_id), 1.0)

    def arrange(self, items: list[YTItem]) -> list[YTItem]:
        """For discovery lists: banned songs out, thumbed-down ones to the back. Albums,
        playlists and artists pass through (a banned artist's own page is left out too)."""
        keep, back = [], []
        for it in items:
            if it.type in ("song", "video"):
                v = self.value(it.id, it.artists)
            elif it.type == "artist":
                v = self.artists.get(artist_key(it.title), 0)
            else:
                v = 0
            if v == BAN:
                continue
            (back if v == DOWN else keep).append(it)
        return keep + back
