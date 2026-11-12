"""Playlists from a link (Josh, 12 Nov): paste a YouTube / YouTube Music playlist or album link,
or a Spotify playlist or album link, and Dielify makes its own playlist of those songs. The new
playlist lives in Dielify only (not synced with YouTube Music); songs not in the library download
like any playlist's.

Spotify is read from its public embed page (open.spotify.com/embed/...): no account needed, but it
only lists the first 100 songs (checked 12 Nov 2026: "All Out 80s" has 150, the page gives 100).
Each Spotify song is looked up on YouTube Music by artist + title (discovery.find_song: the artist
must match; results are remembered for 30 days).

Imports run in the background: the playlist exists at once and fills as songs are found;
`job()` says how far it got and which songs weren't found."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qs, urlparse

import requests

from .yt_adapter import YTItem

log = logging.getLogger(__name__)

SPOTIFY_LIMIT = 100          # what Spotify's embed page lists
MAX_FAILURES = 3             # lookups failing in a row = YouTube isn't answering: stop
BATCH = 10                   # songs added to the playlist at a time (it fills as you watch)
KEEP_JOBS_S = 3600
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Dielify"}

_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
_SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}
_SPOTIFY_SHORT = {"spotify.link", "spotify.app.link"}
_ID = re.compile(r"^[A-Za-z0-9_-]{2,80}$")


@dataclass
class Link:
    source: str  # youtube | spotify
    kind: str    # playlist | album
    id: str


def parse(url: str, http=None) -> Link:
    """What a pasted link points at. Raises ValueError with words for the person."""
    url = (url or "").strip()
    m = re.match(r"^spotify:(playlist|album):([A-Za-z0-9]+)$", url)
    if m:
        return Link("spotify", m.group(1), m.group(2))
    if not re.match(r"^https?://", url):
        url = "https://" + url
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if host in _SPOTIFY_SHORT:  # a "Share" link from the Spotify app: follow it to open.spotify.com
        r = (http or requests).get(url, headers=UA, timeout=20, allow_redirects=True)
        u = urlparse(r.url)
        host = (u.hostname or "").lower()
    if host in _SPOTIFY_HOSTS:
        parts = [p for p in u.path.split("/") if p and not p.startswith("intl-")]
        if parts and parts[0] == "embed":
            parts = parts[1:]
        if len(parts) >= 2 and parts[0] in ("playlist", "album") and re.match(r"^[A-Za-z0-9]+$", parts[1]):
            return Link("spotify", parts[0], parts[1])
        raise ValueError("That Spotify link isn't a playlist or an album")
    if host in _YT_HOSTS:
        q = parse_qs(u.query)
        lst = (q.get("list") or [""])[0]
        if lst and _ID.match(lst):
            if lst.startswith("RD"):
                raise ValueError("That's a YouTube mix (it never ends): open a playlist or album link instead")
            return Link("youtube", "playlist", lst)
        m = re.match(r"^/browse/(MPREb_[A-Za-z0-9_-]+)$", u.path)
        if m:
            return Link("youtube", "album", m.group(1))
        raise ValueError("That YouTube link isn't a playlist or an album (it needs \"list=\" in it)")
    raise ValueError("Paste a link to a Spotify or YouTube playlist or album")


@dataclass
class ExtSong:
    artist: str
    title: str
    duration_s: int | None = None


def spotify_list(kind: str, sid: str, http=None) -> tuple[str, list[ExtSong]]:
    """(name, songs) of a public Spotify playlist or album, from its embed page."""
    r = (http or requests).get(f"https://open.spotify.com/embed/{kind}/{sid}", headers=UA, timeout=30)
    if r.status_code == 404:
        raise ValueError("Spotify doesn't have that (is the playlist public?)")
    r.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text, re.S)
    try:
        ent = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise ValueError("Couldn't read that Spotify page (Spotify may have changed it)") from e
    songs = []
    for t in ent.get("trackList") or []:
        title, artist = (t.get("title") or "").strip(), (t.get("subtitle") or "").replace("\xa0", " ").strip()
        if title and artist:
            d = t.get("duration")
            songs.append(ExtSong(artist, title, round(d / 1000) if isinstance(d, (int, float)) else None))
    return (ent.get("name") or ent.get("title") or "Spotify playlist").strip(), songs[:SPOTIFY_LIMIT]


# --- jobs ------------------------------------------------------------------------------------

@dataclass
class Job:
    id: str
    profile: str
    url: str
    source: str
    state: str = "working"            # working | done | failed
    name: str = ""
    playlist_id: int | None = None
    total: int = 0
    checked: int = 0
    added: int = 0
    missing: list[str] = field(default_factory=list)
    error: str | None = None
    note: str | None = None
    started: float = field(default_factory=time.time)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def job(job_id: str, profile: str) -> Job | None:
    with _lock:
        j = _jobs.get(job_id)
    return j if j and j.profile.casefold() == profile.casefold() else None


def _tidy() -> None:
    now = time.time()
    with _lock:
        for k in [k for k, j in _jobs.items() if j.state != "working" and now - j.started > KEEP_JOBS_S]:
            del _jobs[k]


class Importer:
    """Runs imports for one server. `call` = the YouTube caller (custom_api.youtube.call),
    `engine` = the playlists.Playlists that creates playlists and downloads their songs."""

    def __init__(self, call, engine):
        self.call, self.engine = call, engine

    def start(self, profile: str, link: Link, url: str) -> Job:
        _tidy()
        j = Job(uuid.uuid4().hex[:12], profile, url, link.source)
        with _lock:
            _jobs[j.id] = j
        threading.Thread(target=self._run, args=(j, link), name=f"import-{j.id}", daemon=True).start()
        return j

    def run_now(self, profile: str, link: Link, url: str) -> Job:
        """The same, in this thread (tests)."""
        j = Job(uuid.uuid4().hex[:12], profile, url, link.source)
        with _lock:
            _jobs[j.id] = j
        self._run(j, link)
        return j

    def _run(self, j: Job, link: Link) -> None:
        try:
            if link.source == "youtube":
                self._youtube(j, link)
            else:
                self._spotify(j, link)
            j.state = "done"
        except Exception as e:  # noqa: BLE001 - whatever went wrong is shown to the person
            j.error = _words(e)
            if j.playlist_id is not None and j.added == 0:  # don't leave an empty playlist behind
                try:
                    self.engine.delete(j.profile, j.playlist_id, on_youtube=False)
                    j.playlist_id = None
                except Exception:  # noqa: BLE001
                    pass
            j.state = "failed"  # last: whoever is watching sees the finished job
            log.info("Import of %s for %s failed: %s", j.url, j.profile, j.error)
        log.info("Import %s for %s: %s, %d/%d added", link.source, j.profile, j.state, j.added, j.total)

    def _create(self, j: Job, name: str) -> None:
        j.name = name.strip()[:150] or "Imported playlist"
        j.playlist_id = self.engine.create(j.profile, j.name, on_youtube=False)["id"]

    def _add(self, j: Job, items: list[YTItem]) -> None:
        if items:
            self.engine.add(j.profile, j.playlist_id, items)
            j.added += len(items)

    def _youtube(self, j: Job, link: Link) -> None:
        info, tracks = self.call(j.profile, link.kind, link.id)
        tracks = [t for t in tracks if t.type in ("song", "video") and t.id]
        if not tracks:
            raise ValueError("That YouTube playlist is empty or private")
        self._create(j, info.title or "YouTube playlist")
        j.total = len(tracks)
        for n in range(0, len(tracks), 100):
            self._add(j, tracks[n:n + 100])
            j.checked = min(n + 100, len(tracks))

    def _spotify(self, j: Job, link: Link) -> None:
        from .discovery import find_song
        name, songs = spotify_list(link.kind, link.id)
        if not songs:
            raise ValueError("That Spotify playlist is empty")
        self._create(j, name)
        j.total = len(songs)
        if len(songs) >= SPOTIFY_LIMIT:
            j.note = f"Spotify only shows the first {SPOTIFY_LIMIT} songs of a playlist, so that's what came across"
        batch, seen, failures = [], set(), 0
        for s in songs:
            try:
                found = find_song(self.call, j.profile, s.artist, s.title)
                failures = 0
            except Exception as e:  # noqa: BLE001 - one song failing to look up isn't the whole import...
                log.info("Import: looking up %s - %s failed: %s", s.artist, s.title, e)
                failures += 1
                if failures >= MAX_FAILURES:  # ...but YouTube not answering at all is: say so, not "not found"
                    self._add(j, batch)
                    raise RuntimeError(f"YouTube Music isn't answering ({_words(e)}). Stopped after "
                                       f"{j.checked + 1} of {j.total} songs") from e
                found = None
            j.checked += 1
            if found is None:
                j.missing.append(f"{s.artist} – {s.title}")
            elif found.id not in seen:
                seen.add(found.id)
                batch.append(found)
            if len(batch) >= BATCH:
                self._add(j, batch)
                batch = []
        self._add(j, batch)


def _words(e: Exception) -> str:
    return str(getattr(e, "detail", "") or "") or str(e) or type(e).__name__


def as_dict(j: Job) -> dict:
    d = asdict(j)
    d.pop("profile", None)
    return d
