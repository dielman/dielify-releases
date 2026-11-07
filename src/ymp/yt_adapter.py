"""The ONLY module that talks to YouTube.

ytmusicapi (catalogue, search, metadata) and yt-dlp (audio) both track YouTube's
private APIs and break from time to time. Everything else in ymp depends on the
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


def parse_browser_headers(raw: str) -> dict:
    """Turn request headers copied from browser DevTools into ytmusicapi auth."""
    import ytmusicapi
    try:
        auth = json.loads(ytmusicapi.setup(filepath=None, headers_raw=raw))
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
    """Versions/locations of everything a download needs (for `ymp doctor`)."""
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
        self._yt = YTMusic(auth=auth, language=language) if auth else YTMusic(language=language)
        self._http = requests.Session()

    # Gentle pacing so traffic looks like a person, not a bot.
    def _pace(self) -> None:
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
            raise NotSignedIn("Not signed in. Run: ymp auth login")
        self._pace()
        try:
            info = self._yt.get_account_info()
        except Exception as e:
            raise NotSignedIn(
                "YouTube rejected the saved sign-in (cookies usually expire after a "
                "few weeks). Run: ymp auth login") from e
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

    def get_track(self, video_id: str) -> TrackInfo:
        """Full metadata for tagging: album, track number, year, best cover."""
        self._pace()
        try:
            wp = self._yt.get_watch_playlist(videoId=video_id, limit=1)
            t = next(x for x in wp["tracks"] if x.get("videoId") == video_id)
        except StopIteration:
            raise YouTubeError(f"Track {video_id} not found")
        except Exception as e:
            raise YouTubeError(f"Couldn't load track {video_id}: {e}") from e

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
        try:
            r = self._http.get(url, timeout=20)
            if r.status_code == 404 and "maxresdefault" in url:
                r = self._http.get(url.replace("maxresdefault", "hqdefault"), timeout=20)
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            log.warning("Cover art download failed: %s", e)
            return None

    def fetch_audio(self, video_id: str, dest_dir: Path, quality: str = "auto",
                    preferred_format: str = "auto",
                    progress: ProgressFn | None = None) -> Path:
        """Download audio only, without re-encoding. Returns the file path."""
        import yt_dlp

        fmt = {
            "auto": "bestaudio",
            "high": "bestaudio",
            "standard": "bestaudio[abr<=160]/bestaudio",
        }[quality]
        if preferred_format == "m4a":
            fmt = f"bestaudio[ext=m4a]/{fmt}"
        elif preferred_format == "opus":
            fmt = f"bestaudio[acodec=opus]/{fmt}"

        dest_dir.mkdir(parents=True, exist_ok=True)
        cookie_dir = tempfile.mkdtemp(prefix="ymp-")
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
            if self._auth:
                cookie = next((v for k, v in self._auth.items() if k.lower() == "cookie"), "")
                cookie_file = os.path.join(cookie_dir, "cookies.txt")
                with open(cookie_file, "w", encoding="utf-8") as f:
                    f.write(cookie_header_to_netscape(cookie))
                if os.name != "nt":
                    os.chmod(cookie_file, 0o600)
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
