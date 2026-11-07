"""The ONLY module that talks to YouTube.

ytmusicapi (catalogue, search, metadata) and yt-dlp (audio) both track YouTube's
private APIs and break from time to time. Everything else in Dielify depends on the
small interface here, so a fix after a YouTube change should only touch this file
(plus a version bump in pyproject.toml).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable

import requests

log = logging.getLogger(__name__)

YTM_WATCH_URL = "https://music.youtube.com/watch?v={}"
ProgressFn = Callable[[dict], None]


class YouTubeError(Exception):
    """Something YouTube-facing failed. Message is safe to show to the user."""


class NotSignedIn(YouTubeError):
    pass


class Offline(YouTubeError):
    """Offline mode is on: Dielify doesn't contact YouTube at all."""


def _check_online() -> None:
    from .settings import load
    if load().offline:
        raise Offline("Offline mode is on, so Dielify isn't contacting YouTube. "
                      "Your downloaded music still plays.")


@dataclass
class TrackInfo:
    video_id: str
    title: str
    artists: list[str] = field(default_factory=list)
    album: str | None = None
    album_id: str | None = None
    album_artist: str | None = None
    track_number: int | None = None
    track_total: int | None = None
    year: str | None = None
    duration_s: int | None = None
    cover_url: str | None = None
    is_video: bool = False  # music video rather than an album track

    @property
    def artist(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown Artist"


ITEM_TYPES = ("song", "video", "album", "playlist", "artist")


@dataclass
class YTItem:
    """Anything discovery can show: a song/video (id = videoId), album (browseId),
    playlist (playlistId) or artist (channel id)."""
    type: str
    id: str
    title: str
    artists: list[str] = field(default_factory=list)
    album: str | None = None
    album_id: str | None = None
    year: str | None = None
    duration_s: int | None = None
    thumbnail: str | None = None
    subtitle: str | None = None


@dataclass
class Shelf:
    title: str
    items: list[YTItem]


def to_item(raw: dict) -> YTItem | None:
    """Normalise any ytmusicapi result (home, search, charts, album, playlist)."""
    if not raw:
        return None
    browse = raw.get("browseId") or ""
    artists = [a["name"] for a in raw.get("artists") or [] if a.get("name")]
    album = raw.get("album") if isinstance(raw.get("album"), dict) else {}
    thumb = _best_thumb(raw.get("thumbnails") or raw.get("thumbnail"))
    if raw.get("videoId"):
        is_song = (raw.get("resultType") == "song" or raw.get("videoType") == "MUSIC_VIDEO_TYPE_ATV"
                   or (raw.get("videoType") is None and bool(album)))
        return YTItem("song" if is_song else "video", raw["videoId"], raw.get("title") or raw["videoId"],
                      artists, album.get("name"), album.get("id"), raw.get("year"),
                      raw.get("duration_seconds") or _parse_duration(raw.get("duration") or raw.get("length")),
                      thumb)
    if browse.startswith("MPRE"):
        return YTItem("album", browse, raw.get("title") or "", artists, year=raw.get("year"),
                      thumbnail=thumb, subtitle=raw.get("type"))
    if raw.get("playlistId") or browse.startswith("VL"):
        author = raw.get("author")
        if isinstance(author, list):
            author = ", ".join(a.get("name", "") for a in author if a)
        elif isinstance(author, dict):
            author = author.get("name")
        return YTItem("playlist", raw.get("playlistId") or browse[2:], raw.get("title") or "",
                      thumbnail=thumb, subtitle=author or raw.get("description"))
    if browse.startswith("UC"):
        return YTItem("artist", browse, raw.get("title") or raw.get("artist") or "", thumbnail=thumb,
                      subtitle=raw.get("subscribers"))
    return None


def _items(raws) -> list[YTItem]:
    return [i for i in map(to_item, raws or []) if i]


# --- helpers (pure functions, unit-tested) ----------------------------------

def upscale_cover_url(url: str | None, size: int = 1200) -> str | None:
    """YouTube Music thumbnails accept size parameters; ask for a large one."""
    if not url:
        return None
    if "googleusercontent.com" in url or "ggpht.com" in url:
        return re.sub(r"=w\d+-h\d+.*$", f"=w{size}-h{size}-l90-rj", url)
    if "i.ytimg.com" in url:  # video thumbnails: try the max-res variant
        return re.sub(r"/[a-z0-9_]+\.(jpg|webp)(\?.*)?$", "/maxresdefault.jpg", url)
    return url


_TITLE_NOISE = re.compile(
    r"\s*[\(\[](?:official\s*(?:music\s*)?(?:video|audio|lyric\s*video|visualizer)|"
    r"lyrics?|lyric\s*video|audio|hd|hq|4k|remastered(?:\s*\d{4})?)[\)\]]\s*", re.I)


def split_video_title(title: str, channel: str | None) -> tuple[str | None, str]:
    """'Vance Joy - Riptide (Official Video)' by 'VanceJoyVEVO' -> ('Vance Joy', 'Riptide')."""
    clean = _TITLE_NOISE.sub(" ", title).strip()
    for sep in (" - ", " \u2013 ", " \u2014 ", " | "):
        if sep in clean:
            artist, song = clean.split(sep, 1)
            if artist.strip() and song.strip():
                return artist.strip(), song.strip()
    name = re.sub(r"(?:VEVO| - Topic|Official)$", "", channel or "", flags=re.I).strip() or None
    return name, clean or title


def _best_thumb(thumbnails: list[dict] | None) -> str | None:
    if not thumbnails:
        return None
    best = max(thumbnails, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
    return best.get("url")


def _parse_duration(text: str | None) -> int | None:
    if not text:
        return None
    try:
        secs = 0
        for part in text.split(":"):
            secs = secs * 60 + int(part)
        return secs
    except ValueError:
        return None


def _short_error(e: Exception, limit: int = 200) -> str:
    """One-line description of an exception, with anything cookie-like masked."""
    text = " ".join(str(e).split()) or "(no message)"
    text = re.sub(r"(SAPISID\w*|[A-Z0-9_-]*SID\w*)[= ]\S+", r"\1=***", text)
    return f"{type(e).__name__}: {text[:limit]}"


def _text(node) -> str | None:
    if isinstance(node, dict):
        if node.get("simpleText"):
            return node["simpleText"]
        runs = node.get("runs") or []
        return "".join(r.get("text", "") for r in runs) or None
    return None


def _find_account_name(obj) -> str | None:
    """Find the signed-in account's name anywhere in an account-menu response."""
    if isinstance(obj, dict):
        header = obj.get("activeAccountHeaderRenderer")
        if isinstance(header, dict):
            return _text(header.get("accountName")) or _text(header.get("channelHandle")) or "(signed in)"
        children = obj.values()
    elif isinstance(obj, list):
        children = obj
    else:
        return None
    for child in children:
        found = _find_account_name(child)
        if found:
            return found
    return None


# Cookies a signed-in YouTube session normally carries (names only, never values).
_SIGNIN_COOKIES = ("SAPISID", "__Secure-3PAPISID", "SID", "HSID", "SSID", "APISID",
                   "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO")


def _cookie_report(auth: dict | None) -> str:
    """Which sign-in cookies were copied. Safe to show: no values."""
    auth = {k.lower(): v for k, v in (auth or {}).items()}
    jar = {p.split("=", 1)[0].strip() for p in auth.get("cookie", "").split(";") if "=" in p}
    missing = [c for c in _SIGNIN_COOKIES if c not in jar]
    report = (f"{len(jar)} cookies copied; sign-in cookies missing: "
              f"{', '.join(missing) or 'none'}. x-goog-authuser={auth.get('x-goog-authuser', '?')}")
    if "x-goog-pageid" in auth:
        report += ", x-goog-pageid present (brand account)"
    return report + "."


def cookie_header_to_netscape(cookie_header: str) -> str:
    """Convert a browser `Cookie:` header to a Netscape cookie file for yt-dlp."""
    jar = SimpleCookie()
    jar.load(cookie_header)
    expires = int(time.time()) + 3600  # temporary file, short expiry is fine
    lines = ["# Netscape HTTP Cookie File"]
    for name, morsel in jar.items():
        lines.append("\t".join([".youtube.com", "TRUE", "/", "TRUE", str(expires),
                                name, morsel.value]))
    if len(lines) == 1:
        raise YouTubeError("No cookies found in the saved sign-in headers.")
    return "\n".join(lines) + "\n"


_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")


def normalize_headers(raw: str) -> dict[str, str]:
    """Read headers in any DevTools copy format into {lowercase-name: value}.

    Handles Chrome/Edge raw view ("name: value"), Chrome's normal view (name and
    value on separate lines, with or without a colon), tab-separated pairs, Windows
    line endings, HTTP/2 pseudo-headers and Chrome's multi-line "Decoded:" block.
    """
    headers: dict[str, str] = {}
    pending: str | None = None
    in_decoded = False
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        if in_decoded:  # x-client-data's decoded protobuf, ends with "}"
            in_decoded = line != "}"
            continue
        if line.rstrip(":") == "Decoded":
            in_decoded, pending = True, None
            continue
        if pending is not None:
            if not pending.startswith(":"):
                headers[pending.lower()] = line
            pending = None
            continue
        if "\t" in line:
            name, value = line.split("\t", 1)
        elif ": " in line[1:]:
            idx = line.index(": ", 1)
            name, value = line[:idx], line[idx + 2:]
        elif line.endswith(":") or _HEADER_NAME.match(line):
            pending = line.rstrip(":")
            continue
        else:
            continue
        name = name.strip().rstrip(":")
        if name and not name.startswith(":"):
            headers[name.lower()] = value.strip()
    return headers


YTM_ORIGIN = "https://music.youtube.com"


def sapisid_hash(sapisid: str, origin: str = YTM_ORIGIN, now: int | None = None) -> str:
    """The `authorization` header browsers send, derived from the SAPISID cookie."""
    import hashlib
    ts = str(now or int(time.time()))
    return f"SAPISIDHASH {ts}_{hashlib.sha1(f'{ts} {sapisid} {origin}'.encode()).hexdigest()}"


def headers_from_cookies(cookies: dict[str, str], authuser: str = "0", pageid: str | None = None,
                         user_agent: str | None = None) -> dict:
    """Build ytmusicapi browser auth from cookies read out of a signed-in window,
    i.e. the same headers a person would otherwise copy from DevTools."""
    sapisid = cookies.get("__Secure-3PAPISID") or cookies.get("SAPISID")
    if not sapisid:
        raise NotSignedIn("The window isn't signed in to YouTube Music (no SAPISID cookie).")
    headers = {
        "cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "authorization": sapisid_hash(sapisid),
        "x-goog-authuser": str(authuser or "0"),
        "x-origin": YTM_ORIGIN,
        "user-agent": user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "accept": "*/*",
        "content-type": "application/json",
    }
    if pageid:
        headers["x-goog-pageid"] = pageid  # brand account / channel the person chose
    return parse_browser_headers("\n".join(f"{k}: {v}" for k, v in headers.items()))


def parse_browser_headers(raw: str) -> dict:
    """Turn request headers copied from browser DevTools into ytmusicapi auth."""
    import ytmusicapi
    found = normalize_headers(raw)
    missing = [h for h in ("cookie", "x-goog-authuser") if h not in found]
    if missing:
        names = ", ".join(sorted(found)) or "none"
        raise YouTubeError(
            f"The copied headers are missing: {', '.join(missing)}. "
            f"Header names found: {names}. Copy the Request Headers (not Response "
            "Headers) of a music.youtube.com 'browse' request (see README, 'Sign in').")
    site = " ".join(found.get(h, "") for h in ("x-origin", "origin", "referer", ":authority"))
    if "youtube.com" in site and "music.youtube.com" not in site:
        raise YouTubeError(
            "These headers were copied from www.youtube.com. Copy them from "
            "music.youtube.com instead (see README, 'Sign in').")
    clean = "\n".join(f"{k}: {v}" for k, v in found.items())
    try:
        auth = json.loads(ytmusicapi.setup(filepath=None, headers_raw=clean))
    except Exception as e:  # ytmusicapi raises various types here
        raise YouTubeError(
            "Those headers didn't look right. Copy them from a request to "
            "music.youtube.com (see README, 'Sign in').") from e
    cookie = next((v for k, v in auth.items() if k.lower() == "cookie"), "")
    if "SAPISID" not in cookie:
        raise YouTubeError(
            "The pasted headers have no sign-in cookie (SAPISID). Make sure you are "
            "signed in to music.youtube.com and copied the full request headers.")
    return auth


def check_runtime() -> dict[str, str | None]:
    """Versions/locations of everything a download needs (for `dielify doctor`)."""
    import mutagen
    import yt_dlp
    import ytmusicapi
    return {
        "yt-dlp": yt_dlp.version.__version__,
        "ytmusicapi": getattr(ytmusicapi, "__version__", None) or _pkg_version("ytmusicapi"),
        "mutagen": mutagen.version_string,
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "deno": shutil.which("deno"),
        "node": shutil.which("node"),
    }


def _pkg_version(name: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version(name)
    except PackageNotFoundError:
        return None


# --- the adapter ------------------------------------------------------------

class YTMusicAdapter:
    def __init__(self, auth: dict | None = None, request_delay_s: float = 1.5,
                 language: str = "en"):
        from ytmusicapi import YTMusic
        self._auth = auth
        self._delay = request_delay_s
        self._last_call = 0.0
        try:
            self._yt = YTMusic(auth=auth, language=language) if auth else YTMusic(language=language)
        except Exception as e:  # ytmusicapi rejects malformed auth here
            raise NotSignedIn(f"The saved sign-in isn't usable: {_short_error(e)}") from e
        self._http = requests.Session()

    # Gentle pacing so traffic looks like a person, not a bot.
    def _pace(self) -> None:
        _check_online()  # every YouTube call passes through here
        wait = self._delay - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @property
    def signed_in(self) -> bool:
        return self._auth is not None

    def account_name(self) -> str:
        """Confirms the sign-in still works. Raises NotSignedIn if it doesn't."""
        if not self._auth:
            raise NotSignedIn("Not signed in. Run: dielify auth login")
        self._pace()
        try:
            info = self._yt.get_account_info()
        except KeyError:
            # ytmusicapi reads the name from one fixed path, which YouTube moves
            # around. Search the raw menu instead; no account header = signed out.
            try:
                menu = self._yt._send_request("account/account_menu", {})
            except Exception as e:
                raise YouTubeError(f"Couldn't confirm the sign-in with YouTube: {_short_error(e)}") from e
            name = _find_account_name(menu)
            if name:
                return name
            raise NotSignedIn(
                "YouTube answered as if you were signed out, so the copied cookies "
                "weren't accepted. " + _cookie_report(self._auth)) from None
        except Exception as e:
            detail = _short_error(e)
            if re.search(r"\b(401|403)\b|sign(ed)? ?in|login", detail, re.I):
                raise NotSignedIn(
                    "YouTube rejected the sign-in (cookies usually expire after a few "
                    f"weeks). Run: dielify auth login  [{detail}]") from e
            raise YouTubeError(f"Couldn't confirm the sign-in with YouTube: {detail}") from e
        return info.get("accountName") or info.get("channelHandle") or "(signed in)"

    def search(self, query: str, limit: int = 10, videos: bool = False) -> list[TrackInfo]:
        self._pace()
        try:
            results = self._yt.search(query, filter="videos" if videos else "songs",
                                      limit=limit)
        except Exception as e:
            raise YouTubeError(f"Search failed: {e}") from e
        out = []
        for r in results:
            vid = r.get("videoId")
            if not vid:
                continue
            album = r.get("album") or {}
            out.append(TrackInfo(
                video_id=vid,
                title=r.get("title") or vid,
                artists=[a["name"] for a in r.get("artists") or [] if a.get("name")],
                album=album.get("name"),
                album_id=album.get("id"),
                year=r.get("year"),
                duration_s=r.get("duration_seconds") or _parse_duration(r.get("duration")),
                cover_url=_best_thumb(r.get("thumbnails")),
                is_video=r.get("resultType") == "video",
            ))
        return out[:limit]

    # --- discovery (Phase 3) -------------------------------------------------------

    def _call(self, what: str, fn, *args, **kwargs):
        self._pace()
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            raise YouTubeError(f"{what} failed: {_short_error(e)}") from e

    def home(self, shelves: int = 6) -> list[Shelf]:
        """The personalised home feed: mixes, playlists, new releases..."""
        raw = self._call("Loading the home feed", self._yt.get_home, limit=shelves)
        return [Shelf(s.get("title") or "", _items(s.get("contents"))) for s in raw]

    def charts(self, country: str = "ZZ") -> dict:
        """Chart playlists (open with `playlist`) and top artists. ZZ = global."""
        raw = self._call("Loading charts", self._yt.get_charts, country=country)
        return {"country": ((raw.get("countries") or {}).get("selected") or {}).get("text") or country,
                "countries": (raw.get("countries") or {}).get("options") or [],
                "playlists": _items(raw.get("videos")) + _items(raw.get("songs")),
                "artists": _items(raw.get("artists"))}

    def similar(self, video_id: str, limit: int = 25) -> list[YTItem]:
        """Songs like this one (YouTube Music's radio for it), without the song itself."""
        raw = self._call("Loading similar songs", self._yt.get_watch_playlist,
                         videoId=video_id, radio=True, limit=limit + 1)
        return [i for i in _items(raw.get("tracks")) if i.id != video_id][:limit]

    def search_items(self, query: str, kind: str = "song", limit: int = 20) -> list[YTItem]:
        if kind not in ITEM_TYPES:
            raise ValueError(f"type must be one of {ITEM_TYPES}")
        raw = self._call("Search", self._yt.search, query, filter=kind + "s", limit=limit)
        return _items(raw)[:limit]

    def album(self, browse_id: str) -> tuple[YTItem, list[YTItem]]:
        raw = self._call("Loading the album", self._yt.get_album, browse_id)
        info = to_item({**raw, "browseId": browse_id}) or YTItem("album", browse_id, raw.get("title", ""))
        tracks = _items({**t, "album": t.get("album") or {"name": raw.get("title"), "id": browse_id}}
                        for t in raw.get("tracks") or [] if t.get("isAvailable", True))
        for t in tracks:  # YouTube labels some album tracks as videos; on an album they're songs
            t.type = "song"
            t.year = t.year or raw.get("year")
        return info, tracks

    def playlist(self, playlist_id: str, limit: int = 5000) -> tuple[YTItem, list[YTItem]]:
        # ytmusicapi fetches pages of 100 until it has `limit`: ask for (practically) all
        raw = self._call("Loading the playlist", self._yt.get_playlist, playlist_id, limit=limit)
        info = to_item({**raw, "playlistId": playlist_id}) or YTItem("playlist", playlist_id, "")
        tracks = _items(t for t in raw.get("tracks") or [] if t.get("isAvailable", True))
        return info, tracks[:limit]

    def my_playlists(self) -> list[YTItem]:
        """The signed-in account's own playlists in YouTube Music (and Liked Music)."""
        raw = self._call("Loading your playlists", self._yt.get_library_playlists, limit=None)
        items = []
        for p in raw or []:
            it = to_item(p)
            if it is None:
                continue
            count = p.get("count")
            if count:
                it.subtitle = f"{count} songs"
            items.append(it)
        return items

    # --- downloading -----------------------------------------------------------------

    def get_track(self, video_id: str) -> TrackInfo:
        """Full metadata for tagging: album, track number, year, best cover."""
        self._pace()
        try:
            wp = self._yt.get_watch_playlist(videoId=video_id, limit=1)
            t = next((x for x in wp.get("tracks") or [] if x.get("videoId") == video_id), None)
        except Exception as e:  # ytmusicapi can trip over unusual videos (e.g. KeyError 'videoId')
            log.warning("Watch-playlist lookup failed for %s: %s", video_id, e)
            t = None
        if t is None:
            # Videos that aren't in YouTube Music's catalogue (e.g. many VEVO uploads) get an
            # unrelated list back; use the video's own details instead.
            return self._track_from_video(video_id)

        album = t.get("album") or {}
        info = TrackInfo(
            video_id=video_id,
            title=t.get("title") or video_id,
            artists=[a["name"] for a in t.get("artists") or [] if a.get("name")],
            album=album.get("name"),
            album_id=album.get("id"),
            year=t.get("year"),
            duration_s=_parse_duration(t.get("length")),
            cover_url=_best_thumb(t.get("thumbnail")),
            is_video=t.get("videoType") not in (None, "MUSIC_VIDEO_TYPE_ATV"),
        )
        if info.album_id:
            self._enrich_from_album(info)
        info.cover_url = upscale_cover_url(info.cover_url)
        return info

    def _track_from_video(self, video_id: str) -> TrackInfo:
        self._pace()
        try:
            vd = (self._yt.get_song(video_id) or {}).get("videoDetails") or {}
        except Exception as e:
            raise YouTubeError(f"Couldn't load video {video_id}: {e}") from e
        if not vd.get("title"):
            raise YouTubeError(f"Video {video_id} not found")
        artist, title = split_video_title(vd["title"], vd.get("author"))
        try:
            duration = int(vd.get("lengthSeconds") or 0) or None
        except ValueError:
            duration = None
        cover = _best_thumb((vd.get("thumbnail") or {}).get("thumbnails"))
        return TrackInfo(video_id=video_id, title=title, artists=[artist] if artist else [],
                         duration_s=duration, cover_url=upscale_cover_url(cover), is_video=True)

    def _enrich_from_album(self, info: TrackInfo) -> None:
        self._pace()
        try:
            alb = self._yt.get_album(info.album_id)
        except Exception as e:  # metadata is a nice-to-have; don't fail the download
            log.warning("Album lookup failed for %s: %s", info.album_id, e)
            return
        info.album = alb.get("title") or info.album
        info.year = alb.get("year") or info.year
        artists = [a["name"] for a in alb.get("artists") or [] if a.get("name")]
        info.album_artist = ", ".join(artists) or None
        tracks = alb.get("tracks") or []
        info.track_total = alb.get("trackCount") or len(tracks) or None
        for i, tr in enumerate(tracks, start=1):
            if tr.get("videoId") == info.video_id:
                info.track_number = tr.get("trackNumber") or i
                break
        album_cover = _best_thumb(alb.get("thumbnails"))
        if album_cover:  # square album art beats a 16:9 video frame
            info.cover_url = album_cover
        info.is_video = False

    def fetch_cover(self, url: str | None) -> bytes | None:
        if not url:
            return None
        _check_online()
        try:
            r = self._http.get(url, timeout=20)
            if r.status_code == 404 and "maxresdefault" in url:
                r = self._http.get(url.replace("maxresdefault", "hqdefault"), timeout=20)
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            log.warning("Cover art download failed: %s", e)
            return None

    @staticmethod
    def _format(quality: str, preferred_format: str) -> str:
        fmt = {
            "auto": "bestaudio",
            "high": "bestaudio",
            "standard": "bestaudio[abr<=160]/bestaudio",
        }[quality]
        if preferred_format == "m4a":
            fmt = f"bestaudio[ext=m4a]/{fmt}"
        elif preferred_format == "opus":
            fmt = f"bestaudio[acodec=opus]/{fmt}"
        return fmt

    def _cookie_file(self, cookie_dir: str) -> str | None:
        """The signed-in cookies as a temporary Netscape cookie file (for yt-dlp)."""
        if not self._auth:
            return None
        cookie = next((v for k, v in self._auth.items() if k.lower() == "cookie"), "")
        cookie_file = os.path.join(cookie_dir, "cookies.txt")
        with open(cookie_file, "w", encoding="utf-8") as f:
            f.write(cookie_header_to_netscape(cookie))
        if os.name != "nt":
            os.chmod(cookie_file, 0o600)
        return cookie_file

    def stream_info(self, video_id: str, quality: str = "auto",
                    preferred_format: str = "auto") -> "StreamInfo":
        """Where to fetch a song's audio right now (for playing before it's downloaded).
        The URL works for a few hours; it's never shown to phones, the PC relays it."""
        import yt_dlp
        _check_online()
        cookie_dir = tempfile.mkdtemp(prefix="dielify-")
        try:
            opts: dict = {"format": self._format(quality, preferred_format), "noplaylist": True,
                          "quiet": True, "no_warnings": False, "logger": _YdlLogger()}
            cookie_file = self._cookie_file(cookie_dir)
            if cookie_file:
                opts["cookiefile"] = cookie_file
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(YTM_WATCH_URL.format(video_id), download=False)
            fmt = (info.get("requested_formats") or [info])[0]
            url = fmt.get("url") or info.get("url")
            if not url:
                raise YouTubeError(f"No playable audio for {video_id}")
            ext = fmt.get("ext") or info.get("ext") or "webm"
            mime = {"m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm",
                    "opus": "audio/ogg"}.get(ext, "application/octet-stream")
            log.info("Streaming %s: format %s, %s kbps", video_id, fmt.get("format_id"), fmt.get("abr"))
            return StreamInfo(video_id=video_id, url=url, headers=dict(fmt.get("http_headers") or {}),
                              mime=mime, size=fmt.get("filesize") or fmt.get("filesize_approx"),
                              title=info.get("track") or info.get("title") or video_id,
                              artist=info.get("artist") or info.get("uploader"),
                              album=info.get("album"), available_at=float(fmt.get("available_at") or 0))
        except yt_dlp.utils.DownloadError as e:
            raise YouTubeError(f"Can't play {video_id}: {e}") from e
        finally:
            shutil.rmtree(cookie_dir, ignore_errors=True)  # never leave cookies on disk

    def fetch_audio(self, video_id: str, dest_dir: Path, quality: str = "auto",
                    preferred_format: str = "auto",
                    progress: ProgressFn | None = None) -> Path:
        """Download audio only, without re-encoding. Returns the file path."""
        import yt_dlp
        _check_online()

        fmt = self._format(quality, preferred_format)
        dest_dir.mkdir(parents=True, exist_ok=True)
        cookie_dir = tempfile.mkdtemp(prefix="dielify-")
        cookie_file = None
        try:
            opts: dict = {
                "format": fmt,
                "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": False,
                "noprogress": True,
                "sleep_interval_requests": min(self._delay, 2.0),
                "retries": 3,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}],
                "logger": _YdlLogger(),
            }
            cookie_file = self._cookie_file(cookie_dir)
            if cookie_file:
                opts["cookiefile"] = cookie_file
            if progress:
                opts["progress_hooks"] = [progress]

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(YTM_WATCH_URL.format(video_id), download=True)
            path = Path(info["requested_downloads"][0]["filepath"])
            if not path.exists():
                raise YouTubeError("yt-dlp reported success but no file was written")
            log.info("Got %s: format %s, %s kbps", video_id, info.get("format_id"),
                     info.get("abr"))
            return path
        except yt_dlp.utils.DownloadError as e:
            hint = ""
            if not shutil.which("deno") and not shutil.which("node"):
                hint = " (No JavaScript runtime found: install Deno, see README.)"
            raise YouTubeError(f"Download failed for {video_id}: {e}{hint}") from e
        finally:
            shutil.rmtree(cookie_dir, ignore_errors=True)  # never leave cookies on disk


@dataclass
class StreamInfo:
    video_id: str
    url: str
    headers: dict
    mime: str
    size: int | None
    title: str
    artist: str | None = None
    album: str | None = None
    available_at: float = 0.0  # YouTube refuses the address (403) before this time
    fetched_at: float = field(default_factory=time.time)


class _YdlLogger:
    """Route yt-dlp output through logging (and keep it quiet by default)."""
    def debug(self, msg: str) -> None:
        log.debug(msg)

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        log.warning(msg)

    def error(self, msg: str) -> None:
        log.error(msg)
