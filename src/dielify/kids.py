"""Kids accounts (0.9.3): the parent's controls, and the filter every song a child gets
goes through (search, radio, discovery play, Household, downloads, instant play).

Explicit songs: YouTube marks them ("E" badge) in search, album and playlist results, and
those marks are remembered here (table yt_flags). Radio results carry no mark, so a song
with no mark yet is looked up once (a YouTube search for it) and the answer remembered.
Until a song has been checked, a child doesn't get it. Lyrics: songs whose stored lyrics
(or titles) contain words on the list are blocked too, when that control is on.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .library import connect
from .ratings import artist_key

log = logging.getLogger(__name__)

Call = Callable[..., object]  # call("search_items", q, "song", 5) -> list[YTItem]


# --- the parent's controls ------------------------------------------------------------

@dataclass
class Controls:
    explicit: str = "block"            # block | allow
    clean_versions: bool = True        # when blocked: offer the clean version instead, if YouTube has one
    lyrics_check: bool = True          # also block songs whose lyrics / title use words on the list
    extra_words: list[str] = field(default_factory=list)
    downloads: str = "auto"            # auto | approve (new downloads wait for a parent's OK)
    daily_limit: int = 50              # new downloads per day (0 = none)
    youtube_search: bool = True        # off: only the household's songs and the parent's picks
    discovery_play: bool = True
    blocked_artists: list[str] = field(default_factory=list)
    blocked_songs: list[dict] = field(default_factory=list)   # [{"id": videoId, "title": ...}]
    quiet_hours: bool = False
    quiet_from: str = "21:00"
    quiet_to: str = "07:00"
    parent_sees_stats: bool = False
    blend: bool = False                # may make a Blend with someone in the household (0.9.8)
    jam: bool = True                   # may join a Jam (songs in it are filtered for her)
    picks: list[dict] = field(default_factory=list)  # the parent's picks: YTItem dicts (albums, artists, playlists, songs)

    @classmethod
    def from_dict(cls, d: dict) -> "Controls":
        known = {f for f in cls.__dataclass_fields__}
        c = cls(**{k: v for k, v in (d or {}).items() if k in known})
        c.validate()
        return c

    def validate(self) -> None:
        if self.explicit not in ("block", "allow"):
            raise ValueError("explicit: block or allow")
        if self.downloads not in ("auto", "approve"):
            raise ValueError("downloads: auto or approve")
        if not 0 <= int(self.daily_limit) <= 1000:
            raise ValueError("daily_limit: 0 to 1000")
        for t in (self.quiet_from, self.quiet_to):
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t or ""):
                raise ValueError("Times look like 21:00")
        self.extra_words = [w.strip().lower() for w in self.extra_words if w.strip()][:200]
        self.blocked_artists = [a.strip() for a in self.blocked_artists if a.strip()][:500]
        self.picks = self.picks[:100]


def load(profile: str) -> Controls:
    with connect() as conn:
        row = conn.execute("SELECT body FROM kid_controls WHERE profile = ?", (profile,)).fetchone()
    return Controls.from_dict(json.loads(row["body"])) if row else Controls()


def save(profile: str, c: Controls) -> Controls:
    c.validate()
    with connect() as conn:
        conn.execute("INSERT INTO kid_controls (profile, body, updated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT(profile) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
                     (profile, json.dumps(asdict(c)), time.time()))
    return c


def quiet_message(c: Controls, now: datetime | None = None) -> str | None:
    """"Music is off until 07:00" during the quiet hours, else None."""
    if not c.quiet_hours:
        return None
    now = now or datetime.now()
    start = now.replace(hour=int(c.quiet_from[:2]), minute=int(c.quiet_from[3:]), second=0, microsecond=0)
    end = now.replace(hour=int(c.quiet_to[:2]), minute=int(c.quiet_to[3:]), second=0, microsecond=0)
    if start <= end:
        quiet = start <= now < end
    else:  # over midnight, e.g. 21:00 -> 07:00
        quiet = now >= start or now < end
    return f"Music is off until {c.quiet_to} (a parent set quiet hours)" if quiet else None


def downloads_today(profile: str) -> int:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM downloads WHERE profile = ? AND created_at >= ? "
                            "AND attempts + (status = 'queued') + (status = 'approval') > 0",
                            (profile, midnight)).fetchone()[0]


# --- words ------------------------------------------------------------------------------

# Strong language and slurs. Stems match longer forms too ("fuck" -> "fucking", "motherfucker").
# A parent can add more words in the controls.
_STEMS = ("fuck", "shit", "cunt", "bitch", "nigg", "fag", "whore", "slut", "pussy", "dick",
          "cock", "wank", "twat", "bollock", "bastard", "retard", "kike", "spic", "chink", "dyke",
          "tranny", "coon", "motherf", "asshole", "arsehole", "jizz", "cum", "porn")
_WORDS = ("ass", "arse", "hoe", "hoes", "tits", "titties", "piss", "prick", "skank", "thot",
          "nutsack", "blowjob", "dildo", "clit")


# Ordinary words that start with a listed stem.
_INNOCENT_PREFIXES = ("dickens", "dickinson", "cocktail", "cockpit", "cockatoo", "cockroach", "cocky",
                      "cumulat", "cumbersome", "cumin", "cumbria", "spice", "spici", "spicy", "spick",
                      "coonhound", "shiitake", "shitake", "fagin")


def bad_words(text: str | None, extra=()) -> bool:
    """Whether `text` uses a word on the list (whole words; stems also match longer forms)."""
    if not text:
        return False
    extra = {w.lower() for w in extra}
    for word in re.findall(r"[a-z0-9']+", text.lower()):
        w = word.strip("'")
        if w in _WORDS or w in extra:
            return True
        if (w.startswith(_STEMS) or (w.startswith("mother") and "fuck" in w)) and not w.startswith(_INNOCENT_PREFIXES):
            return True
    return False


def lyrics_bad(video_id: str | None, extra: list[str] = ()) -> bool:
    if not video_id:
        return False
    from .lyrics import cached
    known, body = cached(video_id)
    return bool(known and body and bad_words(body.get("text"), extra))


# --- explicit marks -----------------------------------------------------------------------

def remember(items) -> None:
    """Keep YouTube's explicit marks from any results seen (so radio songs can be checked)."""
    rows = [(i.id, int(i.explicit), time.time()) for i in items
            if getattr(i, "explicit", None) is not None and i.type in ("song", "video")]
    if rows:
        with connect() as conn:
            conn.executemany("INSERT INTO yt_flags (video_id, explicit, checked_at) VALUES (?, ?, ?) "
                             "ON CONFLICT(video_id) DO UPDATE SET explicit = excluded.explicit, "
                             "checked_at = excluded.checked_at", rows)


