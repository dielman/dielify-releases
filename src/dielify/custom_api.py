"""Our own API (/api/...): discovery, YouTube search, download requests, settings.

This is the contract for the Android app (Phase 6). The OpenAPI spec FastAPI builds
from these models is published at /api/openapi.json and saved in docs/openapi.json.

Auth: POST /api/auth/login with a server user's name + password returns a token
for that device; send it as "Authorization: Bearer <token>" on every other call.
"""

from __future__ import annotations

import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import auth
from . import settings as settings_mod
from .downloads import DownloadQueue
from .leveller import gain_db
from .library import CONTENT_TYPES, Library, connect, library_for, signin_of
from .yt_adapter import NotSignedIn, Offline, YouTubeError, YTItem, YTMusicAdapter

router = APIRouter(prefix="/api")
lockout = auth.Lockout()
_bearer = HTTPBearer(auto_error=False)

ItemType = Literal["song", "video", "album", "playlist", "artist"]
JobStatus = Literal["queued", "downloading", "processing", "done", "failed", "cancelled"]


# --- models (the API contract) ---------------------------------------------------

class Item(BaseModel):
    type: ItemType
    id: str = Field(description="videoId (song/video), browseId (album), playlistId, or channel id")
    title: str
    artists: list[str] = []
    album: str | None = None
    album_id: str | None = None
    year: str | None = None
    duration_s: int | None = None
    thumbnail: str | None = None
    subtitle: str | None = None
    library_track_id: int | None = Field(None, description="Set when this song is already downloaded")


class Shelf(BaseModel):
    title: str
    items: list[Item]


class HomeFeed(BaseModel):
    shelves: list[Shelf]


class ItemList(BaseModel):
    items: list[Item]


class Charts(BaseModel):
    country: str
    countries: list[str]
    playlists: list[Item]
    artists: list[Item]


class Collection(BaseModel):
    info: Item
    tracks: list[Item]


class DownloadRequest(BaseModel):
    type: Literal["song", "video", "album", "playlist"]
    id: str
    title: str | None = Field(None, description="Shown in the queue until the download starts")
    artists: list[str] = []
    album: str | None = None
    next: bool = Field(False, description="Download before everything else that's waiting")


class Download(BaseModel):
    id: int
    video_id: str
    title: str
    artist: str | None
    album: str | None
    request_id: str
    request_type: str
    request_title: str | None
    next: bool = Field(False, description="Asked to download before the rest of the queue")
    status: JobStatus
    progress: float = Field(description="0.0 to 1.0")
    error: str | None
    attempts: int
    track_id: int | None = Field(description="Library track, once done")
    created_at: float
    updated_at: float


def _download_out(job: dict) -> "Download":
    return Download(**{k: v for k, v in job.items() if k != "priority"}, next=job.get("priority", 0) > 0)


class DownloadList(BaseModel):
    downloads: list[Download]
    active_total: int | None = Field(None, description="All waiting + running downloads (not just this page)")
    seconds_per_song: float | None = Field(None, description="Recent pace, for a time estimate")


class LoginRequest(BaseModel):
    username: str
    password: str
    device_name: str = Field("device", max_length=60)


class LoginResult(BaseModel):
    token: str = Field(description="Send as 'Authorization: Bearer <token>'. Shown only once.")
    device_id: int
    username: str
    profile: str


class NewDevice(BaseModel):
    device_name: str = Field(max_length=60)


class Device(BaseModel):
    id: int
    device_name: str
    created_at: float
    last_used_at: float | None
    current: bool


class DeviceList(BaseModel):
    devices: list[Device]


class SettingsView(BaseModel):
    profile: str
    library_root: str
    quality: str
    preferred_format: str
    cache_limit_gb: float


class SettingsChange(BaseModel):
    quality: Literal["auto", "high", "standard"] | None = None
    preferred_format: Literal["auto", "m4a", "opus"] | None = None
    cache_limit_gb: float | None = Field(None, ge=0)


