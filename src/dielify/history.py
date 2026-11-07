"""Play history: every play (or skip) from the phone app, the PC app and Subsonic apps,
and the stats and "for you" lists built from it.

A play *counts* (play count, top lists) once you've heard half the song or 4 minutes,
the usual scrobbling rule. Shorter plays are kept as skips: they say what you don't want.
Songs are grouped by their YouTube video id when they have one, so a song first played
straight from YouTube and later from the downloaded file is one song.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .library import Library, connect


PERIODS = {"week": 7, "month": 30, "year": 365, "all": None}


def counts(played_s: int | None, duration_s: int | None) -> bool:
    if played_s is None:
        return True
    if duration_s:
        return played_s >= min(duration_s / 2, 240)
    return played_s >= 30


@dataclass
class PlayIn:
    track_id: int | None = None
    video_id: str | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration_s: int | None = None
    played_s: int | None = None
    started_at: float | None = None
    client_id: str | None = None


def record(lib: Library, play: PlayIn, device: str) -> bool:
    """Store one play. Returns False if it was a duplicate (already sent)."""
    track = lib.track(play.track_id) if play.track_id else None
    if track is None and play.video_id:
        tid = lib.video_ids().get(play.video_id)
        track = lib.track(tid) if tid else None
    title = play.title or (track["title"] if track else None)
    if not title:
        raise ValueError("A play needs a title, or a track that's in the library")
    duration = play.duration_s or (track["duration_s"] if track else None)
    counted = counts(play.played_s, duration)
    when = play.started_at or time.time()
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO plays (profile, client_id, track_id, video_id, title, artist, album, "
            "duration_s, played_s, counted, started_at, device) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (lib.profile, play.client_id, track["id"] if track else None,
             play.video_id or (track["video_id"] if track else None), title,
             play.artist or (track["artist"] if track else None),
             play.album or (track["album"] if track else None),
             duration, play.played_s, int(counted), when, device))
        new = cur.rowcount > 0
    if new and counted and track is not None:
        lib.record_play(track["id"], when)
    return new


def _since(period: str) -> float | None:
    days = PERIODS[period]
    return time.time() - days * 86400 if days else None


def stats(lib: Library, period: str = "month", limit: int = 10) -> dict:
    since = _since(period) or 0.0
    key = "COALESCE(p.video_id, 'tr' || p.track_id, p.title || '|' || COALESCE(p.artist, ''))"
    with connect() as conn:
        args = (lib.profile, since)
        where = "p.profile = ? AND p.started_at >= ? AND p.counted = 1"
        total = conn.execute(
            f"SELECT COUNT(*) n, COALESCE(SUM(COALESCE(p.played_s, p.duration_s, 0)), 0) secs, "
            f"COUNT(DISTINCT {key}) songs, COUNT(DISTINCT p.artist) artists FROM plays p WHERE {where}",
            args).fetchone()
        skips = conn.execute("SELECT COUNT(*) FROM plays p WHERE p.profile = ? AND p.started_at >= ? "
                             "AND p.counted = 0", args).fetchone()[0]
        first = conn.execute("SELECT MIN(started_at) FROM plays WHERE profile = ?", (lib.profile,)).fetchone()[0]
        songs = conn.execute(
            f"SELECT {key} k, MAX(p.track_id) track_id, MAX(p.video_id) video_id, MAX(p.title) title, "
            f"MAX(p.artist) artist, MAX(p.album) album, COUNT(*) plays, "
            f"SUM(COALESCE(p.played_s, p.duration_s, 0)) secs FROM plays p WHERE {where} "
            f"GROUP BY k ORDER BY plays DESC, secs DESC LIMIT ?", (*args, limit)).fetchall()
        artists = conn.execute(
            f"SELECT p.artist name, COUNT(*) plays, SUM(COALESCE(p.played_s, p.duration_s, 0)) secs, "
            f"MAX(p.track_id) track_id FROM plays p WHERE {where} AND p.artist IS NOT NULL "
            f"GROUP BY p.artist ORDER BY plays DESC LIMIT ?", (*args, limit)).fetchall()
        albums = conn.execute(
            f"SELECT p.album name, MAX(p.artist) artist, COUNT(*) plays, MAX(p.track_id) track_id "
            f"FROM plays p WHERE {where} AND p.album IS NOT NULL AND p.album != '' "
            f"GROUP BY p.album ORDER BY plays DESC LIMIT ?", (*args, limit)).fetchall()
        hours = conn.execute(
            f"SELECT CAST(strftime('%H', p.started_at, 'unixepoch', 'localtime') AS INTEGER) h, COUNT(*) n "
            f"FROM plays p WHERE {where} GROUP BY h", args).fetchall()
    by_hour = [0] * 24
    for r in hours:
        by_hour[r["h"]] = r["n"]
    return {
        "period": period, "since": since or None, "history_starts": first,
        "plays": total["n"], "minutes": round(total["secs"] / 60), "songs": total["songs"],
        "artists": total["artists"], "skips": skips, "by_hour": by_hour,
        "top_songs": [dict(r) for r in songs], "top_artists": [dict(r) for r in artists],
        "top_albums": [dict(r) for r in albums],
    }


def on_repeat(lib: Library, days: int = 14, limit: int = 25) -> list[int]:
    """Library tracks you've played most lately."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.track_id, COUNT(*) n FROM plays p JOIN tracks t ON t.id = p.track_id "
            "WHERE p.profile = ? AND p.started_at >= ? AND p.counted = 1 "
            "GROUP BY p.track_id HAVING n >= 2 ORDER BY n DESC LIMIT ?",
            (lib.profile, time.time() - days * 86400, limit)).fetchall()
    return [r["track_id"] for r in rows]


def forgotten(lib: Library, days: int = 60, limit: int = 25) -> list[int]:
    """Songs you played a lot, but not for a while (uses the play counts from before
    this history existed too)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM tracks WHERE profile = ? AND play_count >= 3 AND last_played IS NOT NULL "
            "AND last_played < ? ORDER BY play_count DESC, last_played LIMIT ?",
            (lib.profile, time.time() - days * 86400, limit)).fetchall()
    return [r["id"] for r in rows]


def seeds(lib: Library, days: int = 30, limit: int = 4) -> list[str]:
    """Video ids of your most-played songs lately (to find more like them)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.video_id, COUNT(*) n FROM plays p WHERE p.profile = ? AND p.started_at >= ? "
            "AND p.counted = 1 AND p.video_id IS NOT NULL GROUP BY p.video_id ORDER BY n DESC LIMIT ?",
            (lib.profile, time.time() - days * 86400, limit)).fetchall()
        ids = [r["video_id"] for r in rows]
        if len(ids) < limit:  # not much history yet: fall back to all-time play counts
            more = conn.execute(
                "SELECT video_id FROM tracks WHERE profile = ? AND video_id IS NOT NULL AND play_count > 0 "
                "ORDER BY play_count DESC, last_played DESC LIMIT ?", (lib.profile, limit * 2)).fetchall()
            ids += [r["video_id"] for r in more if r["video_id"] not in ids]
    return ids[:limit]