_MISSING = object()

# Songs a child met (radio, Discover) that had no explicit mark: the background check does
# these first, so they show next time. video id -> (title, artists, sign-in profile)
_pending: dict[str, tuple[str, list[str], str]] = {}
_pending_lock = threading.Lock()


def check_soon(video_id: str, title: str, artists: list[str], signin: str) -> None:
    with _pending_lock:
        if video_id not in _pending and len(_pending) < 5000:
            _pending[video_id] = (title, list(artists), signin)


def flags(video_ids) -> dict:
    """video id -> True / False (YouTube's mark), None (looked up, YouTube didn't say).
    Ids never checked are left out."""
    ids = [v for v in dict.fromkeys(video_ids) if v]
    out = {}
    with connect() as conn:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in conn.execute(f"SELECT video_id, explicit FROM yt_flags WHERE video_id IN "
                                  f"({','.join('?' * len(chunk))})", chunk):
                out[r[0]] = None if r[1] is None else bool(r[1])
    return out


def _norm(text: str | None) -> str:
    text = re.sub(r"\s*[\(\[].*?[\)\]]", "", (text or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def look_up(call: Call, video_id: str, title: str, artists: list[str], raise_errors: bool = False) -> bool | None:
    """Ask YouTube (a song search) whether this song is explicit, and remember it.
    Returns True/False, or None when YouTube had no answer."""
    try:
        found = call("search_items", f"{' '.join(artists[:1])} {title}".strip(), "song", 6) or []
    except Exception as e:  # noqa: BLE001 - offline, signed out: try again another time
        if raise_errors:
            raise
        log.info("Explicit check for %s failed: %s", video_id, e)
        return None
    remember(found)
    match = next((f for f in found if f.id == video_id), None)
    if match is None:
        a = _norm(artists[0]) if artists else ""
        match = next((f for f in found if _norm(f.title) == _norm(title)
                      and (not a or any(_norm(x) == a for x in f.artists))), None)
    flag = None if match is None or match.explicit is None else bool(match.explicit)
    with connect() as conn:
        conn.execute("INSERT INTO yt_flags (video_id, explicit, checked_at) VALUES (?, ?, ?) "
                     "ON CONFLICT(video_id) DO UPDATE SET explicit = excluded.explicit, checked_at = excluded.checked_at",
                     (video_id, None if flag is None else int(flag), time.time()))
    return flag


def clean_version(call: Call, title: str, artists: list[str]):
    """The clean (non-explicit) version of a song, if YouTube has one."""
    try:
        found = call("search_items", f"{' '.join(artists[:1])} {title} clean".strip(), "song", 8) or []
    except Exception:  # noqa: BLE001
        return None
    remember(found)
    a = _norm(artists[0]) if artists else ""
    return next((f for f in found if f.explicit is False and _norm(f.title) == _norm(title)
                 and (not a or any(_norm(x) == a for x in f.artists))), None)


# --- the filter ---------------------------------------------------------------------------

class KidFilter:
    """What one child may get. `call` (optional) lets it ask YouTube about songs with no
    explicit mark yet; `lookups` caps how many it asks about per request (each is a search)."""

    def __init__(self, profile: str, call: Call | None = None, lookups: int = 0):
        self.profile = profile
        self.c = load(profile)
        self.call, self.lookups = call, lookups
        self._blocked_artists = {artist_key(a) for a in self.c.blocked_artists}
        self._blocked_songs = {s.get("id") for s in self.c.blocked_songs}

    def why_not(self, video_id: str | None, title: str, artists: list[str], explicit: bool | None = None,
                flag=_MISSING) -> str | None:
        """None if allowed, else the reason."""
        if video_id and video_id in self._blocked_songs:
            return "blocked by a parent"
        if any(artist_key(a) in self._blocked_artists for a in artists):
            return "artist blocked by a parent"
        if self.c.lyrics_check and bad_words(title, self.c.extra_words):
            return "language"
        if self.c.explicit == "block" and video_id:
            if explicit is not None:
                flag = explicit
            elif flag is _MISSING:
                flag = flags([video_id]).get(video_id, _MISSING)
            if flag is _MISSING and self.call and self.lookups > 0:
                self.lookups -= 1
                flag = look_up(self.call, video_id, title, artists)
            if flag is True:
                return "explicit"
            if flag is _MISSING:
                from .library import signin_of
                check_soon(video_id, title, artists, signin_of(self.profile))  # shows next time
                return "not checked yet"
        if self.c.lyrics_check and lyrics_bad(video_id, self.c.extra_words):
            return "language in the lyrics"
        return None

    def items(self, items: list) -> list:
        """Filter discovery items (songs, videos, albums, artists, playlists)."""
        known = flags(i.id for i in items if i.type in ("song", "video") and i.explicit is None)
        out, seen = [], set()
        for it in items:
            if it.type in ("song", "video"):
                reason = self.why_not(it.id, it.title, it.artists, it.explicit, known.get(it.id, _MISSING))
                if reason == "explicit" and self.c.clean_versions and self.call and self.lookups > 0:
                    self.lookups -= 1
                    clean = clean_version(self.call, it.title, it.artists)
                    if clean is not None and self.why_not(clean.id, clean.title, clean.artists, False) is None:
                        it, reason = clean, None
                if reason:
                    continue
            elif it.type == "album":
                if (self.c.explicit == "block" and it.explicit) or \
                        any(artist_key(a) in self._blocked_artists for a in it.artists) or \
                        (self.c.lyrics_check and bad_words(it.title, self.c.extra_words)):
                    continue
            elif it.type == "artist":
                if artist_key(it.title) in self._blocked_artists:
                    continue
            elif self.c.lyrics_check and bad_words(it.title, self.c.extra_words):
                continue
            if it.id not in seen:
                seen.add(it.id)
                out.append(it)
        return out

    def tracks(self, rows) -> list:
        """Filter library rows (the Household shelf): songs with no explicit mark yet wait
        for the background check."""
        rows = list(rows)
        known = flags(r["video_id"] for r in rows if r["video_id"])
        out = []
        for r in rows:
            artists = [r["artist"], r["album_artist"]]
            flag = known.get(r["video_id"], _MISSING) if r["video_id"] else None
            if self.why_not(r["video_id"], r["title"], artists, flag=flag) is None:
                out.append(r)
        return out


def children() -> list[str]:
    with connect() as conn:
        return [r[0] for r in conn.execute("SELECT profile FROM people WHERE role = 'child'")]


def is_child(profile: str) -> bool:
    with connect() as conn:
        r = conn.execute("SELECT role FROM people WHERE profile = ?", (profile,)).fetchone()
    return bool(r and r[0] == "child")


# --- background check of the music already on the PC ----------------------------------------

class Checker:
    """While a kids account blocks explicit songs, check the household's songs that have no
    explicit mark yet (one YouTube search each, paced by the adapter), so the Household shelf
    and "On the PC" fill in. About 1,500 songs an hour; skipped while offline."""

    BATCH = 50
    IDLE_S = 600

    def __init__(self, call: Call):
        self._call = call  # call(profile, fn_name, *args)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.checked = 0

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="dielify-kids-check", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5)

    def todo(self, limit: int) -> list[tuple[str, dict]]:
        """(sign-in, song) pairs still to check: songs a child just met first, then the
        stores' songs (for stores with a kid who blocks explicit)."""
        with _pending_lock:
            out = [(signin, {"video_id": vid, "title": title, "artist": (artists or [""])[0]})
                   for vid, (title, artists, signin) in list(_pending.items())[:limit]]
        if len(out) >= limit:
            return out
        stores = {}
        with connect() as conn:
            for r in conn.execute("SELECT p.profile, p.store, k.body FROM people p LEFT JOIN kid_controls k "
                                  "ON k.profile = p.profile WHERE p.role = 'child'"):
                if Controls.from_dict(json.loads(r["body"]) if r["body"] else {}).explicit == "block":
                    stores[r["store"]] = True
            for store in stores:
                out += [(store, dict(t)) for t in conn.execute(
                    "SELECT t.video_id, t.title, t.artist FROM tracks t WHERE t.profile = ? AND t.video_id IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM yt_flags f WHERE f.video_id = t.video_id) "
                    "ORDER BY t.created_at DESC LIMIT ?", (store, limit))]
        seen, unique = set(), []
        for signin, t in out:  # a song met in Discover may also be on the PC
            if t["video_id"] not in seen:
                seen.add(t["video_id"])
                unique.append((signin, t))
        return unique[:limit]

    def run_once(self) -> int:
        from . import settings as settings_mod
        if settings_mod.load().offline:
            return 0
        n = 0
        for store, t in self.todo(self.BATCH):
            if self._stop.is_set():
                break
            try:
                look_up(lambda fn, *a: self._call(store, fn, *a), t["video_id"], t["title"], [t["artist"]],
                        raise_errors=True)
            except Exception as e:  # noqa: BLE001 - YouTube unreachable / signed out: later
                log.info("Kids check paused: %s", getattr(e, "detail", e))
                break
            with _pending_lock:
                _pending.pop(t["video_id"], None)
            n += 1
        self.checked += n
        return n

    def _loop(self) -> None:
        self._stop.wait(60)  # let the app settle first
        while not self._stop.is_set():
            try:
                busy = self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("Kids check failed")
                busy = 0
            self._stop.wait(1 if busy else self.IDLE_S)
