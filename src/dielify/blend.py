"""Blend: a weekly playlist made from two people's tastes.

Everyone in a household who turns Blend on gets one Blend with each other person who has it
on: songs you both play first, then each person's favourites in turn (50 songs, a new pick
every week). Each person's bans and left-out-of-taste songs aren't picked from their side.
A kids account can only take part once a parent allows it (her controls: blend), and a Blend
with her in it only holds songs her controls allow.

Stored as read-only playlists (kind='blend', mix_key 'blend:<a>|<b>'), one copy for each of
the two people, so every app (and Subsonic) shows it like a playlist.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import date

from . import releases
from .library import connect, person
from .playlists import household
from .ratings import BAN, Ratings
from .taste import Taste
from .yt_adapter import YTItem

log = logging.getLogger(__name__)

SIZE = 50
PER_PERSON = 40
REBUILD_EVERY_S = 7 * 86400


def wants(profile: str) -> bool:
    return bool(releases.pref(profile, "blend", False))


def allowed(profile: str) -> bool:
    """A kids account needs a parent's OK."""
    if person(profile)["role"] != "child":
        return True
    from . import kids
    return bool(getattr(kids.load(profile), "blend", False))


def active(profile: str) -> bool:
    return wants(profile) and allowed(profile)


def set_wanted(profile: str, on: bool) -> None:
    releases.set_pref(profile, "blend", bool(on))


def partners(profile: str) -> list[str]:
    """Household members with Blend on (and allowed), besides this person."""
    if not active(profile):
        return []
    return [p for p in household(profile) if p.casefold() != profile.casefold() and active(p)]


def _favourites(profile: str, limit: int = PER_PERSON) -> list[dict]:
    """A person's most-played library songs (last 90 days counted double), minus bans and
    songs they left out of their taste."""
    since = time.time() - 90 * 86400
    with connect() as conn:
        rows = conn.execute(
            "SELECT t.id, t.video_id, t.title, t.artist, t.duration_s, al.name AS album, li.play_count, "
            "(SELECT COUNT(*) FROM plays p WHERE p.profile = li.profile AND p.track_id = t.id AND p.counted = 1 "
            " AND p.started_at >= ?) AS recent "
            "FROM library_items li JOIN tracks t ON t.id = li.track_id JOIN albums al ON al.id = t.album_id "
            "WHERE li.profile = ? AND t.video_id IS NOT NULL AND (li.play_count > 0 OR li.starred_at IS NOT NULL) "
            "ORDER BY (li.play_count + 2 * recent) DESC LIMIT ?", (since, profile, limit * 3)).fetchall()
    r, taste = Ratings(profile), Taste(profile)
    out = [dict(x) for x in rows if r.value(x["video_id"], x["artist"], x["id"]) != BAN and not taste.out(x["video_id"], x["id"])]
    return out[:limit]


def _pick(a: str, b: str, week: str) -> list[dict]:
    fa, fb = _favourites(a), _favourites(b)
    ids_b = {s["video_id"] for s in fb}
    both = [s for s in fa if s["video_id"] in ids_b]
    rnd = random.Random(f"{min(a, b)}|{max(a, b)}|{week}")
    rest_a = [s for s in fa if s["video_id"] not in ids_b]
    rest_b = [s for s in fb if s["video_id"] not in {x["video_id"] for x in fa}]
    def shuffled(side: list[dict]) -> list[dict]:  # favourites first, but a different handful each week
        n = max(1, len(side))
        keyed = [(rnd.random() + 1.5 * (1 - i / n), s) for i, s in enumerate(side)]
        return [s for _, s in sorted(keyed, key=lambda k: -k[0])]
    rest_a, rest_b = shuffled(rest_a), shuffled(rest_b)
    out, seen = list(both[: SIZE // 3]), {s["video_id"] for s in both[: SIZE // 3]}
    for x, y in zip(rest_a + [None] * len(rest_b), rest_b + [None] * len(rest_a)):
        for s in (x, y):
            if s and s["video_id"] not in seen and len(out) < SIZE:
                seen.add(s["video_id"])
                out.append(s)
    return out


def _kid_safe(a: str, b: str, songs: list[dict]) -> list[dict]:
    from . import kids
    for p in (a, b):
        if person(p)["role"] == "child":
            items = [YTItem("song", s["video_id"], s["title"], [s["artist"]] if s["artist"] else []) for s in songs]
            ok = {i.id for i in kids.KidFilter(p).items(items)}
            songs = [s for s in songs if s["video_id"] in ok]
    return songs


def _key(a: str, b: str) -> str:
    x, y = sorted([a.casefold(), b.casefold()])
    return f"blend:{x}|{y}"


def _week() -> str:
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


def build(a: str, b: str) -> list[dict]:
    songs = _kid_safe(a, b, _pick(a, b, _week()))
    now = time.time()
    key = _key(a, b)
    with connect() as conn:
        for me, other in ((a, b), (b, a)):
            row = conn.execute("SELECT id FROM playlists WHERE profile = ? AND kind = 'blend' AND mix_key = ?",
                               (me, key)).fetchone()
            name = f"Blend: {me} + {other}"
            desc = f"Songs you and {other} both play, and favourites from each of you. New every week"
            if row:
                pid = row["id"]
                conn.execute("UPDATE playlists SET name = ?, description = ?, updated_at = ?, synced_at = ? WHERE id = ?",
                             (name, desc, now, now, pid))
                conn.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (pid,))
            else:
                pid = conn.execute(
                    "INSERT INTO playlists (profile, name, kind, mix_key, description, read_only, created_at, updated_at, "
                    "synced_at) VALUES (?,?,'blend',?,?,1,?,?,?)", (me, name, key, desc, now, now, now)).lastrowid
            conn.executemany(
                "INSERT INTO playlist_items (playlist_id, position, video_id, title, artist, album, duration_s, added_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [(pid, i, s["video_id"], s["title"], s["artist"], s["album"], s["duration_s"], now)
                 for i, s in enumerate(songs, start=1)])
    log.info("Blend %s: %d songs", key, len(songs))
    return songs


def rebuild_all(force: bool = False) -> int:
    """Make the Blends that should exist (and drop the ones that shouldn't any more)."""
    from .library import people
    everyone = [p["profile"] for p in people()]
    wanted = set()
    built = 0
    for a in everyone:
        for b in partners(a):
            key = _key(a, b)
            if key in wanted:
                continue
            wanted.add(key)
            with connect() as conn:
                last = conn.execute("SELECT MAX(updated_at) FROM playlists WHERE kind = 'blend' AND mix_key = ?",
                                    (key,)).fetchone()[0]
            if force or last is None or time.time() - last > REBUILD_EVERY_S:
                build(a, b)
                built += 1
    with connect() as conn:
        for r in conn.execute("SELECT id, mix_key FROM playlists WHERE kind = 'blend'").fetchall():
            if r["mix_key"] not in wanted:
                conn.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (r["id"],))
                conn.execute("DELETE FROM playlists WHERE id = ?", (r["id"],))
    return built
