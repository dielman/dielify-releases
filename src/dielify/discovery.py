"""Discovery from outside YouTube: radio charts and ListenBrainz.

Daily, per profile, Dielify builds a few lists and finds each song on YouTube Music (so
a tap plays it like any other song):
  - most played this week on triple j, Double J and triple j Unearthed (counted from
    the ABC's public "recently played" data),
  - trending this week on ListenBrainz (worldwide),
  - "Because you like <artist>": ListenBrainz's similar artists for your most-played
    artists, only ones not already in your library.
No account anywhere; only artist names / MusicBrainz ids leave the PC. YouTube matches
are remembered in ext_matches, so each song is searched for once.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import __version__, library, tags
from .httpclient import retrying_session
from .library import connect
from .yt_adapter import YTItem

log = logging.getLogger(__name__)

ABC_PLAYS = "https://music.abcradio.net.au/api/v1/plays/search.json"
LB_TRENDING = "https://api.listenbrainz.org/1/stats/sitewide/recordings"
LB_SIMILAR = "https://labs.api.listenbrainz.org/similar-artists/json"
LB_ALGORITHM = "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"
STATIONS = {"triplej": "triple j", "doublej": "Double J", "unearthed": "triple j Unearthed"}
CHART_SIZE = 30
REFRESH_S = 24 * 3600
MATCH_TTL_S = 30 * 86400

Caller = Callable[..., object]  # call(profile, adapter_method, *args)


def _http():
    s = retrying_session()
    s.headers["User-Agent"] = f"Dielify/{__version__} ( https://github.com/dielman/dielify-releases )"
    return s


# --- sources ------------------------------------------------------------------------------

def station_chart(station: str, http=None, days: int = 7, size: int = CHART_SIZE) -> list[tuple[str, str, int]]:
    """(artist, title, plays) most played on an ABC station over the last `days`."""
    http = http or _http()
    now = datetime.now(timezone.utc)
    params = {"station": station, "limit": 100, "order": "desc",
              "from": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "to": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    counts: Counter = Counter()
    shown: dict = {}
    offset = 0
    while offset < 6000:
        r = http.get(ABC_PLAYS, params={**params, "offset": offset}, timeout=30)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or []
        for it in items:
            rec = it.get("recording") or {}
            title = rec.get("title") or (it.get("summary") or {}).get("title")
            artists = [a.get("name") for a in rec.get("artists") or [] if a.get("name")]
            artist = artists[0] if artists else (it.get("summary") or {}).get("artist")
            if not title or not artist:
                continue
            key = (tags.norm(artist), tags.norm(title))
            counts[key] += 1
            shown.setdefault(key, (artist, title))
        offset += len(items)
        if not items or offset >= (data.get("total") or 0):
            break
    return [(*shown[k], n) for k, n in counts.most_common(size)]


def lb_trending(http=None, size: int = CHART_SIZE, per_artist: int = 2) -> list[tuple[str, str, int]]:
    """This week's most-played songs on ListenBrainz, at most `per_artist` per artist (one
    big release can otherwise fill the whole list)."""
    http = http or _http()
    r = http.get(LB_TRENDING, params={"range": "week", "count": size * 4}, timeout=30)
    r.raise_for_status()
    recs = ((r.json().get("payload") or {}).get("recordings")) or []
    out, per = [], Counter()
    for x in recs:
        a, t = x.get("artist_name"), x.get("track_name")
        if a and t and per[tags.norm(a)] < per_artist:
            per[tags.norm(a)] += 1
            out.append((a, t, x.get("listen_count") or 0))
    return out[:size]


def lb_similar_artists(mbid: str, http=None, limit: int = 12) -> list[str]:
    http = http or _http()
    r = http.get(LB_SIMILAR, params={"artist_mbids": mbid, "algorithm": LB_ALGORITHM}, timeout=30)
    r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else []
    return [x["name"] for x in sorted(rows, key=lambda x: -(x.get("score") or 0)) if x.get("name")][:limit]


# --- finding songs on YouTube Music ---------------------------------------------------------

def _cached_match(key: str) -> YTItem | None | bool:
    with connect() as conn:
        row = conn.execute("SELECT item, matched_at FROM ext_matches WHERE key = ?", (key,)).fetchone()
    if row is None or time.time() - row["matched_at"] > MATCH_TTL_S:
        return False  # not looked up (recently)
    return YTItem(**json.loads(row["item"])) if row["item"] else None


def _remember(key: str, item: YTItem | None) -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO ext_matches (key, item, matched_at) VALUES (?,?,?)",
                     (key, json.dumps(vars(item)) if item else None, time.time()))


def find_song(call: Caller, profile: str, artist: str, title: str) -> YTItem | None:
    """The YouTube Music song for (artist, title): the first song result whose artist
    matches; None if YouTube has nothing that fits."""
    key = f"song:{tags.norm(artist)}|{tags.norm(title)}"
    cached = _cached_match(key)
    if cached is not False:
        return cached
    results = call(profile, "search_items", f"{artist} {title}", "song", 5)
    want = tags.norm(artist)
    found = next((r for r in results if any(want in tags.norm(a) or tags.norm(a) in want for a in r.artists)), None)
    _remember(key, found)
    return found


def top_songs_by(call: Caller, profile: str, artist: str, n: int = 2) -> list[YTItem]:
    key = f"artist:{tags.norm(artist)}"
    with connect() as conn:
        row = conn.execute("SELECT item, matched_at FROM ext_matches WHERE key = ?", (key,)).fetchone()
    if row and time.time() - row["matched_at"] < MATCH_TTL_S:
        return [YTItem(**x) for x in json.loads(row["item"] or "[]")][:n]
    results = call(profile, "search_items", artist, "song", 6)
    want = tags.norm(artist)
    songs = [r for r in results if any(tags.norm(a) == want for a in r.artists)][:n]
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO ext_matches (key, item, matched_at) VALUES (?,?,?)",
                     (key, json.dumps([vars(s) for s in songs]), time.time()))
    return songs


# --- building the lists ---------------------------------------------------------------------

def _save(profile: str, key: str, title: str, subtitle: str, items: list[YTItem], position: int) -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO discovery_lists (profile, key, title, subtitle, items, position, "
                     "updated_at) VALUES (?,?,?,?,?,?,?)",
                     (profile, key, title, subtitle, json.dumps([vars(i) for i in items]), position, time.time()))


def _top_artists(profile: str, n: int = 3) -> list[tuple[str, str]]:
    """(name, MusicBrainz id) of your most-played album artists that MusicBrainz knows."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT ar.name, SUM(li.play_count) plays FROM library_items li JOIN tracks t ON t.id = li.track_id "
            "JOIN artists ar ON ar.id = t.artist_id "
            "WHERE li.profile = ? GROUP BY ar.name ORDER BY plays DESC, COUNT(*) DESC LIMIT 25", (profile,)).fetchall()
        out = []
        for r in rows:
            m = conn.execute("SELECT mbid FROM artist_tags WHERE name_key = ?", (tags.norm(r["name"]),)).fetchone()
            if m and m["mbid"]:
                out.append((r["name"], m["mbid"]))
            if len(out) >= n:
                break
    return out


