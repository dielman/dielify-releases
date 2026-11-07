"""Subsonic / OpenSubsonic API, so Symfonium, Ultrasonic and DSub can use the library.

Every call is /rest/<method> (optionally with ".view"), GET or form POST, and
answers in XML by default or JSON with f=json. Errors are HTTP 200 with
status="failed", as the protocol expects.

IDs are typed strings: "ar-1" artist, "al-2" album, "tr-3" track. Cover-art IDs use
the same forms.
"""

from __future__ import annotations

import io
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from . import __version__, auth
from . import settings as settings_mod
from .library import CONTENT_TYPES, Library
from .tagging import read_cover

log = logging.getLogger(__name__)

API_VERSION = "1.16.1"
XMLNS = "http://subsonic.org/restapi"

# Subsonic error codes
MISSING_PARAM, WRONG_LOGIN, NOT_AUTHORIZED, NOT_FOUND, GENERIC = 10, 40, 50, 70, 0


class ApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# --- request context -----------------------------------------------------------

class Params:
    """Query string + form body, with repeated keys kept (id=1&id=2)."""

    def __init__(self, pairs: list[tuple[str, str]]):
        self.pairs = pairs

    def get(self, name: str, default: str | None = None) -> str | None:
        return next((v for k, v in self.pairs if k == name), default)

    def all(self, name: str) -> list[str]:
        return [v for k, v in self.pairs if k == name]

    def need(self, name: str) -> str:
        value = self.get(name)
        if value is None or value == "":
            raise ApiError(MISSING_PARAM, f"Required parameter is missing: {name}")
        return value

    def int(self, name: str, default: int, lo: int = 0, hi: int = 10_000) -> int:
        try:
            return max(lo, min(hi, int(self.get(name, default))))
        except (TypeError, ValueError):
            return default

    def flag(self, name: str, default: bool) -> bool:
        value = self.get(name)
        return default if value is None else value.lower() == "true"


class Ctx:
    def __init__(self, params: Params, user: auth.ServerUser | None, lib: Library | None):
        self.p, self.user, self.lib = params, user, lib


def parse_id(text: str, *kinds: str) -> tuple[str, int]:
    """'al-12' -> ('al', 12). Bare numbers are treated as tracks."""
    kind, _, num = text.rpartition("-")
    kind = kind or "tr"
    if kind not in kinds or not num.isdigit():
        raise ApiError(NOT_FOUND, f"Not found: {text}")
    return kind, int(num)


# --- response building ---------------------------------------------------------

def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def song(t) -> dict:
    ext = "." + t["suffix"]
    return _clean({
        "id": f"tr-{t['id']}", "parent": f"al-{t['album_id']}", "isDir": False,
        "title": t["title"], "album": t["album"], "artist": t["artist"],
        "track": t["track_no"], "year": t["year"],
        "coverArt": f"tr-{t['id']}" if t["has_cover"] else None,
        "size": t["size"], "contentType": CONTENT_TYPES.get(ext, "application/octet-stream"),
        "suffix": t["suffix"], "duration": t["duration_s"], "bitRate": t["bitrate_kbps"],
        "path": t["relpath"], "albumId": f"al-{t['album_id']}", "artistId": f"ar-{t['artist_id']}",
        "type": "music", "mediaType": "song", "isVideo": False,
        "playCount": t["play_count"], "played": _iso(t["last_played"]),
        "created": _iso(t["created_at"]), "starred": _iso(t["starred_at"]),
    })


def album(a) -> dict:
    return _clean({
        "id": f"al-{a['id']}", "name": a["name"], "artist": a["artist"],
        "artistId": f"ar-{a['artist_id']}",
        "coverArt": f"al-{a['id']}" if a["cover_track_id"] else None,
        "songCount": a["song_count"], "duration": a["duration"], "year": a["year"],
        "playCount": a["play_count"], "played": _iso(a["last_played"]),
        "created": _iso(a["created_at"]), "starred": _iso(a["starred_at"]),
        # child-style fields, for the older getAlbumList / getMusicDirectory callers
        "parent": f"ar-{a['artist_id']}", "isDir": True, "title": a["name"], "album": a["name"],
    })


def artist(r) -> dict:
    return _clean({
        "id": f"ar-{r['id']}", "name": r["name"], "albumCount": r["album_count"],
        "coverArt": f"ar-{r['id']}" if r["first_album_id"] else None,
        "starred": _iso(r["starred_at"]),
    })


def _index(artists) -> list[dict]:
    groups: dict[str, list] = {}
    for r in artists:
        first = r["name"][:1].upper()
        groups.setdefault(first if first.isalpha() else "#", []).append(artist(r))
    return [{"name": k, "artist": v} for k, v in sorted(groups.items())]


