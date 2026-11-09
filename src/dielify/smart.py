"""Smart playlists: rule-based lists over your library that keep themselves up to date.

Stored as playlists with kind='smart', read-only (you change the rules, not the songs) and
the rules as JSON in playlists.rules. The songs are worked out again whenever the playlist
is read and its list is older than REFRESH_S, so every app (and Subsonic apps) sees a
current list without a background job.

Rules: {"match": "all"|"any", "rules": [{"field", "op", "value"}, ...], "sort", "limit"}
  text fields  artist, album, title, genre   ops is, is_not, contains, not_contains
  numbers      plays, year, length_s         ops gt, lt, eq
  days         last_played, added            ops within (in the last N days), not_within
                                              (not in the last N days, or never)
  rating       rating                        op is: up | down | none
Songs without a YouTube video id can't be listed (playlist entries are videos). Banned songs
never show.
"""

from __future__ import annotations

import json
import random
import time
from datetime import date

from . import tags
from .library import connect
from .ratings import BAN, DOWN, UP, Ratings, artist_key

REFRESH_S = 300
TEXT = {"artist", "album", "title", "genre"}
NUMBER = {"plays", "year", "length_s"}
DAYS = {"last_played", "added"}
OPS = {**{f: {"is", "is_not", "contains", "not_contains"} for f in TEXT},
       **{f: {"gt", "lt", "eq"} for f in NUMBER},
       **{f: {"within", "not_within"} for f in DAYS},
       "rating": {"is"}}
SORTS = ("random", "most_played", "least_played", "recently_added", "recently_played", "title", "artist", "year")


def validate(rules: dict) -> dict:
    """Checked and normalised rules; ValueError says what's wrong."""
    match = rules.get("match", "all")
    if match not in ("all", "any"):
        raise ValueError("match must be all or any")
    out = []
    for r in rules.get("rules") or []:
        field, op, value = r.get("field"), r.get("op"), r.get("value")
        if field not in OPS:
            raise ValueError(f"Unknown rule: {field}")
        if op not in OPS[field]:
            raise ValueError(f"{field} can't use {op}")
        if field in TEXT:
            value = str(value or "").strip()
            if not value:
                raise ValueError(f"{field}: type something to match")
        elif field == "rating":
            if value not in ("up", "down", "none"):
                raise ValueError("rating is up, down or none")
        else:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{field} needs a number") from None
        out.append({"field": field, "op": op, "value": value})
    if not out:
        raise ValueError("Add at least one rule")
    sort = rules.get("sort", "random")
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {', '.join(SORTS)}")
    limit = int(rules.get("limit") or 100)
    if not 1 <= limit <= 1000:
        raise ValueError("limit is 1 to 1,000 songs")
    return {"match": match, "rules": out, "sort": sort, "limit": limit}


def _songs(profile: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT t.id, t.video_id, t.title, t.artist, t.year, t.duration_s, t.created_at, li.play_count, "
            "li.last_played, li.added_at, al.name AS album, ar.name AS album_artist "
            "FROM library_items li JOIN tracks t ON t.id = li.track_id JOIN albums al ON al.id = t.album_id "
            "JOIN artists ar ON ar.id = t.artist_id WHERE li.profile = ? AND t.video_id IS NOT NULL",
            (profile,)).fetchall()
    return [dict(r) for r in rows]


def _text_match(op: str, haystack: list[str], needle: str) -> bool:
    n = needle.casefold()
    hs = [h.casefold() for h in haystack if h]
    if op == "is":
        return n in hs
    if op == "is_not":
        return n not in hs
    if op == "contains":
        return any(n in h for h in hs)
    return not any(n in h for h in hs)  # not_contains


def _matches(rule: dict, s: dict, ratings: Ratings, genres: dict[str, list[str]], now: float) -> bool:
    f, op, v = rule["field"], rule["op"], rule["value"]
    if f in TEXT:
        names = [s["album_artist"], *tags.split_artists(s["artist"])]
        hay = {"artist": names, "album": [s["album"]], "title": [s["title"]],
               "genre": [g for n in names for g in genres.get(n, [])]}[f]
        return _text_match(op, hay, v)
    if f == "rating":
        r = ratings.value(s["video_id"], s["artist"], s["id"])
        return {"up": r == UP, "down": r == DOWN, "none": r == 0}[v]
    if f in NUMBER:
        x = {"plays": s["play_count"] or 0, "year": s["year"], "length_s": s["duration_s"]}[f]
        if x is None:
            return False
        return x > v if op == "gt" else x < v if op == "lt" else x == v
    when = s["last_played"] if f == "last_played" else s["added_at"]
    recent = when is not None and when >= now - v * 86400
    return recent if op == "within" else not recent


