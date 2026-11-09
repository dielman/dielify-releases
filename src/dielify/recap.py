"""Year in review (and any month): a recap of one person's listening.

Built from the play history (history.py; it starts at 0.8.0). A month's recap is there
from the month's first play; a year's ("December edition") from 1 December of that year,
or straight away for years that are over. Only the person themselves sees theirs (a
child's recap is hers only; the parent's stats view is separate and needs her controls).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from . import tags
from .library import Library, connect

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
KEY = "COALESCE(p.video_id, 'tr' || p.track_id, p.title || '|' || COALESCE(p.artist, ''))"


def _range(period: str) -> tuple[float, float, str]:
    """'2026' or '2026-11' -> (start, end, title), local time."""
    try:
        if len(period) == 4:
            y = int(period)
            start, end = datetime(y, 1, 1), datetime(y + 1, 1, 1)
            title = f"Your {y}"
        else:
            y, m = int(period[:4]), int(period[5:7])
            start = datetime(y, m, 1)
            end = datetime(y + (m == 12), m % 12 + 1, 1)
            title = f"{MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        raise ValueError("period is a year (2026) or a month (2026-11)") from None
    return start.timestamp(), end.timestamp(), title


def periods(lib: Library, today: date | None = None) -> list[dict]:
    """Recaps there are something for, newest first: years (from 1 December, or once over),
    then months."""
    today = today or date.today()
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT strftime('%Y-%m', started_at, 'unixepoch', 'localtime') m FROM plays "
            "WHERE profile = ? AND counted = 1 ORDER BY m DESC", (lib.profile,)).fetchall()
    months = [r["m"] for r in rows if r["m"]]
    years = sorted({m[:4] for m in months}, reverse=True)
    out = [{"period": y, "title": f"Your {y}", "kind": "year"} for y in years
           if int(y) < today.year or today.month == 12]
    out += [{"period": m, "title": f"{MONTHS[int(m[5:]) - 1]} {m[:4]}", "kind": "month"} for m in months]
    return out


def build(lib: Library, period: str) -> dict:
    start, end, title = _range(period)
    args = (lib.profile, start, end)
    where = "p.profile = ? AND p.started_at >= ? AND p.started_at < ? AND p.counted = 1"
    secs = "COALESCE(p.played_s, p.duration_s, 0)"
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) n, COALESCE(SUM({secs}), 0) s, COUNT(DISTINCT {KEY}) songs, "
                             f"COUNT(DISTINCT p.artist) artists FROM plays p WHERE {where}", args).fetchone()
        songs = conn.execute(
            f"SELECT {KEY} k, MAX(p.track_id) track_id, MAX(p.video_id) video_id, MAX(p.title) title, "
            f"MAX(p.artist) artist, COUNT(*) plays, SUM({secs}) secs FROM plays p WHERE {where} "
            f"GROUP BY k ORDER BY plays DESC, secs DESC LIMIT 10", args).fetchall()
        artists = conn.execute(
            f"SELECT p.artist name, COUNT(*) plays, SUM({secs}) secs, MAX(p.track_id) track_id FROM plays p "
            f"WHERE {where} AND p.artist IS NOT NULL GROUP BY p.artist ORDER BY plays DESC LIMIT 10", args).fetchall()
        albums = conn.execute(
            f"SELECT p.album name, MAX(p.artist) artist, COUNT(*) plays, MAX(p.track_id) track_id FROM plays p "
            f"WHERE {where} AND p.album IS NOT NULL AND p.album != '' GROUP BY p.album ORDER BY plays DESC LIMIT 5",
            args).fetchall()
        first = conn.execute(f"SELECT p.title, p.artist, p.track_id, p.started_at FROM plays p WHERE {where} "
                             f"ORDER BY p.started_at LIMIT 1", args).fetchone()
        days = [r["d"] for r in conn.execute(
            f"SELECT DISTINCT date(p.started_at, 'unixepoch', 'localtime') d FROM plays p WHERE {where} ORDER BY d",
            args)]
        busiest = conn.execute(
            f"SELECT date(p.started_at, 'unixepoch', 'localtime') d, SUM({secs}) s FROM plays p WHERE {where} "
            f"GROUP BY d ORDER BY s DESC LIMIT 1", args).fetchone()
        hour = conn.execute(
            f"SELECT CAST(strftime('%H', p.started_at, 'unixepoch', 'localtime') AS INTEGER) h, COUNT(*) n "
            f"FROM plays p WHERE {where} GROUP BY h ORDER BY n DESC LIMIT 1", args).fetchone()
        # artists heard for the first time ever in this period
        new_artists = conn.execute(
            f"SELECT p.artist name, COUNT(*) plays, MAX(p.track_id) track_id FROM plays p WHERE {where} "
            f"AND p.artist IS NOT NULL AND NOT EXISTS (SELECT 1 FROM plays q WHERE q.profile = p.profile "
            f"AND q.artist = p.artist AND q.counted = 1 AND q.started_at < ?) "
            f"GROUP BY p.artist ORDER BY plays DESC", (*args, start)).fetchall()
        all_artist_plays = conn.execute(
            f"SELECT p.artist name, COUNT(*) n FROM plays p WHERE {where} AND p.artist IS NOT NULL GROUP BY p.artist",
            args).fetchall()
    # genres: each play counts for its artist's genres (MusicBrainz tags, where looked up)
    plays_of = {}
    for r in all_artist_plays:
        for n in tags.split_artists(r["name"]):
            plays_of[n] = plays_of.get(n, 0) + r["n"]
    genre_plays: dict[str, int] = {}
    for name, gs in tags.tags_for(list(plays_of)).items():
        for g in gs[:2]:
            genre_plays[g] = genre_plays.get(g, 0) + plays_of[name]
    genres = [{"name": g.title(), "plays": n} for g, n in sorted(genre_plays.items(), key=lambda kv: -kv[1])[:5]]
    streak = best = 0
    prev = None
    for d in days:
        cur = date.fromisoformat(d)
        streak = streak + 1 if prev is not None and cur - prev == timedelta(days=1) else 1
        best = max(best, streak)
        prev = cur
    return {
        "period": period, "title": title, "since": start, "until": end, "generated_at": time.time(),
        "minutes": round(total["s"] / 60), "plays": total["n"], "songs": total["songs"], "artists": total["artists"],
        "days_listened": len(days), "longest_streak_days": best,
        "busiest_day": {"date": busiest["d"], "minutes": round(busiest["s"] / 60)} if busiest else None,
        "favourite_hour": hour["h"] if hour else None,
        "top_songs": [dict(r) for r in songs], "top_artists": [dict(r) for r in artists],
        "top_albums": [dict(r) for r in albums], "top_genres": genres,
        "first_song": dict(first) if first else None,
        "new_artists": len(new_artists), "top_new_artists": [dict(r) for r in new_artists[:5]],
    }