class Track(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    album_artist: str
    year: int | None
    track_no: int | None
    duration_s: int | None
    bitrate_kbps: int | None
    suffix: str
    content_type: str
    size: int
    video_id: str | None
    play_count: int
    starred: bool
    stream_url: str
    cover_url: str | None
    gain_db: float | None = Field(None, description="Volume levelling: play this song this many dB "
                                                    "louder (negative = quieter). None: not measured yet")


# --- session + YouTube access -----------------------------------------------------

class Session:
    def __init__(self, user: auth.ServerUser, device_id: int, desktop: bool = False):
        self.user, self.device_id, self.desktop = user, device_id, desktop
        self.lib = library_for(user.profile)
        # A kids account (role child) never sees anything from the parent's YouTube account
        # (home feed, charts, YouTube playlists) and can't change settings.
        self.kid = self.lib.role == "child"


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def session(request: Request,
            creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Session:
    client = _client(request)
    if lockout.is_locked(client):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins. Try again later.")
    if creds and auth.is_desktop_token(creds.credentials):
        # the desktop window on this PC: acts for the active profile
        profile = settings_mod.load().active_profile
        return Session(auth.ServerUser("desktop", profile, ""), 0, desktop=True)
    found = auth.check_token(creds.credentials) if creds else None
    if found is None:
        if creds:
            lockout.failed(client)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first (POST /api/auth/login)",
                            headers={"WWW-Authenticate": "Bearer"})
    return Session(*found)


def media_session(request: Request,
                  creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Session:
    """Like `session`, but also accepts ?token=... because audio players and <img>
    tags can't send headers. (Request logs never include query strings.)"""
    if creds is None and request.query_params.get("token"):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=request.query_params["token"])
    return session(request, creds)


class _YouTube:
    """One adapter per YouTube sign-in, one call at a time (keeps traffic human-paced).
    A person uses their store owner's sign-in (a child: the parent's)."""

    def __init__(self):
        self._adapters: dict[str, tuple[YTMusicAdapter, threading.Lock]] = {}
        self._lock = threading.Lock()

    def call(self, profile: str, fn_name: str, *args, **kwargs):
        from . import credstore
        profile = signin_of(profile)
        with self._lock:
            if profile not in self._adapters:
                s = settings_mod.load()
                adapter = YTMusicAdapter(auth=credstore.load(profile), request_delay_s=s.request_delay_s)
                self._adapters[profile] = (adapter, threading.Lock())
            adapter, lock = self._adapters[profile]
        try:
            with lock:
                return getattr(adapter, fn_name)(*args, **kwargs)
        except Offline as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
        except NotSignedIn as e:
            self._adapters.pop(profile, None)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
        except YouTubeError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    def reset(self) -> None:
        with self._lock:
            self._adapters.clear()


youtube = _YouTube()


def desktop_session(s: Session = Depends(session)) -> Session:
    """PC-only actions: only the desktop app's window may do these."""
    if not s.desktop:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Dielify app on the PC can do this")
    return s


def _queue(request: Request) -> DownloadQueue:
    return request.app.state.queue


def _ratings(s: Session):
    from .ratings import Ratings
    return Ratings(s.user.profile)


def _items(items: list[YTItem], lib: Library) -> list[Item]:
    have = lib.video_ids()
    return [Item(**vars(i), library_track_id=have.get(i.id) if i.type in ("song", "video") else None)
            for i in items]


# --- auth -------------------------------------------------------------------------

@router.post("/auth/login", response_model=LoginResult, tags=["auth"])
def login(body: LoginRequest, request: Request) -> LoginResult:
    client = _client(request)
    if lockout.is_locked(client):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins. Try again later.")
    user = auth.get_user(body.username)
    if user is None or not auth.check_subsonic(user, body.password, None, None):
        lockout.failed(client)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    lockout.succeeded(client)
    device_id, token = auth.create_token(user, body.device_name)
    return LoginResult(token=token, device_id=device_id, username=user.name, profile=user.profile)


@router.post("/auth/device-token", response_model=LoginResult, tags=["auth"])
def new_device_token(body: NewDevice, s: Session = Depends(session)) -> LoginResult:
    """A token for another device, created from an already signed-in one."""
    device_id, token = auth.create_token(s.user, body.device_name)
    return LoginResult(token=token, device_id=device_id, username=s.user.name, profile=s.user.profile)


@router.get("/auth/devices", response_model=DeviceList, tags=["auth"])
def devices(s: Session = Depends(session)) -> DeviceList:
    return DeviceList(devices=[Device(**{k: d[k] for k in ("id", "device_name", "created_at",
                                                           "last_used_at")}, current=d["id"] == s.device_id)
                               for d in auth.list_tokens(s.user.name)])


@router.delete("/auth/device-token/{device_id}", status_code=204, tags=["auth"])
def revoke_device(device_id: int, s: Session = Depends(session)) -> Response:
    if not auth.revoke_token(device_id, s.user.name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such device")
    return Response(status_code=204)


# --- discovery + YouTube catalogue ------------------------------------------------

@router.get("/discover/home", response_model=HomeFeed, tags=["discover"])
def discover_home(shelves: int = Query(6, ge=1, le=20), s: Session = Depends(session)) -> HomeFeed:
    """YouTube Music's personalised home feed: mixes, playlists, new releases. Empty for a
    kids account (it's the parent's YouTube)."""
    if s.kid:
        return HomeFeed(shelves=[])
    feed = youtube.call(s.user.profile, "home", shelves)
    r = _ratings(s)
    return HomeFeed(shelves=[Shelf(title=sh.title, items=_items(r.arrange(sh.items), s.lib)) for sh in feed])


@router.get("/discover/similar/{video_id}", response_model=ItemList, tags=["discover"])
def discover_similar(video_id: str, limit: int = Query(25, ge=1, le=50),
                     s: Session = Depends(session)) -> ItemList:
    """Songs like this one (its YouTube Music radio)."""
    return ItemList(items=_items(_ratings(s).arrange(youtube.call(s.user.profile, "similar", video_id, limit)), s.lib))


@router.get("/discover/charts", response_model=Charts, tags=["discover"])
def discover_charts(country: str = Query("ZZ", min_length=2, max_length=2,
                                         description="ISO country code; ZZ = global"),
                    s: Session = Depends(session)) -> Charts:
    if s.kid:  # no YouTube charts in a kids account
        return Charts(country=country.upper(), countries=[], playlists=[], artists=[])
    c = youtube.call(s.user.profile, "charts", country.upper())
    return Charts(country=c["country"], countries=c["countries"],
                  playlists=_items(c["playlists"], s.lib), artists=_items(c["artists"], s.lib))


@router.get("/yt/search", response_model=ItemList, tags=["youtube"])
def yt_search(q: str = Query(min_length=1), type: Literal["song", "video", "album", "playlist", "artist"] = "song",
              limit: int = Query(20, ge=1, le=50), s: Session = Depends(session)) -> ItemList:
    return ItemList(items=_items(youtube.call(s.user.profile, "search_items", q, type, limit), s.lib))


@router.get("/yt/my-playlists", response_model=ItemList, tags=["youtube"])
def yt_my_playlists(s: Session = Depends(session)) -> ItemList:
    """Your own playlists on YouTube Music (open one with /yt/playlist/{id}). Empty for a
    kids account."""
    if s.kid:
        return ItemList(items=[])
    return ItemList(items=_items(youtube.call(s.user.profile, "my_playlists"), s.lib))


@router.get("/yt/stream/{video_id}", tags=["youtube"],
            responses={200: {"content": {"audio/*": {}}}, 206: {"content": {"audio/*": {}}}})
def yt_stream(video_id: str, request: Request, s: Session = Depends(media_session)) -> Response:
    """Play any YouTube song now (relayed by the PC, seeking works). The PC also downloads
    it next in line, so afterwards it plays from your library. A song already in the
    library is served from the file."""
    from . import ytstream
    if not ytstream.VIDEO_ID.match(video_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a YouTube video id")
    have = s.lib.video_ids().get(video_id)
    if have:
        path = s.lib.path_of(_track(s, have))
        if path.exists():
            return FileResponse(path, media_type=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
    cfg = settings_mod.load()
    resolve = lambda: youtube.call(s.user.profile, "stream_info", video_id, cfg.quality, cfg.preferred_format)
    info = ytstream.cache.get(s.user.profile, video_id, resolve)
    range_header = request.headers.get("range")
    if not range_header or range_header.startswith("bytes=0-"):
        # first request for this song: keep it (download next in line)
        _queue(request).enqueue(s.user.profile, [YTItem("song", video_id, info.title,
                                                        [info.artist] if info.artist else [], info.album)],
                                "song", info.title, s.user.name, next_up=True)
    try:
        upstream = ytstream.open_upstream(info, range_header)
        if upstream.status_code in (403, 410):  # address expired: ask YouTube again, once
            upstream.close()
            info = ytstream.cache.get(s.user.profile, video_id, resolve, fresh=True)
            upstream = ytstream.open_upstream(info, range_header)
    except ytstream.requests.RequestException as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"YouTube didn't answer: {e}") from e
    if upstream.status_code not in (200, 206):
        upstream.close()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"YouTube answered HTTP {upstream.status_code}")
    code, headers, body = ytstream.relay(upstream)
    return StreamingResponse(body, status_code=code, media_type=info.mime, headers=headers)


@router.get("/yt/album/{browse_id}", response_model=Collection, tags=["youtube"])
def yt_album(browse_id: str, s: Session = Depends(session)) -> Collection:
    info, tracks = youtube.call(s.user.profile, "album", browse_id)
    return Collection(info=_items([info], s.lib)[0], tracks=_items(tracks, s.lib))


@router.get("/yt/playlist/{playlist_id}", response_model=Collection, tags=["youtube"])
def yt_playlist(playlist_id: str, limit: int = Query(5000, ge=1, le=5000),
                s: Session = Depends(session)) -> Collection:
    info, tracks = youtube.call(s.user.profile, "playlist", playlist_id, limit)
    return Collection(info=_items([info], s.lib)[0], tracks=_items(tracks, s.lib))


# --- download requests ------------------------------------------------------------

@router.post("/downloads", response_model=DownloadList, status_code=202, tags=["downloads"])
def request_download(body: DownloadRequest, request: Request, s: Session = Depends(session)) -> DownloadList:
    """Queue a song, video, whole album or playlist. Returns one job per track; tracks
    already in the library come back as 'done' straight away."""
    if body.type in ("song", "video"):
        items = [YTItem(body.type, body.id, body.title or body.id, body.artists, body.album)]
        title = body.title
    else:
        info, items = youtube.call(s.user.profile, body.type, body.id)
        title = info.title
        if not items:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No downloadable tracks in that {body.type}")
    jobs = _queue(request).enqueue(s.user.profile, items, body.type, title, s.user.name,
                                   next_up=body.next)
    return DownloadList(downloads=[_download_out(j) for j in jobs])


@router.get("/downloads", response_model=DownloadList, tags=["downloads"])
def list_downloads(request: Request, active: bool = False, finished: bool = False,
                   limit: int = Query(200, ge=1, le=1000), s: Session = Depends(session)) -> DownloadList:
    """active=true: running + waiting, in the order they'll download. finished=true:
    done/failed/cancelled, newest first. Neither: everything, newest first.
    Poll every second or two to show progress."""
    q = _queue(request)
    summary = q.summary(s.user.profile)
    return DownloadList(downloads=[_download_out(j) for j in q.list(s.user.profile, active, limit, finished)],
                        active_total=summary["active"], seconds_per_song=summary["seconds_per_song"])


@router.get("/downloads/{job_id}", response_model=Download, tags=["downloads"])
def get_download(job_id: int, request: Request, s: Session = Depends(session)) -> Download:
    job = _queue(request).get(s.user.profile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such download")
    return _download_out(job)


@router.post("/downloads/{job_id}/next", response_model=Download, tags=["downloads"])
def download_next(job_id: int, request: Request, s: Session = Depends(session)) -> Download:
    """Move a waiting download to the front of the line."""
    job = _queue(request).move_next(s.user.profile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such download")
    return _download_out(job)


class Cleared(BaseModel):
    removed: int


@router.post("/downloads/clear-finished", response_model=Cleared, tags=["downloads"])
def clear_finished_downloads(request: Request, s: Session = Depends(session)) -> Cleared:
    """Remove downloaded and cancelled songs from the list. The songs stay in the library;
    failed downloads stay listed."""
    return Cleared(removed=_queue(request).clear_finished(s.user.profile))


@router.delete("/downloads/{job_id}", response_model=Download, tags=["downloads"])
def cancel_download(job_id: int, request: Request, s: Session = Depends(session)) -> Download:
    """Cancel a queued or running download. Finished ones are left as they are."""
    job = _queue(request).cancel(s.user.profile, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such download")
    return _download_out(job)


# --- library (play what was downloaded) ---------------------------------------------

def _track(s: Session, track_id: int):
    t = s.lib.track(track_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such track")
    return t


class Artist(BaseModel):
    id: int
    name: str
    album_count: int
    cover_url: str | None
    starred: bool


class Album(BaseModel):
    id: int
    name: str
    artist: str
    artist_id: int
    year: int | None
    song_count: int
    duration_s: int
    play_count: int
    cover_url: str | None
    starred: bool
    created_at: float


class ArtistList(BaseModel):
    artists: list[Artist]


class ArtistDetail(BaseModel):
    artist: Artist
    albums: list[Album]


class AlbumList(BaseModel):
    albums: list[Album]


class AlbumDetail(BaseModel):
    album: Album
    tracks: list[Track]


class TrackList(BaseModel):
    tracks: list[Track]


class AddSongs(BaseModel):
    track_ids: list[int] = Field(min_length=1, max_length=2000)


class Added(BaseModel):
    added: int = Field(description="How many were new to your library")


class Me(BaseModel):
    username: str
    profile: str
    role: Literal["parent", "child"]
    household: list[str] = Field(description="Everyone sharing this music store")


class LibrarySearch(BaseModel):
    artists: list[Artist]
    albums: list[Album]
    tracks: list[Track]


class StarChange(BaseModel):
    starred: bool


def _track_out(t) -> Track:
    return Track(id=t["id"], title=t["title"], artist=t["artist"], album=t["album"],
                 album_artist=t["album_artist"], year=t["year"], track_no=t["track_no"],
                 duration_s=t["duration_s"], bitrate_kbps=t["bitrate_kbps"], suffix=t["suffix"],
                 content_type=CONTENT_TYPES.get("." + t["suffix"], "application/octet-stream"),
                 size=t["size"], video_id=t["video_id"], play_count=t["play_count"],
                 starred=t["starred_at"] is not None,
                 stream_url=f"/api/library/tracks/{t['id']}/stream",
                 cover_url=f"/api/library/tracks/{t['id']}/cover" if t["has_cover"] else None,
                 gain_db=gain_db(t["loudness"]) if "loudness" in t.keys() else None)


def _album_out(a) -> Album:
    return Album(id=a["id"], name=a["name"], artist=a["artist"], artist_id=a["artist_id"],
                 year=a["year"], song_count=a["song_count"], duration_s=a["duration"] or 0,
                 play_count=a["play_count"],
                 cover_url=f"/api/library/albums/{a['id']}/cover" if a["cover_track_id"] else None,
                 starred=a["starred_at"] is not None, created_at=a["created_at"])


def _artist_out(r) -> Artist:
    cover = f"/api/library/albums/{r['first_album_id']}/cover" if r["first_album_id"] else None
    return Artist(id=r["id"], name=r["name"], album_count=r["album_count"], cover_url=cover,
                  starred=r["starred_at"] is not None)




@router.get("/library/artists", response_model=ArtistList, tags=["library"])
def library_artists(s: Session = Depends(session)) -> ArtistList:
    return ArtistList(artists=[_artist_out(r) for r in s.lib.artists()])


@router.get("/library/artists/{artist_id}", response_model=ArtistDetail, tags=["library"])
def library_artist(artist_id: int, s: Session = Depends(session)) -> ArtistDetail:
    r = s.lib.artist(artist_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such artist")
    return ArtistDetail(artist=_artist_out(r),
                        albums=[_album_out(a) for a in s.lib.albums_by_artist(artist_id)])


@router.get("/library/albums", response_model=AlbumList, tags=["library"])
def library_albums(sort: Literal["newest", "alphabeticalByName", "alphabeticalByArtist", "frequent",
                                 "recent", "starred", "random"] = "newest",
                   limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                   s: Session = Depends(session)) -> AlbumList:
    return AlbumList(albums=[_album_out(a) for a in s.lib.album_list(sort, limit, offset)])


@router.get("/library/albums/{album_id}", response_model=AlbumDetail, tags=["library"])
def library_album(album_id: int, s: Session = Depends(session)) -> AlbumDetail:
    a = s.lib.album(album_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such album")
    return AlbumDetail(album=_album_out(a), tracks=[_track_out(t) for t in s.lib.tracks_on_album(album_id)])


@router.get("/library/search", response_model=LibrarySearch, tags=["library"])
def library_search(q: str = "", limit: int = Query(30, ge=1, le=500),
                   s: Session = Depends(session)) -> LibrarySearch:
    artists, albums, tracks = s.lib.search(q, limit, 0, limit, 0, limit, 0)
    return LibrarySearch(artists=[_artist_out(r) for r in artists],
                         albums=[_album_out(a) for a in albums],
                         tracks=[_track_out(t) for t in tracks])


@router.get("/library/tracks/{track_id}", response_model=Track, tags=["library"])
def library_track(track_id: int, s: Session = Depends(session)) -> Track:
    return _track_out(_track(s, track_id))


@router.put("/library/tracks/{track_id}/star", response_model=Track, tags=["library"])
def library_star(track_id: int, body: StarChange, s: Session = Depends(session)) -> Track:
    _track(s, track_id)
    s.lib.set_starred("tracks", track_id, body.starred)
    return _track_out(_track(s, track_id))


@router.post("/library/tracks/{track_id}/played", status_code=204, tags=["library"])
def library_played(track_id: int, s: Session = Depends(session)) -> Response:
    """Older way to say a track was listened to; POST /api/plays says how much."""
    from . import history
    _track(s, track_id)
    history.record(s.lib, history.PlayIn(track_id=track_id), _device_name(s))
    return Response(status_code=204)


# --- play history + stats ------------------------------------------------------------

class PlayReport(BaseModel):
    track_id: int | None = None
    video_id: str | None = Field(None, max_length=20)
    title: str | None = Field(None, max_length=300)
    artist: str | None = Field(None, max_length=300)
    album: str | None = Field(None, max_length=300)
    duration_s: int | None = Field(None, ge=0)
    played_s: int | None = Field(None, ge=0, description="Seconds actually heard (skips count too)")
    started_at: float | None = Field(None, description="Unix time; default now")
    client_id: str | None = Field(None, max_length=64, description="Unique per play, so resending is safe")


class PlayBatch(BaseModel):
    plays: list[PlayReport] = Field(max_length=500)


class PlaysRecorded(BaseModel):
    recorded: int
    duplicates: int


def _device_name(s: Session) -> str:
    if s.desktop:
        return "PC"
    for d in auth.list_tokens(s.user.name):
        if d["id"] == s.device_id:
            return d["device_name"]
    return s.user.name


@router.post("/plays", response_model=PlaysRecorded, tags=["stats"])
def report_plays(body: PlayBatch, s: Session = Depends(session)) -> PlaysRecorded:
    """Report plays (when, how much was heard). A play counts once you've heard half the
    song or 4 minutes; shorter ones are kept as skips."""
    from . import history
    device, new, dup = _device_name(s), 0, 0
    for p in body.plays:
        try:
            if history.record(s.lib, history.PlayIn(**p.model_dump()), device):
                new += 1
            else:
                dup += 1
        except ValueError:
            dup += 1  # nothing to identify the song: skip it rather than fail the batch
    return PlaysRecorded(recorded=new, duplicates=dup)


class StatSong(BaseModel):
    title: str
    artist: str | None
    album: str | None
    plays: int
    minutes: int
    track_id: int | None
    video_id: str | None
    cover_url: str | None = Field(None, description="From the library (needs the token)")
    thumbnail: str | None = Field(None, description="From YouTube")


class StatArtist(BaseModel):
    name: str
    plays: int
    minutes: int
    cover_url: str | None
    artist_id: int | None = None


class StatAlbum(BaseModel):
    name: str
    artist: str | None
    plays: int
    cover_url: str | None
    album_id: int | None = None


class Stats(BaseModel):
    period: Literal["week", "month", "year", "all"]
    since: float | None
    history_starts: float | None = Field(description="When play history began (None = no plays yet)")
    plays: int
    minutes: int
    songs: int
    artists: int
    skips: int
    by_hour: list[int] = Field(description="Plays per hour of the day, 0-23, local time")
    top_songs: list[StatSong]
    top_artists: list[StatArtist]
    top_albums: list[StatAlbum]


def _thumb(video_id: str | None) -> str | None:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


@router.get("/stats", response_model=Stats, tags=["stats"])
def get_stats(period: Literal["week", "month", "year", "all"] = "month",
              limit: int = Query(10, ge=1, le=50), s: Session = Depends(session)) -> Stats:
    from . import history
    st = history.stats(s.lib, period, limit)
    tracks = {}

    def track(tid):
        if tid and tid not in tracks:
            tracks[tid] = s.lib.track(tid)
        return tracks.get(tid)

    def cover(tid):
        t = track(tid)
        return f"/api/library/tracks/{tid}/cover" if t is not None and t["has_cover"] else None

    songs = [StatSong(title=r["title"], artist=r["artist"], album=r["album"], plays=r["plays"],
                      minutes=round((r["secs"] or 0) / 60), track_id=r["track_id"] if track(r["track_id"]) else None,
                      video_id=r["video_id"], cover_url=cover(r["track_id"]), thumbnail=_thumb(r["video_id"]))
             for r in st["top_songs"]]
    artists = []
    for r in st["top_artists"]:
        t = track(r["track_id"])
        artists.append(StatArtist(name=r["name"], plays=r["plays"], minutes=round((r["secs"] or 0) / 60),
                                  cover_url=cover(r["track_id"]), artist_id=t["artist_id"] if t is not None else None))
    albums = []
    for r in st["top_albums"]:
        t = track(r["track_id"])
        albums.append(StatAlbum(name=r["name"], artist=r["artist"], plays=r["plays"], cover_url=cover(r["track_id"]),
                                album_id=t["album_id"] if t is not None else None))
    return Stats(**{k: st[k] for k in ("period", "since", "history_starts", "plays", "minutes", "songs",
                                         "artists", "skips", "by_hour")},
                 top_songs=songs, top_artists=artists, top_albums=albums)


# --- ratings: thumbs up / down / ban --------------------------------------------------

class Rating(BaseModel):
    kind: Literal["song", "artist"]
    key: str
    name: str
    value: int = Field(description="1 up, -1 down, -2 banned")
    updated_at: float


class RatingList(BaseModel):
    ratings: list[Rating]
    removed: str | None = Field(None, description="Thumbs down on a song discovery play brought in: "
                                                  "its title (its download was deleted from the PC)")


class RatingIn(BaseModel):
    kind: Literal["song", "artist"]
    name: str = Field(max_length=300, description='song: "Title - Artist"; artist: its name')
    video_id: str | None = None
    track_id: int | None = None
    value: int = Field(ge=-2, le=1, description="1 up, -1 down, -2 ban, 0 clear")


@router.get("/ratings", response_model=RatingList, tags=["ratings"])
def get_ratings(s: Session = Depends(session)) -> RatingList:
    from . import ratings
    return RatingList(ratings=[Rating(**r) for r in ratings.listing(s.user.profile)])


@router.put("/ratings", response_model=RatingList, tags=["ratings"])
def put_rating(body: RatingIn, request: Request, s: Session = Depends(session)) -> RatingList:
    """Thumbs up (1), down (-1), ban (-2) or clear (0) a song or an artist. Returns all."""
    from . import ratings
    if body.kind == "artist":
        key = ratings.artist_key(body.name)
    else:
        key = ratings.song_key(body.video_id, body.track_id)
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Which song? (video_id or track_id)")
    ratings.set_rating(s.user.profile, body.kind, key, body.name.strip(), body.value)
    out = get_ratings(s)
    if body.kind == "song" and body.value in (ratings.DOWN, ratings.BAN):
        from . import explore
        out.removed = explore.disliked(s.user.profile, s.lib, _queue(request), body.video_id, body.track_id)
    return out


class LyricLine(BaseModel):
    ms: int = Field(description="When the line starts, from the start of the song")
    text: str


class Lyrics(BaseModel):
    synced: bool = Field(description="lines have times (scroll along with the song)")
    lines: list[LyricLine] = Field(description="Empty when not synced: show `text`")
    text: str
    source: str | None = None


@router.get("/lyrics", response_model=Lyrics, tags=["library"],
            responses={404: {"description": "No lyrics for this song"}})
def get_lyrics(video_id: str | None = Query(None, max_length=64), track_id: int | None = None,
               title: str | None = Query(None, max_length=300), artist: str | None = Query(None, max_length=300),
               album: str | None = Query(None, max_length=300), duration_s: int | None = Query(None, ge=0, le=36000),
               s: Session = Depends(session)) -> Lyrics:
    """The song's lyrics (YouTube Music, else LRCLIB), synced when possible. Kept on the PC,
    so songs looked up before (and every downloaded song) have them offline. A YouTube song
    that isn't in the library: pass video_id plus title / artist."""
    from . import lyrics
    t = s.lib.track(track_id) if track_id else (s.lib.track_by_video(video_id) if video_id else None)
    if t is not None:
        video_id = video_id or t["video_id"]
        title, artist, album, duration_s = t["title"], t["artist"], t["album"], t["duration_s"]
    key = lyrics.key_of(video_id, t["id"] if t is not None else track_id)
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Which song? (video_id or track_id)")
    if settings_mod.load().offline:
        found = lyrics.cached(key)[1]
    else:
        yt = (lambda: youtube.call(s.user.profile, "lyrics", video_id)) if video_id else None
        found = lyrics.find(key, yt, artist, title, album, duration_s)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No lyrics for this song")
    lines = [LyricLine(ms=ms, text=txt) for ms, txt in (found["lines"] or [])]
    return Lyrics(synced=bool(lines), lines=lines, text=found["text"], source=found.get("source"))


@router.get("/keep", response_model=TrackList, tags=["library"])
def keep_on_phone(liked: bool = False, top: int = Query(0, ge=0, le=500),
                  playlists: str = Query("", max_length=2000, description="Dielify playlist ids, comma-separated"),
                  s: Session = Depends(session)) -> TrackList:
    """Songs a phone keeps saved automatically: your thumbs-up songs, your most played (last
    30 days), and the downloaded songs of chosen playlists. Library songs only."""
    from . import history
    ids: list[int] = []
    have = s.lib.video_ids()
    with connect() as conn:
        if liked:
            for r in conn.execute("SELECT key FROM ratings WHERE profile = ? AND kind = 'song' AND value = 1",
                                  (s.user.profile,)):
                k = r["key"]
                tid = int(k[3:]) if k.startswith("tr-") and k[3:].isdigit() else have.get(k)
                if tid:
                    ids.append(tid)
        wanted = [int(x) for x in playlists.split(",") if x.strip().isdigit()][:100]
        for pid in wanted:
            rows = conn.execute("SELECT i.video_id FROM playlist_items i JOIN playlists p ON p.id = i.playlist_id "
                                "WHERE p.id = ? AND p.profile = ? ORDER BY i.position", (pid, s.user.profile))
            ids += [have[r["video_id"]] for r in rows if r["video_id"] in have]
    if top:
        ids += history.on_repeat(s.lib, days=30, limit=top)
    tracks = [t for t in (s.lib.track(i) for i in dict.fromkeys(ids)) if t is not None]
    return TrackList(tracks=[_track_out(t) for t in tracks])


class EndlessIn(BaseModel):
    seeds: list[str] = Field([], max_length=50,
                             description="Video ids heard so far in this list, oldest first (thumbs-up ones count most)")
    exclude: list[str] = Field([], max_length=2000, description="Video ids already in the list")
    count: int = Field(10, ge=1, le=25)


@router.post("/discover/endless", response_model=ItemList, tags=["discover"])
def discover_endless(body: EndlessIn, request: Request, s: Session = Depends(session)) -> ItemList:
    """Never-ending discovery play: the next songs that aren't in your library yet, like
    the seeds. They're queued for download so you can check them out; thumbs down on one
    (PUT /ratings) deletes it from the PC again."""
    from . import explore, history
    r = _ratings(s)
    liked = [v for v in body.seeds if r.songs.get(v) == 1]
    seeds = [v for v in body.seeds if v not in liked] + liked  # newest last; liked ones go first
    # nothing heard yet: your most-played songs lately, else a few random library songs
    fallback = history.seeds(s.lib) or [t["video_id"] for t in s.lib.random_tracks(20) if t["video_id"]][:4]
    items = explore.next_songs(s.lib, r, lambda vid, n: youtube.call(s.user.profile, "similar", vid, n),
                               seeds, set(body.exclude) | set(body.seeds), fallback, body.count)
    if items:
        explore.remember(s.user.profile, items)
        _queue(request).enqueue(s.user.profile, items, "discovery", "Discovery play", s.user.name)
    return ItemList(items=_items(items, s.lib))


class OutsideShelf(BaseModel):
    key: str
    title: str
    subtitle: str | None
    items: list[Item]
    updated_at: float


class OutsideDiscovery(BaseModel):
    shelves: list[OutsideShelf]


@router.get("/discover/outside", response_model=OutsideDiscovery, tags=["discover"])
def discover_outside(s: Session = Depends(session)) -> OutsideDiscovery:
    """Radio charts (triple j, Double J, Unearthed) and ListenBrainz (trending, artists like
    yours), matched on YouTube Music. Rebuilt daily on the PC."""
    from . import discovery
    return OutsideDiscovery(shelves=[OutsideShelf(key=l["key"], title=l["title"], subtitle=l["subtitle"],
                                                  items=_items(l["items"], s.lib), updated_at=l["updated_at"])
                                     for l in discovery.lists(s.user.profile)])


@router.post("/discover/outside/refresh", status_code=202, tags=["discover"])
def refresh_outside(request: Request, s: Session = Depends(session)) -> Response:
    request.app.state.discovery.refresh_soon()
    return Response(status_code=202)


class ForYou(BaseModel):
    on_repeat: list[Track] = Field(description="Your songs you've played most in the last 2 weeks")
    forgotten: list[Track] = Field(description="Songs you played a lot, but not for 2 months")
    more_like: list[Item] = Field(description="New to you: like your most-played songs (from YouTube Music)")


@router.get("/discover/for-you", response_model=ForYou, tags=["discover"])
def discover_for_you(s: Session = Depends(session)) -> ForYou:
    from . import history, ratings
    r = _ratings(s)
    ok = lambda t: t is not None and r.value(t["video_id"], t["artist"], t["id"]) != ratings.BAN  # noqa: E731
    on_repeat = [_track_out(t) for t in map(s.lib.track, history.on_repeat(s.lib)) if ok(t)]
    forgotten = [_track_out(t) for t in map(s.lib.track, history.forgotten(s.lib)) if ok(t)]
    have, seen, more = s.lib.video_ids(), set(), []
    for vid in history.seeds(s.lib):
        try:
            similar = youtube.call(s.user.profile, "similar", vid, 12)
        except HTTPException:
            continue  # offline / signed out: the library lists still work
        for it in similar:
            if it.id not in have and it.id not in seen:
                seen.add(it.id)
                more.append(it)
    return ForYou(on_repeat=on_repeat, forgotten=forgotten, more_like=_items(r.arrange(more)[:40], s.lib))


@router.get("/me", response_model=Me, tags=["auth"])
def me(s: Session = Depends(session)) -> Me:
    from .library import people
    return Me(username=s.user.name, profile=s.lib.profile, role=s.lib.role,
              household=[p["profile"] for p in people() if p["store"] == s.lib.store])


@router.get("/library/household", response_model=TrackList, tags=["library"])
def library_household(q: str = "", limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                      s: Session = Depends(session)) -> TrackList:
    """Songs already on the PC that aren't in your library (someone else in the household
    has them). Add them with POST /library/add: no download needed."""
    return TrackList(tracks=[_track_out(t) for t in s.lib.household(q, limit, offset)])


@router.post("/library/add", response_model=Added, tags=["library"])
def library_add(body: AddSongs, s: Session = Depends(session)) -> Added:
    """Add songs that are already on the PC to your library."""
    return Added(added=s.lib.add_many(body.track_ids, "household"))


@router.get("/library/tracks/{track_id}/stream", tags=["library"],
            response_class=FileResponse, responses={200: {"content": {"audio/*": {}}}})
def library_stream(track_id: int, s: Session = Depends(media_session)) -> FileResponse:
    """The original file (supports Range requests for seeking). Also plays songs on the
    Household shelf (in your household's store, not yet in your library)."""
    t = s.lib.track(track_id) or s.lib.household_track(track_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such track")
    path = s.lib.path_of(t)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing; run a library scan")
    return FileResponse(path, media_type=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))


def _cover_response(s: Session, track_id: int | None, size: int) -> Response:
    from .subsonic_api import _cover_bytes
    t = (s.lib.track(track_id) or s.lib.household_track(track_id)) if track_id else None
    path = s.lib.path_of(t) if t else None
    data = _cover_bytes(str(path), path.stat().st_mtime, size) if path and path.exists() else None
    if not data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cover art")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/library/tracks/{track_id}/cover", tags=["library"],
            responses={200: {"content": {"image/jpeg": {}}}})
def library_cover(track_id: int, size: int = Query(0, ge=0, le=3000),
                  s: Session = Depends(media_session)) -> Response:
    return _cover_response(s, track_id, size)


@router.get("/library/albums/{album_id}/cover", tags=["library"],
            responses={200: {"content": {"image/jpeg": {}}}})
def library_album_cover(album_id: int, size: int = Query(0, ge=0, le=3000),
                        s: Session = Depends(media_session)) -> Response:
    a = s.lib.album(album_id)
    return _cover_response(s, a["cover_track_id"] if a else None, size)


# --- settings -------------------------------------------------------------------------

def _settings_view(s: Session) -> SettingsView:
    cfg = settings_mod.load()
    return SettingsView(profile=s.user.profile, library_root=cfg.library_root, quality=cfg.quality,
                        preferred_format=cfg.preferred_format, cache_limit_gb=cfg.cache_limit_gb)


@router.get("/settings", response_model=SettingsView, tags=["settings"])
def get_settings(s: Session = Depends(session)) -> SettingsView:
    return _settings_view(s)


@router.put("/settings", response_model=SettingsView, tags=["settings"])
def put_settings(body: SettingsChange, s: Session = Depends(session)) -> SettingsView:
    """Audio quality, format and cache limit. The music folder is changed on the PC only.
    Not from a kids account."""
    if s.kid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ask a parent to change this on the PC")
    for key, value in body.model_dump(exclude_none=True).items():
        settings_mod.set_value(key, str(value))
    return _settings_view(s)