def evaluate(profile: str, rules: dict, now: float | None = None) -> list[dict]:
    """The songs these rules pick from the person's library, sorted and capped."""
    now = now or time.time()
    songs = _songs(profile)
    ratings = Ratings(profile)
    genres = {}
    if any(r["field"] == "genre" for r in rules["rules"]):
        names = {n for s in songs for n in [s["album_artist"], *tags.split_artists(s["artist"])]}
        genres = tags.tags_for(list(names))
    test = all if rules["match"] == "all" else any
    picked = [s for s in songs
              if ratings.value(s["video_id"], s["artist"], s["id"]) != BAN
              and test(_matches(r, s, ratings, genres, now) for r in rules["rules"])]
    sort = rules["sort"]
    if sort == "random":  # the same order all day, a new one tomorrow
        rnd = random.Random(f"{profile}:{date.today()}")
        rnd.shuffle(picked)
    else:
        key = {"most_played": lambda s: -(s["play_count"] or 0),
               "least_played": lambda s: s["play_count"] or 0,
               "recently_added": lambda s: -(s["added_at"] or 0),
               "recently_played": lambda s: -(s["last_played"] or 0),
               "title": lambda s: (s["title"] or "").casefold(),
               "artist": lambda s: (artist_key(s["album_artist"] or ""), s["year"] or 0, (s["title"] or "").casefold()),
               "year": lambda s: (s["year"] or 0)}[sort]
        picked.sort(key=key)
    return picked[:rules["limit"]]


def describe(rules: dict) -> str:
    """'Genre contains rock, plays more than 5' -- for the playlist's description."""
    words = {"is": "is", "is_not": "is not", "contains": "contains", "not_contains": "doesn't contain",
             "gt": "more than", "lt": "less than", "eq": "exactly"}
    names = {"artist": "Artist", "album": "Album", "title": "Title", "genre": "Genre", "plays": "Plays",
             "year": "Year", "length_s": "Length (s)", "last_played": "Played", "added": "Added", "rating": "Rating"}
    parts = []
    for r in rules["rules"]:
        f, op, v = r["field"], r["op"], r["value"]
        if f in DAYS:
            n = int(v)
            parts.append(f"{names[f]} {'in' if op == 'within' else 'not in'} the last {n} day{'s' if n != 1 else ''}")
        elif f == "rating":
            parts.append({"up": "Thumbs up", "down": "Thumbs down", "none": "Not rated"}[v])
        else:
            vv = int(v) if isinstance(v, float) and v.is_integer() else v
            parts.append(f"{names[f]} {words[op]} {vv}")
    return (" and " if rules["match"] == "all" else " or ").join(parts)


def _write(conn, playlist_id: int, songs: list[dict], now: float) -> None:
    conn.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (playlist_id,))
    conn.executemany(
        "INSERT INTO playlist_items (playlist_id, position, video_id, title, artist, album, duration_s, added_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [(playlist_id, pos, s["video_id"], s["title"], s["artist"], s["album"], s["duration_s"], now)
         for pos, s in enumerate(songs, start=1)])
    conn.execute("UPDATE playlists SET synced_at = ? WHERE id = ?", (now, playlist_id))


def create(profile: str, name: str, rules: dict) -> int:
    rules = validate(rules)
    now = time.time()
    songs = evaluate(profile, rules, now)
    with connect() as conn:
        pid = conn.execute(
            "INSERT INTO playlists (profile, name, kind, description, rules, read_only, created_at, updated_at) "
            "VALUES (?,?,'smart',?,?,1,?,?)", (profile, name, describe(rules), json.dumps(rules), now, now)).lastrowid
        _write(conn, pid, songs, now)
    return pid


def update(profile: str, playlist_id: int, name: str, rules: dict) -> None:
    rules = validate(rules)
    now = time.time()
    songs = evaluate(profile, rules, now)
    with connect() as conn:
        conn.execute("UPDATE playlists SET name = ?, description = ?, rules = ?, updated_at = ? "
                     "WHERE id = ? AND profile = ? AND kind = 'smart'",
                     (name, describe(rules), json.dumps(rules), now, playlist_id, profile))
        _write(conn, playlist_id, songs, now)


def refresh_stale(profile: str, playlist_id: int | None = None, force: bool = False) -> None:
    """Work out again the smart playlists whose list is older than REFRESH_S."""
    now = time.time()
    with connect() as conn:
        q = "SELECT id, rules, synced_at FROM playlists WHERE profile = ? AND kind = 'smart'"
        args: list = [profile]
        if playlist_id is not None:
            q += " AND id = ?"
            args.append(playlist_id)
        rows = conn.execute(q, args).fetchall()
    for r in rows:
        if force or not r["synced_at"] or now - r["synced_at"] > REFRESH_S:
            songs = evaluate(profile, json.loads(r["rules"]), now)
            with connect() as conn:
                _write(conn, r["id"], songs, now)


def rules_of(profile: str, playlist_id: int) -> dict | None:
    with connect() as conn:
        r = conn.execute("SELECT rules FROM playlists WHERE id = ? AND profile = ? AND kind = 'smart'",
                         (playlist_id, profile)).fetchone()
    return json.loads(r["rules"]) if r and r["rules"] else None