def _xml_value(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


def _to_xml(parent: ET.Element, name: str, value) -> None:
    if isinstance(value, list):
        for item in value:
            _to_xml(parent, name, item)
    elif isinstance(value, dict):
        el = ET.SubElement(parent, name)
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                _to_xml(el, k, v)
            elif v is not None:
                el.set(k, _xml_value(v))
    else:  # list of scalars, e.g. user.folder
        ET.SubElement(parent, name).text = _xml_value(value)


def render(params: Params, payload: dict, status: str = "ok") -> Response:
    envelope = {"status": status, "version": API_VERSION, "type": "dielify",
                "serverVersion": __version__, "openSubsonic": True, **payload}
    if params.get("f", "xml").startswith("json"):
        return JSONResponse({"subsonic-response": envelope})
    root = ET.Element("subsonic-response", {"xmlns": XMLNS})
    for k, v in envelope.items():
        if isinstance(v, (dict, list)):
            _to_xml(root, k, v)
        else:
            root.set(k, _xml_value(v))
    body = b'<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="utf-8")
    return Response(body, media_type="text/xml; charset=utf-8")


def error(params: Params, code: int, message: str) -> Response:
    return render(params, {"error": {"code": code, "message": message}}, status="failed")


# --- handlers ------------------------------------------------------------------

Handler = Callable[[Ctx], "dict | Response"]
HANDLERS: dict[str, Handler] = {}
PUBLIC = {"getOpenSubsonicExtensions"}  # the spec requires this one without login


def api(*names: str):
    def register(fn: Handler) -> Handler:
        for n in names:
            HANDLERS[n] = fn
        return fn
    return register


def _empty(name: str, payload: dict):
    HANDLERS[name] = lambda ctx: payload


# Features later phases may fill in; until then clients get valid empty answers.
for _name, _payload in {
    "getPlaylists": {"playlists": {"playlist": []}},
    "getGenres": {"genres": {"genre": []}},
    "getNowPlaying": {"nowPlaying": {"entry": []}},
    "getArtistInfo": {"artistInfo": {}},
    "getArtistInfo2": {"artistInfo2": {}},
    "getAlbumInfo": {"albumInfo": {}},
    "getAlbumInfo2": {"albumInfo": {}},
    "getSimilarSongs": {"similarSongs": {"song": []}},
    "getSimilarSongs2": {"similarSongs2": {"song": []}},
    "getTopSongs": {"topSongs": {"song": []}},
    "getSongsByGenre": {"songsByGenre": {"song": []}},
    "getLyrics": {"lyrics": {}},
    "getLyricsBySongId": {"lyricsList": {"structuredLyrics": []}},
    "getInternetRadioStations": {"internetRadioStations": {"internetRadioStation": []}},
    "getPodcasts": {"podcasts": {"channel": []}},
    "getNewestPodcasts": {"newestPodcasts": {"episode": []}},
    "getBookmarks": {"bookmarks": {"bookmark": []}},
    "getShares": {"shares": {"share": []}},
    "getVideos": {"videos": {"video": []}},
    "getPlayQueue": {},
    "savePlayQueue": {},
}.items():
    _empty(_name, _payload)


@api("ping")
def ping(ctx: Ctx) -> dict:
    return {}


@api("getLicense")
def get_license(ctx: Ctx) -> dict:
    return {"license": {"valid": True}}


@api("getOpenSubsonicExtensions")
def get_extensions(ctx: Ctx) -> dict:
    return {"openSubsonicExtensions": [{"name": "formPost", "versions": [1]}]}


@api("getUser")
def get_user(ctx: Ctx) -> dict:
    roles = dict(adminRole=False, settingsRole=False, downloadRole=True, uploadRole=False,
                 playlistRole=False, coverArtRole=True, commentRole=False, podcastRole=False,
                 streamRole=True, jukeboxRole=False, shareRole=False, videoConversionRole=False,
                 scrobblingEnabled=True)
    return {"user": {"username": ctx.user.name, **roles, "folder": [1]}}


@api("getMusicFolders")
def get_music_folders(ctx: Ctx) -> dict:
    return {"musicFolders": {"musicFolder": [{"id": 1, "name": ctx.user.profile}]}}


@api("getArtists")
def get_artists(ctx: Ctx) -> dict:
    return {"artists": {"ignoredArticles": "", "index": _index(ctx.lib.artists())}}


@api("getIndexes")
def get_indexes(ctx: Ctx) -> dict:
    return {"indexes": {"lastModified": int(time.time() * 1000), "ignoredArticles": "",
                        "index": _index(ctx.lib.artists())}}


@api("getArtist")
def get_artist(ctx: Ctx) -> dict:
    _, aid = parse_id(ctx.p.need("id"), "ar")
    r = ctx.lib.artist(aid)
    if r is None:
        raise ApiError(NOT_FOUND, "Artist not found")
    return {"artist": {**artist(r), "album": [album(a) for a in ctx.lib.albums_by_artist(aid)]}}


@api("getAlbum")
def get_album(ctx: Ctx) -> dict:
    _, aid = parse_id(ctx.p.need("id"), "al")
    a = ctx.lib.album(aid)
    if a is None:
        raise ApiError(NOT_FOUND, "Album not found")
    return {"album": {**album(a), "song": [song(t) for t in ctx.lib.tracks_on_album(aid)]}}


@api("getSong")
def get_song(ctx: Ctx) -> dict:
    return {"song": song(_track(ctx))}


@api("getMusicDirectory")
def get_music_directory(ctx: Ctx) -> dict:
    kind, num = parse_id(ctx.p.need("id"), "ar", "al")
    if kind == "ar":
        r = ctx.lib.artist(num)
        if r is None:
            raise ApiError(NOT_FOUND, "Artist not found")
        children = [album(a) for a in ctx.lib.albums_by_artist(num)]
        return {"directory": {"id": f"ar-{num}", "name": r["name"], "child": children}}
    a = ctx.lib.album(num)
    if a is None:
        raise ApiError(NOT_FOUND, "Album not found")
    return {"directory": {"id": f"al-{num}", "parent": f"ar-{a['artist_id']}", "name": a["name"],
                          "child": [song(t) for t in ctx.lib.tracks_on_album(num)]}}


@api("getAlbumList2", "getAlbumList")
def get_album_list(ctx: Ctx) -> dict:
    kind = ctx.p.need("type")
    rows = ctx.lib.album_list(kind, ctx.p.int("size", 10, 1, 500), ctx.p.int("offset", 0),
                              ctx.p.int("fromYear", 0, 0, 9999), ctx.p.int("toYear", 9999, 0, 9999))
    key = "albumList2" if ctx.p.get("_method") == "getAlbumList2" else "albumList"
    return {key: {"album": [album(a) for a in rows]}}


@api("getRandomSongs")
def get_random_songs(ctx: Ctx) -> dict:
    return {"randomSongs": {"song": [song(t) for t in ctx.lib.random_tracks(ctx.p.int("size", 10, 1, 500))]}}


@api("search3", "search2")
def search(ctx: Ctx) -> dict:
    p = ctx.p
    artists, albums, songs = ctx.lib.search(
        p.get("query", ""), p.int("artistCount", 20), p.int("artistOffset", 0, 0, 10**9),
        p.int("albumCount", 20), p.int("albumOffset", 0, 0, 10**9),
        p.int("songCount", 20), p.int("songOffset", 0, 0, 10**9))
    key = "searchResult3" if p.get("_method") == "search3" else "searchResult2"
    return {key: {"artist": [artist(r) for r in artists], "album": [album(a) for a in albums],
                  "song": [song(t) for t in songs]}}


@api("getStarred2", "getStarred")
def get_starred(ctx: Ctx) -> dict:
    artists, albums, songs = ctx.lib.starred()
    key = "starred2" if ctx.p.get("_method") == "getStarred2" else "starred"
    return {key: {"artist": [artist(r) for r in artists], "album": [album(a) for a in albums],
                  "song": [song(t) for t in songs]}}


def _star(ctx: Ctx, starred: bool) -> dict:
    tables = {"tr": "tracks", "al": "albums", "ar": "artists"}
    ids = [parse_id(i, "tr", "al", "ar") for i in ctx.p.all("id")]
    ids += [parse_id(i, "al") for i in ctx.p.all("albumId")]
    ids += [parse_id(i, "ar") for i in ctx.p.all("artistId")]
    for kind, num in ids:
        ctx.lib.set_starred(tables[kind], num, starred)
    return {}


@api("star")
def star(ctx: Ctx) -> dict:
    return _star(ctx, True)


@api("unstar")
def unstar(ctx: Ctx) -> dict:
    return _star(ctx, False)


@api("scrobble")
def scrobble(ctx: Ctx) -> dict:
    if not ctx.p.flag("submission", True):
        return {}  # "now playing" notification: nothing to record yet
    times = ctx.p.all("time")
    for i, raw in enumerate(ctx.p.all("id")):
        _, tid = parse_id(raw, "tr")
        when = int(times[i]) / 1000 if i < len(times) and times[i].isdigit() else None
        from . import history
        if ctx.lib.track(tid) is not None:
            history.record(ctx.lib, history.PlayIn(track_id=tid, started_at=when),
                           f"Subsonic ({ctx.user.name})" if ctx.user else "Subsonic")
    return {}


@api("getScanStatus")
def get_scan_status(ctx: Ctx) -> dict:
    return {"scanStatus": {"scanning": False, "count": ctx.lib.stats()["tracks"]}}


@api("startScan")
def start_scan(ctx: Ctx) -> dict:
    ctx.lib.scan()
    return get_scan_status(ctx)


def _track(ctx: Ctx):
    _, tid = parse_id(ctx.p.need("id"), "tr")
    t = ctx.lib.track(tid)
    if t is None:
        raise ApiError(NOT_FOUND, "Song not found")
    return t


@api("stream", "download")
def stream(ctx: Ctx) -> Response:
    # The original file, always: no transcoding (maxBitRate/format are ignored).
    t = _track(ctx)
    path = ctx.lib.path_of(t)
    if not path.exists():
        raise ApiError(NOT_FOUND, "The file is missing; run a library scan")
    media_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    if ctx.p.get("_method") == "download":
        return FileResponse(path, media_type=media_type, filename=path.name)
    return FileResponse(path, media_type=media_type)


@lru_cache(maxsize=256)
def _cover_bytes(path: str, mtime: float, size: int) -> bytes | None:
    data = read_cover(Path(path))
    if not data or not size:
        return data
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if img.width > size:
        img = img.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue()


@api("getCoverArt")
def get_cover_art(ctx: Ctx) -> Response:
    kind, num = parse_id(ctx.p.need("id"), "tr", "al", "ar")
    track_id = num if kind == "tr" else None
    if kind == "ar":
        albums = ctx.lib.albums_by_artist(num)
        track_id = next((a["cover_track_id"] for a in albums if a["cover_track_id"]), None)
    elif kind == "al":
        a = ctx.lib.album(num)
        track_id = a["cover_track_id"] if a else None
    t = ctx.lib.track(track_id) if track_id else None
    path = ctx.lib.path_of(t) if t else None
    if path is None or not path.exists():
        raise ApiError(NOT_FOUND, "No cover art")
    data = _cover_bytes(str(path), path.stat().st_mtime, ctx.p.int("size", 0, 0, 3000))
    if not data:
        raise ApiError(NOT_FOUND, "No cover art")
    return Response(data, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


# --- routing -------------------------------------------------------------------

router = APIRouter()
lockout = auth.Lockout()
SECRET_PARAMS = {"p", "t", "s", "apiKey"}  # never logged


async def _params(request: Request) -> Params:
    pairs = list(request.query_params.multi_items())
    if request.method == "POST":
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("application/x-www-form-urlencoded"):
            pairs += parse_qsl((await request.body()).decode("utf-8"), keep_blank_values=True)
    return Params(pairs)


def _authenticate(params: Params, client: str) -> auth.ServerUser:
    if lockout.is_locked(client):
        raise ApiError(WRONG_LOGIN, "Too many failed logins. Try again in 15 minutes.")
    name = params.get("u")
    if not name:
        raise ApiError(MISSING_PARAM, "Required parameter is missing: u")
    user = auth.get_user(name)
    if user is None or not auth.check_subsonic(user, params.get("p"), params.get("t"), params.get("s")):
        lockout.failed(client)
        reason = "no such user, or its login file can't be read" if user is None else "wrong password"
        log.warning("Failed Subsonic login for user %r from %s (%s)", name, client, reason)
        raise ApiError(WRONG_LOGIN, "Wrong username or password")
    lockout.succeeded(client)
    return user


def _run(handler: Handler, method: str, params: Params, client: str):
    user = lib = None
    if method not in PUBLIC:
        user = _authenticate(params, client)
        s = settings_mod.load()
        lib = Library(user.profile, s.profile_library(user.profile))
    return handler(Ctx(params, user, lib))


@router.api_route("/rest/{method}", methods=["GET", "POST"], include_in_schema=False)
async def dispatch(method: str, request: Request) -> Response:
    params = await _params(request)
    method = method.removesuffix(".view")
    log.info("%s %s", method, " ".join(f"{k}={v!r}" for k, v in params.pairs if k not in SECRET_PARAMS))
    params.pairs.append(("_method", method))
    handler = HANDLERS.get(method)
    try:
        if handler is None:
            raise ApiError(GENERIC, f"Not implemented in Dielify yet: {method}")
        client = request.client.host if request.client else "?"
        # Database, DPAPI and file work happen off the event loop.
        result = await run_in_threadpool(_run, handler, method, params, client)
    except ApiError as e:
        return error(params, e.code, e.message)
    return result if isinstance(result, Response) else render(params, result)
