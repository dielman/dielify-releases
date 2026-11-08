"""Genre tags for artists, from MusicBrainz (free and open; no account).

Only artist names are sent. MusicBrainz asks for at most one request per second and a
User-Agent naming the app; it sometimes answers 503 when busy, so we back off and retry.
Results (including "not found") are kept in artist_tags and refreshed after REFRESH_DAYS.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata

from . import __version__
from .httpclient import retrying_session
from .library import connect

log = logging.getLogger(__name__)

API = "https://musicbrainz.org/ws/2/artist/"
USER_AGENT = f"Dielify/{__version__} ( https://github.com/dielman/dielify-releases )"
MIN_GAP_S = 1.1
REFRESH_DAYS = 90

# Tags that describe something other than the music's genre.
NOT_GENRES = {
    "british", "american", "australian", "english", "french", "german", "canadian", "swedish", "irish",
    "scottish", "uk", "usa", "us", "new zealand", "japanese", "korean", "italian", "spanish", "dutch",
    "female vocalists", "male vocalists", "female vocalist", "male vocalist", "singer-songwriter",
    "producer", "seen live", "favorites", "favourite", "feminism", "christian", "composer", "dj",
    "rapper", "multiple personalities", "band", "duo", "group", "awesome", "love", "lgbt", "queer",
    "actor", "actress", "parody", "comedy", "orchestra", "remix", "cover", "covers", "live",
}
_DECADE = re.compile(r"^(19|20)?\d0s$")


def norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.casefold().replace("&", "and")).strip()


def genre_tags(tags: list[tuple[str, int]], top: int = 5) -> list[str]:
    """The artist's genres, strongest first, without nationalities, decades etc."""
    out = []
    for name, _ in sorted(tags, key=lambda t: -t[1]):
        name = name.casefold().strip().replace("hip-hop", "hip hop")
        if name in NOT_GENRES or _DECADE.match(name) or len(name) > 40:
            continue
        if name not in out:
            out.append(name)
    return out[:top]


def split_artists(text: str | None) -> list[str]:
    """'A, B & C feat. D' -> ['A', 'B', 'C', 'D']"""
    if not text:
        return []
    parts = re.split(r",|;| & | x | feat\.? | ft\.? | featuring | with ", text, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


class MusicBrainz:
    def __init__(self, session=None):
        self.http = session or retrying_session()
        self.http.headers["User-Agent"] = USER_AGENT
        self._last = 0.0

    def _get(self, params: dict) -> dict | None:
        for attempt in range(5):
            wait = self._last + MIN_GAP_S - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            r = self.http.get(API, params={**params, "fmt": "json"}, timeout=20)
            if r.status_code == 503:  # busy: back off
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        return None

    def artist(self, name: str) -> tuple[str | None, list[tuple[str, int]]] | None:
        """(MusicBrainz id, tags) for an exact name/alias match; (None, []) if there's no
        such artist; None if MusicBrainz didn't answer (try again later)."""
        q = name.replace('"', "")
        data = self._get({"query": f'artist:"{q}" OR alias:"{q}"', "limit": 10})
        if data is None:
            return None
        want, best = norm(name), None
        for a in data.get("artists") or []:
            names = [a.get("name") or ""] + [x.get("name") or "" for x in a.get("aliases") or []]
            if want not in {norm(n) for n in names}:
                continue
            tags = [(t["name"], int(t.get("count") or 0)) for t in a.get("tags") or [] if t.get("name")]
            weight = sum(c for _, c in tags) + (1 if tags else 0)
            if best is None or weight > best[0]:
                best = (weight, a.get("id"), tags)
        return (best[1], best[2]) if best else (None, [])


# --- the artist_tags table ---------------------------------------------------------------

def tags_for(names: list[str]) -> dict[str, list[str]]:
    """Genres per artist name (only those already looked up)."""
    keys = {norm(n): n for n in names}
    out = {}
    with connect() as conn:
        for key in keys:
            row = conn.execute("SELECT tags FROM artist_tags WHERE name_key = ?", (key,)).fetchone()
            if row and row["tags"]:
                out[keys[key]] = genre_tags([tuple(t) for t in json.loads(row["tags"])])
    return out


def library_artists() -> list[str]:
    """Every artist in any library: album artists and each name in track artists."""
    with connect() as conn:
        names = [r[0] for r in conn.execute("SELECT DISTINCT name FROM artists")]
        for (text,) in conn.execute("SELECT DISTINCT artist FROM tracks"):
            names += split_artists(text)
    seen, out = set(), []
    for n in names:
        k = norm(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def status() -> dict:
    names = library_artists()
    with connect() as conn:
        done = {r[0] for r in conn.execute("SELECT name_key FROM artist_tags WHERE fetched_at > ?",
                                           (time.time() - REFRESH_DAYS * 86400,))}
    looked_up = sum(1 for n in names if norm(n) in done)
    return {"artists": len(names), "looked_up": looked_up}


def tag_some(mb: MusicBrainz, stop: threading.Event, limit: int = 300) -> int:
    """Look up artists not done yet (or done long ago). Returns how many were looked up."""
    cutoff = time.time() - REFRESH_DAYS * 86400
    with connect() as conn:
        fresh = {r[0] for r in conn.execute("SELECT name_key FROM artist_tags WHERE fetched_at > ?", (cutoff,))}
    todo = [n for n in library_artists() if norm(n) not in fresh][:limit]
    n = 0
    for name in todo:
        if stop.is_set():
            break
        try:
            found = mb.artist(name)
        except Exception as e:  # network trouble: try again next round
            log.info("MusicBrainz lookup failed for %r: %s", name, e)
            break
        if found is None:
            break
        mbid, tags = found
        with connect() as conn:
            conn.execute("INSERT OR REPLACE INTO artist_tags (name_key, name, mbid, tags, fetched_at) "
                         "VALUES (?,?,?,?,?)", (norm(name), name, mbid, json.dumps(tags), time.time()))
        n += 1
    if n:
        log.info("Looked up genres for %d artists on MusicBrainz", n)
    return n