def rebuild(profile: str, call: Caller, http=None, stop: threading.Event | None = None) -> int:
    """Build every list for one profile. Returns how many lists were saved."""
    http = http or _http()
    stop = stop or threading.Event()
    saved, pos = 0, 0
    keep = []

    def matched(chart):
        out = []
        for artist, title, _ in chart:
            if stop.is_set():
                break
            try:
                it = find_song(call, profile, artist, title)
            except Exception as e:  # YouTube unreachable: stop for now, cached ones still count
                log.info("Can't look up %s - %s on YouTube: %s", artist, title, e)
                break
            if it is not None and all(x.id != it.id for x in out):
                out.append(it)
        return out

    for station, label in STATIONS.items():
        try:
            items = matched(station_chart(station, http))
        except Exception as e:
            log.info("No %s chart: %s", label, e)
            continue
        if items:
            _save(profile, f"radio:{station}", f"{label}: most played this week",
                  f"Counted from {label}'s plays over the last 7 days", items, pos)
            keep.append(f"radio:{station}")
            saved, pos = saved + 1, pos + 1

    try:
        items = matched(lb_trending(http))
        if items:
            _save(profile, "lb:trending", "Trending on ListenBrainz", "Most played worldwide this week", items, pos)
            keep.append("lb:trending")
            saved, pos = saved + 1, pos + 1
    except Exception as e:
        log.info("No ListenBrainz trending: %s", e)

    with connect() as conn:
        have_artists = {tags.norm(r[0]) for r in conn.execute(
            "SELECT DISTINCT ar.name FROM library_items li JOIN tracks t ON t.id = li.track_id "
            "JOIN artists ar ON ar.id = t.artist_id WHERE li.profile = ?", (profile,))}
    for name, mbid in _top_artists(profile):
        if stop.is_set():
            break
        try:
            similar = [a for a in lb_similar_artists(mbid, http) if tags.norm(a) not in have_artists][:8]
            songs = []
            for a in similar:
                songs += top_songs_by(call, profile, a)
        except Exception as e:
            log.info("No similar artists for %s: %s", name, e)
            continue
        if songs:
            key = f"lb:like:{tags.norm(name)}"
            _save(profile, key, f"Because you like {name}", "Artists you don't have yet, via ListenBrainz", songs, pos)
            keep.append(key)
            saved, pos = saved + 1, pos + 1

    if not stop.is_set() and keep:
        with connect() as conn:  # lists that no longer apply (e.g. a different top artist)
            conn.execute(f"DELETE FROM discovery_lists WHERE profile = ? AND key NOT IN ({','.join('?' * len(keep))})",
                         (profile, *keep))
    log.info("Built %d outside-discovery lists for %s", saved, profile)
    return saved


def lists(profile: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM discovery_lists WHERE profile = ? ORDER BY position", (profile,)).fetchall()
    return [{**dict(r), "items": [YTItem(**x) for x in json.loads(r["items"])]} for r in rows]


class Discovery:
    """Background: rebuild the lists daily."""

    def __init__(self, call: Caller):
        self.call = call
        self._stop = threading.Event()
        self._busy = threading.Lock()

    def run_once(self, force: bool = False) -> None:
        from . import settings as settings_mod
        if settings_mod.load().offline or not self._busy.acquire(blocking=False):
            return
        try:
            profiles = library.profiles()
            for p in profiles:
                with connect() as conn:
                    last = conn.execute("SELECT MAX(updated_at) FROM discovery_lists WHERE profile = ?", (p,)).fetchone()[0]
                if force or last is None or time.time() - last > REFRESH_S:
                    rebuild(p, self.call, stop=self._stop)
        except Exception:
            log.exception("Outside discovery failed")
        finally:
            self._busy.release()

    def refresh_soon(self) -> None:
        threading.Thread(target=self.run_once, kwargs={"force": True}, daemon=True, name="dielify-discovery-now").start()

    def _loop(self) -> None:
        self._stop.wait(180)  # after startup, the mixes' genre lookups go first
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(3600)

    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="dielify-discovery").start()

    def stop(self) -> None:
        self._stop.set()
