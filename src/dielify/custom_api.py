"""Our own API (/api/...): discovery, YouTube search, download requests, settings.

This is the contract for the Android app (Phase 6). The OpenAPI spec FastAPI builds
from these models is published at /api/openapi.json and saved in docs/openapi.json.

Auth: POST /api/auth/login with a server user's name + password returns a token
for that device; send it as "Authorization: Bearer <token>" on every other call.
"""

from __future__ import annotations

import logging
import threading
import time
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
from .yt_adapter import SONG_MIX, NotSignedIn, Offline, YouTubeError, YTItem, YTMusicAdapter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
lockout = auth.Lockout()
_bearer = HTTPBearer(auto_error=False)

ItemType = Literal["song", "video", "album", "playlist", "artist"]
JobStatus = Literal["approval", "queued", "downloading", "processing", "done", "failed", "cancelled"]


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
    explicit: bool | None = Field(None, description="YouTube's explicit mark (None: not given)")


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
    colors: ArtColors | None = Field(None, description="From its album's cover")


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
    if creds is not None and creds.credentials.startswith(auth.CAST_PREFIX):  # a speaker: play only
        found = auth.check_cast_token(creds.credentials)
        if found is None:
            lockout.failed(_client(request))
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This cast link has run out: cast again from the phone")
        return Session(*found)
    return session(request, creds)


class _YouTube:
    """One adapter per YouTube sign-in, one call at a time (keeps traffic human-paced).
    A person uses their store owner's sign-in (a child: the parent's)."""

    def __init__(self):
        self._adapters: dict[str, tuple[YTMusicAdapter, threading.Lock]] = {}
        self._lock = threading.Lock()
        self._last_person = 0.0  # when someone (not a background job) last asked YouTube

    def background(self, profile: str, fn_name: str, *args, **kwargs):
        """For background jobs (the kids' explicit check): waits until nobody has asked
        YouTube for 3 seconds, so people never queue behind it."""
        while time.monotonic() - self._last_person < 3:
            time.sleep(0.5)
        return self.call(profile, fn_name, *args, _background=True, **kwargs)

    def call(self, profile: str, fn_name: str, *args, _background: bool = False, **kwargs):
        from . import credstore
        if not _background:
            self._last_person = time.monotonic()
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


def _items(items: list[YTItem], lib: Library, lookups: int = 0) -> list[Item]:
    """API items, marked "in your library". For a kids account, filtered by the parent's
    controls (kids.py); `lookups` = how many unmarked songs it may check with YouTube."""
    from . import kids
    kids.remember(items)
    if lib.role == "child":
        items = _kid_filter(lib, lookups).items(items)
    have = lib.video_ids()
    return [Item(**vars(i), library_track_id=have.get(i.id) if i.type in ("song", "video") else None)
            for i in items]


def _kid_filter(lib: Library, lookups: int = 0):
    from . import kids
    return kids.KidFilter(lib.profile, lambda fn, *a: youtube.call(lib.profile, fn, *a), lookups)


def _kid_controls(s: "Session"):
    from . import kids
    return kids.load(s.lib.profile) if s.kid else None


def _quiet(s: "Session") -> None:
    """Quiet hours a parent set for a kids account: no music until they end."""
    from . import kids
    c = _kid_controls(s)
    msg = kids.quiet_message(c) if c else None
    if msg:
        raise HTTPException(status.HTTP_403_FORBIDDEN, msg)


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

_last_home: dict[str, list] = {}


@router.get("/discover/home", response_model=HomeFeed, tags=["discover"])
def discover_home(shelves: int = Query(6, ge=1, le=20), s: Session = Depends(session)) -> HomeFeed:
    """YouTube Music's personalised home feed: mixes, playlists, new releases. Empty for a
    kids account (it's the parent's YouTube)."""
    if s.kid:  # Dielify's own Kids discovery instead
        from . import kids_home
        return HomeFeed(shelves=[Shelf(title=sh.title, items=_items(sh.items, s.lib))
                                 for sh in kids_home.shelves(s.lib, lambda fn, *a: youtube.call(s.lib.profile, fn, *a))])
    try:
        feed = youtube.call(s.user.profile, "home", shelves)
        _last_home[s.user.profile.lower()] = feed
    except HTTPException as e:
        if e.status_code != status.HTTP_502_BAD_GATEWAY:
            raise
        # YouTube hiccup: show the last home feed that loaded (this run of the server)
        feed = _last_home.get(s.user.profile.lower())
        if feed is None:
            raise
        log.warning("Home feed failed for %s; showing the last one that loaded", s.user.profile)
    r = _ratings(s)
    return HomeFeed(shelves=[Shelf(title=sh.title, items=_items(r.arrange(sh.items), s.lib)) for sh in feed])


@router.get("/discover/similar/{video_id}", response_model=ItemList, tags=["discover"])
def discover_similar(video_id: str, limit: int = Query(25, ge=1, le=50),
                     s: Session = Depends(session)) -> ItemList:
    """Songs like this one (its YouTube Music radio)."""
    if s.kid:  # radio songs carry no explicit mark: fetch more, check some, keep what passes
        found = youtube.call(s.user.profile, "similar", video_id, min(50, limit * 2))
        return ItemList(items=_items(_ratings(s).arrange(found), s.lib)[:limit])
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
    c = _kid_controls(s)
    if c and not c.youtube_search:
        return ItemList(items=[])  # a parent turned YouTube search off for this account
    # songs and albums come with YouTube's explicit mark; videos don't, so a few are checked
    return ItemList(items=_items(youtube.call(s.user.profile, "search_items", q, type, limit), s.lib, lookups=2))


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
    _quiet(s)
    have = s.lib.video_ids().get(video_id)
    if not have and s.kid:  # already on the PC for someone else: play the file (if she may)
        t = s.lib.store_track_by_video(video_id)
        if t is not None and _kid_filter(s.lib).tracks([t]):
            path = s.lib.path_of(t)
            if path.exists():
                return FileResponse(path, media_type=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
    if have:
        path = s.lib.path_of(_track(s, have))
        if path.exists():
            return FileResponse(path, media_type=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
    cfg = settings_mod.load()
    resolve = lambda: youtube.call(s.user.profile, "stream_info", video_id, cfg.quality, cfg.preferred_format)
    info = ytstream.cache.get(s.user.profile, video_id, resolve)
    if s.kid:
        reason = _kid_filter(s.lib, lookups=1).why_not(video_id, info.title, [info.artist] if info.artist else [])
        if reason:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Not available in your account ({reason})")
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
    return _collection(s, info, tracks)


@router.get("/yt/playlist/{playlist_id}", response_model=Collection, tags=["youtube"])
def yt_playlist(playlist_id: str, limit: int = Query(5000, ge=1, le=5000),
                s: Session = Depends(session)) -> Collection:
    info, tracks = youtube.call(s.user.profile, "playlist", playlist_id, limit)
    return _collection(s, info, tracks)


def _collection(s: Session, info: YTItem, tracks: list[YTItem]) -> Collection:
    head = _items([info], s.lib)
    if not head:  # e.g. an explicit album, for a kids account
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available in your account")
    return Collection(info=head[0], tracks=_items(tracks, s.lib))


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


class ArtColors(BaseModel):
    bg: str = Field(description="A dark colour from the artwork, for page backgrounds (#rrggbb)")
    accent: str = Field(description="Its liveliest colour, readable on bg")
    fg: str = Field(description="Text colour on bg")


def _colours(key: str | None) -> ArtColors | None:
    from . import artwork
    c = artwork.colours(key) if key else None
    return ArtColors(**c) if c else None


class Artist(BaseModel):
    id: int
    name: str
    album_count: int
    cover_url: str | None
    starred: bool
    image_url: str | None = Field(None, description="The artist's photo (YouTube Music), else an album cover")
    colors: ArtColors | None = None


class Album(BaseModel):
    id: int
    name: str
    artist: str
    artist_id: int
    year: int | None
    song_count: int
    duration_s: int
    play_count: int
    cover_url: str | None = Field(description="Always set: the album's cover, or a generated one")
    starred: bool
    created_at: float
    colors: ArtColors | None = Field(None, description="From the cover (None: not worked out yet)")


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


class RadioIn(BaseModel):
    video_id: str | None = Field(None, description="Song radio: start from this song")
    artist_id: str | None = Field(None, description="Artist radio: the YouTube channel id (UC...)")
    artist: str | None = Field(None, description="Artist radio by name (library artists)")
    seeds: list[str] = Field([], max_length=50, description="Top-ups: the songs played so far, newest last")
    exclude: list[str] = Field([], max_length=2000, description="Already in the list")
    count: int = Field(25, ge=1, le=50)


class Removed(BaseModel):
    removed: int = Field(description="Songs taken out of your library")
    deleted: int = Field(description="Of those, files deleted from the PC (nobody else had them)")


class AddSongs(BaseModel):
    track_ids: list[int] = Field(min_length=1, max_length=2000)


class Added(BaseModel):
    added: int = Field(description="How many were new to your library")


class Me(BaseModel):
    username: str
    profile: str
    role: Literal["parent", "child"]
    household: list[str] = Field(description="Everyone sharing this music store")
    notice: str | None = Field(None, description="For a kids account: e.g. quiet hours now")
    youtube_search: bool = True
    discovery_play: bool = True


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
                 cover_url=f"/api/library/tracks/{t['id']}/cover",  # generated when the song has no art
                 gain_db=gain_db(t["loudness"]) if "loudness" in t.keys() else None,
                 colors=_colours(f"al:{t['album_id']}") if "album_id" in t.keys() else None)


def _album_out(a) -> Album:
    return Album(id=a["id"], name=a["name"], artist=a["artist"], artist_id=a["artist_id"],
                 year=a["year"], song_count=a["song_count"], duration_s=a["duration"] or 0,
                 play_count=a["play_count"],
                 cover_url=f"/api/library/albums/{a['id']}/cover",  # generated when the album has no art
                 starred=a["starred_at"] is not None, created_at=a["created_at"], colors=_colours(f"al:{a['id']}"))


def _artist_out(r) -> Artist:
    from . import artwork
    cover = f"/api/library/albums/{r['first_album_id']}/cover" if r["first_album_id"] else None
    colours = _colours(artwork.artist_key_of(r["name"])) or (_colours(f"al:{r['first_album_id']}") if r["first_album_id"] else None)
    return Artist(id=r["id"], name=r["name"], album_count=r["album_count"], cover_url=cover,
                  starred=r["starred_at"] is not None, image_url=f"/api/library/artists/{r['id']}/image", colors=colours)




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


def _remove(s: Session, tracks) -> Removed:
    removed = deleted = 0
    for t in tracks:
        path = s.lib.path_of(t)
        if s.lib.remove_track(t["id"]):
            removed += 1
            deleted += not path.exists()
    return Removed(removed=removed, deleted=deleted)


@router.delete("/library/tracks/{track_id}", response_model=Removed, tags=["library"])
def library_remove_track(track_id: int, s: Session = Depends(session)) -> Removed:
    """Take a song out of your library. Its file is deleted from the PC only when nobody
    else in the household has it (and never because of a kids account)."""
    try:
        return _remove(s, [_track(s, track_id)])
    except OSError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e


@router.delete("/library/albums/{album_id}", response_model=Removed, tags=["library"])
def library_remove_album(album_id: int, s: Session = Depends(session)) -> Removed:
    """Take an album (its songs in your library) out of your library; files as above."""
    tracks = s.lib.tracks_on_album(album_id)
    if not tracks:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such album in your library")
    try:
        return _remove(s, tracks)
    except OSError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e


@router.post("/radio", response_model=ItemList, tags=["discover"])
def radio(body: RadioIn, s: Session = Depends(session)) -> ItemList:
    """Song radio or artist radio: songs like this song / artist, to play now. Ask again
    with `seeds` (what's been played) and `exclude` to keep it going. Library songs come
    too; nothing is downloaded unless it's played (like instant play)."""
    from . import explore
    r = _ratings(s)
    similar = lambda vid, n: youtube.call(s.user.profile, "similar", vid, n)  # noqa: E731
    exclude = set(body.exclude)
    if body.seeds:  # top-up: like the latest songs heard
        items = explore.next_songs(s.lib, r, similar, body.seeds, exclude | set(body.seeds), [],
                                   body.count * (3 if s.kid else 1), new_only=False)
    elif body.video_id:
        items = [i for i in similar(body.video_id, 50) if i.id not in exclude]
    elif body.artist_id or body.artist:
        channel = body.artist_id
        if not channel:  # a library artist: find them on YouTube Music
            found = youtube.call(s.user.profile, "search_items", body.artist, "artist", 3)
            match = next((a for a in found if a.title.casefold() == body.artist.casefold()), found[0] if found else None)
            channel = match.id if match else None
        if channel:
            items = youtube.call(s.user.profile, "artist_radio", channel, 50)
        else:  # not on YouTube Music: radio of their songs in your library
            mine = [t["video_id"] for t in s.lib.search(body.artist or "", 0, 0, 0, 0, 20)[2]
                    if t["video_id"] and (body.artist or "").casefold() in (t["artist"] or "").casefold()]
            items = explore.next_songs(s.lib, r, similar, mine[:4], exclude, [], body.count, new_only=False)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Give video_id, artist_id or artist")
    items = [i for i in r.arrange(items) if i.type in ("song", "video") and r.value(i.id, i.artists) > -1]
    return ItemList(items=_items(items, s.lib, lookups=4 if s.kid else 0)[:body.count])


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


# --- 0.9.8 Together: Blend and Jam -------------------------------------------------------

class BlendPlaylist(BaseModel):
    id: int
    name: str


class BlendOut(BaseModel):
    on: bool = Field(description="You turned Blend on")
    allowed: bool = Field(description="False: a kids account whose parent hasn't allowed Blend")
    partners: list[str] = Field(description="People in your household you have a Blend with")
    waiting_for: list[str] = Field(description="People in your household who haven't turned Blend on yet")
    playlists: list[BlendPlaylist]


class BlendIn(BaseModel):
    on: bool


def _blend_out(s: "Session") -> BlendOut:
    from . import blend
    from .playlists import household
    me = s.lib.profile
    others = [p for p in household(me) if p.casefold() != me.casefold()]
    partners = blend.partners(me)
    with connect() as conn:
        rows = conn.execute("SELECT id, name FROM playlists WHERE profile = ? AND kind = 'blend' ORDER BY name",
                            (me,)).fetchall()
    return BlendOut(on=blend.wants(me), allowed=blend.allowed(me), partners=partners,
                    waiting_for=[p for p in others if p not in partners],
                    playlists=[BlendPlaylist(id=r["id"], name=r["name"]) for r in rows])


@router.get("/blend", response_model=BlendOut, tags=["together"])
def get_blend(s: Session = Depends(session)) -> BlendOut:
    """Blend: a weekly playlist with each person in your household who also turned it on."""
    return _blend_out(s)


@router.put("/blend", response_model=BlendOut, tags=["together"])
def set_blend(body: BlendIn, s: Session = Depends(session)) -> BlendOut:
    from . import blend
    if body.on and not blend.allowed(s.lib.profile):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A parent needs to allow Blend for this account first")
    blend.set_wanted(s.lib.profile, body.on)
    blend.rebuild_all()  # new Blends are made now, old ones go
    return _blend_out(s)


class JamSongOut(BaseModel):
    id: int = Field(description="Use to take it out again")
    item: Item
    added_by: str


class JamOut(BaseModel):
    host: str
    device: str = Field(description="The device playing the music")
    you_host: bool
    members: list[str]
    started_at: float
    index: int = Field(description="The song playing now (-1: not started)")
    version: int = Field(description="Goes up with every change: the host's app adds new songs when it changes")
    songs: list[JamSongOut]
    left_out: list[str] = Field([], description="Songs that weren't added (or were taken out) and why")


class JamStart(BaseModel):
    device: str = Field(max_length=60, description="This device's name, shown to the others")
    songs: list[DownloadRequest] = Field([], max_length=500, description="Start with these (type song/video)")


class JamAdd(BaseModel):
    songs: list[DownloadRequest] = Field(min_length=1, max_length=200)


class JamState(BaseModel):
    index: int = Field(ge=-1)


def _jam_out(s: "Session", jam, left_out=None) -> JamOut:
    items = [YTItem("song", x.video_id, x.title, x.artists, x.album, duration_s=x.duration_s, thumbnail=x.thumbnail)
             for x in jam.songs]
    have = s.lib.video_ids()
    return JamOut(host=jam.host, device=jam.device, you_host=jam.host.casefold() == s.lib.profile.casefold(),
                  members=list(jam.members), started_at=jam.started_at, index=jam.index, version=jam.version,
                  songs=[JamSongOut(id=x.id, item=Item(**vars(i), library_track_id=have.get(i.id)), added_by=x.added_by)
                         for x, i in zip(jam.songs, items)],
                  left_out=left_out or [])


def _jam(fn):
    from . import jam
    try:
        return fn()
    except jam.JamError as e:
        raise HTTPException(e.code, str(e)) from e


def _jam_items(songs: list) -> list[YTItem]:
    return [YTItem(x.type if x.type in ("song", "video") else "song", x.id, x.title or x.id, x.artists, x.album)
            for x in songs if x.type in ("song", "video")]


@router.get("/jam", response_model=JamOut | None, tags=["together"])
def get_jam(s: Session = Depends(session)) -> JamOut | None:
    """The Jam going in your household (null: none). The host's app checks this every few
    seconds and adds new songs to what it plays."""
    from . import jam
    j = jam.current(s.lib.profile)
    return _jam_out(s, j) if j else None


@router.post("/jam", response_model=JamOut, tags=["together"])
def start_jam(body: JamStart, s: Session = Depends(session)) -> JamOut:
    """Host a Jam on this device: everyone in the household can add songs to what it plays."""
    from . import jam
    call = lambda fn, *a: youtube.call(s.lib.profile, fn, *a)  # noqa: E731
    j = _jam(lambda: jam.start(s.lib.profile, body.device, _jam_items(body.songs), call))
    return _jam_out(s, j)


@router.post("/jam/join", response_model=JamOut, tags=["together"])
def join_jam(s: Session = Depends(session)) -> JamOut:
    from . import jam
    call = lambda fn, *a: youtube.call(s.lib.profile, fn, *a)  # noqa: E731
    j, removed = _jam(lambda: jam.join(s.lib.profile, call))
    return _jam_out(s, j, removed)


@router.post("/jam/songs", response_model=JamOut, tags=["together"])
def add_to_jam(body: JamAdd, s: Session = Depends(session)) -> JamOut:
    """Add songs to the Jam (joins it if you hadn't). With a child in the Jam, only songs
    her controls allow go in; `left_out` says which didn't."""
    from . import jam
    call = lambda fn, *a: youtube.call(s.lib.profile, fn, *a)  # noqa: E731
    j, why = _jam(lambda: jam.add(s.lib.profile, _jam_items(body.songs), call))
    return _jam_out(s, j, why)


@router.delete("/jam/songs/{song_id}", response_model=JamOut, tags=["together"])
def remove_from_jam(song_id: int, s: Session = Depends(session)) -> JamOut:
    from . import jam
    return _jam_out(s, _jam(lambda: jam.remove(s.lib.profile, song_id)))


@router.post("/jam/playing", response_model=JamOut, tags=["together"])
def jam_playing(body: JamState, s: Session = Depends(session)) -> JamOut:
    """The host's player: which song is playing now."""
    from . import jam
    return _jam_out(s, _jam(lambda: jam.playing(s.lib.profile, body.index)))


@router.post("/jam/leave", status_code=204, tags=["together"])
def leave_jam(s: Session = Depends(session)) -> Response:
    """Leave (the host leaving ends it)."""
    from . import jam
    _jam(lambda: jam.leave(s.lib.profile))
    return Response(status_code=204)


@router.delete("/jam", status_code=204, tags=["together"])
def end_jam(s: Session = Depends(session)) -> Response:
    from . import jam
    _jam(lambda: jam.end(s.lib.profile))
    return Response(status_code=204)


# --- 0.9.7: casting to speakers ---------------------------------------------------------

class CastToken(BaseModel):
    token: str = Field(description="Put on stream / cover links as ?token=...: plays songs and shows covers only")
    expires_at: float


@router.post("/cast/token", response_model=CastToken, tags=["auth"])
def cast_token(s: Session = Depends(session)) -> CastToken:
    """A short-lived key for a speaker (Chromecast / Nest) to fetch songs from this PC, so
    the phone never hands its own login to the speaker. Lasts 12 hours."""
    if s.desktop:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cast from a phone")
    token, expires = auth.create_cast_token(s.user, s.device_id)
    return CastToken(token=token, expires_at=expires)


# --- 0.9.6: recap (year in review / any month) and search by lyrics ---------------------

class RecapGenre(BaseModel):
    name: str
    plays: int


class RecapDay(BaseModel):
    date: str
    minutes: int


class RecapFirst(BaseModel):
    title: str
    artist: str | None
    track_id: int | None
    cover_url: str | None
    started_at: float


class Recap(BaseModel):
    period: str = Field(description="2026 (the year) or 2026-11 (a month)")
    title: str = Field(description='"Your 2026" or "November 2026"')
    since: float
    until: float
    minutes: int
    plays: int
    songs: int
    artists: int
    days_listened: int
    longest_streak_days: int = Field(description="Most days in a row with music")
    busiest_day: RecapDay | None
    favourite_hour: int | None = Field(description="0-23, local time")
    top_songs: list[StatSong]
    top_artists: list[StatArtist]
    top_albums: list[StatAlbum]
    top_genres: list[RecapGenre]
    first_song: RecapFirst | None = Field(description="The first song you played in the period")
    new_artists: int = Field(description="Artists you heard for the first time")
    top_new_artists: list[StatArtist]


class RecapPeriod(BaseModel):
    period: str
    title: str
    kind: Literal["year", "month"]


class RecapPeriods(BaseModel):
    periods: list[RecapPeriod] = Field(description="Newest first. A year shows from 1 December (or once it's over)")


@router.get("/recap/periods", response_model=RecapPeriods, tags=["stats"])
def recap_periods(s: Session = Depends(session)) -> RecapPeriods:
    from . import recap
    return RecapPeriods(periods=[RecapPeriod(**p) for p in recap.periods(s.lib)])


@router.get("/recap", response_model=Recap, tags=["stats"])
def get_recap(period: str = Query(min_length=4, max_length=7, pattern=r"^\d{4}(-\d{2})?$"),
              s: Session = Depends(session)) -> Recap:
    """Your recap: top songs, artists, albums and genres, minutes, streaks, firsts. Only
    ever your own (a kids account's recap is hers only)."""
    from . import recap
    try:
        r = recap.build(s.lib, period)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    tracks: dict = {}

    def track(tid):
        if tid and tid not in tracks:
            tracks[tid] = s.lib.track(tid)
        return tracks.get(tid)

    def cover(tid):
        t = track(tid)
        return f"/api/library/tracks/{tid}/cover" if t is not None and t["has_cover"] else None

    def artist(a):
        t = track(a["track_id"])
        return StatArtist(name=a["name"], plays=a["plays"], minutes=round((a.get("secs") or 0) / 60),
                          cover_url=cover(a["track_id"]), artist_id=t["artist_id"] if t is not None else None)

    f = r["first_song"]
    return Recap(
        **{k: r[k] for k in ("period", "title", "since", "until", "minutes", "plays", "songs", "artists",
                             "days_listened", "longest_streak_days", "favourite_hour", "new_artists")},
        busiest_day=RecapDay(**r["busiest_day"]) if r["busiest_day"] else None,
        top_songs=[StatSong(title=(track(x["track_id"]) or {"title": x["title"]})["title"], artist=x["artist"], album=None,
                            plays=x["plays"],
                            minutes=round((x["secs"] or 0) / 60), track_id=x["track_id"] if track(x["track_id"]) else None,
                            video_id=x["video_id"], cover_url=cover(x["track_id"]), thumbnail=_thumb(x["video_id"]))
                   for x in r["top_songs"]],
        top_artists=[artist(a) for a in r["top_artists"]],
        top_albums=[StatAlbum(name=a["name"], artist=a["artist"], plays=a["plays"], cover_url=cover(a["track_id"]),
                              album_id=(track(a["track_id"]) or {"album_id": None})["album_id"]) for a in r["top_albums"]],
        top_genres=[RecapGenre(**g) for g in r["top_genres"]],
        first_song=RecapFirst(title=f["title"], artist=f["artist"], track_id=f["track_id"] if track(f["track_id"]) else None,
                              cover_url=cover(f["track_id"]), started_at=f["started_at"]) if f else None,
        top_new_artists=[artist(a) for a in r["top_new_artists"]])


class LyricsHit(BaseModel):
    track: Track
    line: str = Field(description="The line of the lyrics that matched best")


class LyricsSearch(BaseModel):
    results: list[LyricsHit]


@router.get("/library/lyrics-search", response_model=LyricsSearch, tags=["library"])
def lyrics_search(q: str = Query(min_length=2, max_length=200), limit: int = Query(50, ge=1, le=200),
                  s: Session = Depends(session)) -> LyricsSearch:
    """Songs in your library whose lyrics have all these words ("quoted words" = that
    phrase). Only songs whose lyrics Dielify has kept (older songs fill in over time)."""
    from . import lyrics
    by_video = s.lib.video_ids()
    out = []
    for key, line in lyrics.search(q, 1000):
        tid = by_video.get(key) if not key.startswith("tr-") else (int(key[3:]) if key[3:].isdigit() else None)
        t = s.lib.track(tid) if tid else None
        if t is not None:
            out.append(LyricsHit(track=_track_out(t), line=line))
            if len(out) >= limit:
                break
    return LyricsSearch(results=out)


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
        try:
            found = lyrics.find(key, yt, artist, title, album, duration_s)
        except lyrics.Busy as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e), headers={"Retry-After": "60"}) from e
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
    c = _kid_controls(s)
    if c and not c.discovery_play:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A parent turned discovery play off for this account")
    r = _ratings(s)
    liked = [v for v in body.seeds if r.songs.get(v) == 1]
    seeds = [v for v in body.seeds if v not in liked] + liked  # newest last; liked ones go first
    # nothing heard yet: your most-played songs lately, else a few random library songs
    fallback = history.seeds(s.lib) or [t["video_id"] for t in s.lib.random_tracks(20) if t["video_id"]][:4]
    items = explore.next_songs(s.lib, r, lambda vid, n: youtube.call(s.user.profile, "similar", vid, n),
                               seeds, set(body.exclude) | set(body.seeds), fallback,
                               body.count * 3 if s.kid else body.count)
    if s.kid:  # only songs her controls allow (checked with YouTube where unmarked)
        allowed = {i.id for i in _items(items, s.lib, lookups=4)}
        items = [i for i in items if i.id in allowed][:body.count]
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


class NowMixOut(BaseModel):
    title: str = Field(description='e.g. "Your Tuesday evening"')
    description: str
    tracks: list[Track]


class ForYou(BaseModel):
    on_repeat: list[Track] = Field(description="Your songs you've played most in the last 2 weeks")
    forgotten: list[Track] = Field(description="Songs you played a lot, but not for 2 months")
    more_like: list[Item] = Field(description="Playlists: YouTube Music's mix of each of your most-played songs "
                                               "(open with /yt/playlist/{id})")
    now_mix: NowMixOut | None = Field(None, description="Time-of-day mix: what you usually play now (None: "
                                                     "not enough history at this time of day yet)")



@router.get("/discover/for-you", response_model=ForYou, tags=["discover"])
def discover_for_you(s: Session = Depends(session)) -> ForYou:
    from . import history, ratings
    r = _ratings(s)
    ok = lambda t: t is not None and r.value(t["video_id"], t["artist"], t["id"]) != ratings.BAN  # noqa: E731
    on_repeat = [_track_out(t) for t in map(s.lib.track, history.on_repeat(s.lib)) if ok(t)]
    forgotten = [_track_out(t) for t in map(s.lib.track, history.forgotten(s.lib)) if ok(t)]
    # More like your top songs: YouTube Music's mix of each of your most-played songs, as
    # playlists (Josh, 9 Nov: playlists, never a shelf of single songs). No YouTube call here:
    # a mix loads when it's opened (yt_adapter.song_mix).
    more = []
    for vid in history.seeds(s.lib, limit=10):
        t = s.lib.track_by_video(vid)
        title, artist = (t["title"], t["artist"]) if t is not None else history.song_name(s.lib, vid)
        if not title or r.value(vid, artist) in (ratings.BAN, ratings.DOWN):
            continue
        more.append(YTItem("playlist", SONG_MIX + vid, f"{title} mix", thumbnail=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                           subtitle=f"Songs like {title}" + (f" by {artist}" if artist else "")))
    from . import nowmix
    m = nowmix.build(s.lib)
    now = NowMixOut(title=m.title, description=m.description,
                    tracks=[_track_out(t) for t in map(s.lib.track, m.track_ids) if t is not None]) if m else None
    return ForYou(on_repeat=on_repeat, forgotten=forgotten, more_like=_items(more, s.lib),
                  now_mix=now)


# --- 0.9.5 Discovery: new releases, artist About, follows, leave out of my taste ----------

class NewReleases(BaseModel):
    items: list[Item] = Field(description="Albums and singles from your artists that turned up lately, newest first")
    watching: int = Field(description="How many artists are watched (followed + your most-played)")
    auto_download: bool = Field(description="New albums download by themselves (never for a kids account)")


class NewReleaseSettings(BaseModel):
    auto_download: bool


@router.get("/discover/new", response_model=NewReleases, tags=["discover"])
def discover_new(s: Session = Depends(session)) -> NewReleases:
    """New for you: releases from the artists you follow and your 20 most-played. The PC
    reads their YouTube pages once a day in the background; this never waits on YouTube."""
    from . import releases
    items = _items(releases.new_for_you(s.lib.profile), s.lib)
    if s.kid:  # albums without an explicit mark (singles) aren't checked: leave them out
        c = _kid_controls(s)
        if c and c.explicit == "block":
            items = [i for i in items if i.explicit is False]
    return NewReleases(items=items, watching=len(releases.watched(s.lib.profile)),
                       auto_download=releases.auto_download(s.lib.profile) and not s.kid)


@router.put("/discover/new/settings", response_model=NewReleases, tags=["discover"])
def discover_new_settings(body: NewReleaseSettings, s: Session = Depends(session)) -> NewReleases:
    from . import releases
    if s.kid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A parent decides what downloads in a kids account")
    releases.set_pref(s.lib.profile, "new_releases_auto", body.auto_download)
    return discover_new(s)


@router.post("/discover/new/refresh", status_code=202, tags=["discover"])
def discover_new_refresh(request: Request, s: Session = Depends(session)) -> Response:
    """Read your artists' pages now (in the background; reload /discover/new after a minute)."""
    request.app.state.releases.refresh_soon(s.lib.profile)
    return Response(status_code=202)


class Link(BaseModel):
    label: str
    url: str


class ArtistAbout(BaseModel):
    name: str
    description: str | None = Field(None, description="Bio from the artist's YouTube Music page")
    thumbnail: str | None = None
    channel_id: str | None = Field(None, description="YouTube Music channel (for artist radio)")
    links: list[Link] = Field([], description="Website, Wikipedia, socials... (from MusicBrainz)")
    followed: bool = Field(description="You follow this artist (their new releases show in New for you)")


@router.get("/artists/about", response_model=ArtistAbout, tags=["library"])
def artist_about(name: str = Query(min_length=1, max_length=300), refresh: bool = False,
                 s: Session = Depends(session)) -> ArtistAbout:
    """An artist's About: bio and links. Kept on the PC for 30 days (the first look can take
    a few seconds: YouTube, then MusicBrainz)."""
    from . import artists, releases
    offline = settings_mod.load().offline
    call = None if offline else (lambda fn, *a: youtube.call(s.user.profile, fn, *a))
    a = artists.cached_about(name) if offline else artists.about(call, name, refresh)
    a = a or {}
    return ArtistAbout(name=name, description=a.get("description"), thumbnail=a.get("thumbnail"),
                       channel_id=a.get("channel_id"), links=[Link(**l) for l in a.get("links") or []],
                       followed=releases.is_followed(s.lib.profile, name))


class FollowIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    channel_id: str | None = Field(None, description="YouTube Music channel, when following from YouTube")
    follow: bool = True


class Follow(BaseModel):
    name: str
    channel_id: str | None = None


class FollowList(BaseModel):
    follows: list[Follow]


@router.get("/follows", response_model=FollowList, tags=["discover"])
def list_follows(s: Session = Depends(session)) -> FollowList:
    from . import releases
    return FollowList(follows=[Follow(name=f["name"], channel_id=f["channel_id"]) for f in releases.follows(s.lib.profile)])


@router.put("/follows", response_model=FollowList, tags=["discover"])
def set_follow(body: FollowIn, request: Request, s: Session = Depends(session)) -> FollowList:
    """Follow an artist (or stop). Following reads their page soon, so New for you fills in."""
    from . import releases
    releases.set_follow(s.lib.profile, body.name, body.follow, body.channel_id)
    if body.follow:
        request.app.state.releases.refresh_soon(s.lib.profile)
    return list_follows(s)


class TasteOut(BaseModel):
    kind: Literal["song", "playlist"]
    key: str = Field(description="song: video id (or tr-<track id>); playlist: Dielify playlist id")
    name: str
    added_at: float | None = None


class TasteIn(BaseModel):
    kind: Literal["song", "playlist"]
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(max_length=300)
    out: bool = Field(True, description="true: leave it out of your taste; false: count it again")


class TasteList(BaseModel):
    items: list[TasteOut] = Field(description="Songs and playlists that don't shape your recommendations")


@router.get("/taste", response_model=TasteList, tags=["discover"])
def list_taste(s: Session = Depends(session)) -> TasteList:
    from . import taste
    return TasteList(items=[TasteOut(**t) for t in taste.listing(s.lib.profile)])


@router.put("/taste", response_model=TasteList, tags=["discover"])
def set_taste(body: TasteIn, s: Session = Depends(session)) -> TasteList:
    """Leave a song or playlist out of your taste: it still plays, but For you, mixes, the
    time-of-day mix and new releases ignore it."""
    from . import taste
    taste.set_out(s.lib.profile, body.kind, body.key, body.name, body.out)
    return list_taste(s)


@router.get("/me", response_model=Me, tags=["auth"])
def me(s: Session = Depends(session)) -> Me:
    from .library import people
    from . import kids
    c = _kid_controls(s)
    return Me(username=s.user.name, profile=s.lib.profile, role=s.lib.role,
              household=[p["profile"] for p in people() if p["store"] == s.lib.store],
              notice=kids.quiet_message(c) if c else None,
              youtube_search=c.youtube_search if c else True, discovery_play=c.discovery_play if c else True)


@router.get("/library/household", response_model=TrackList, tags=["library"])
def library_household(q: str = "", limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                      s: Session = Depends(session)) -> TrackList:
    """Songs already on the PC that aren't in your library (someone else in the household
    has them). Add them with POST /library/add: no download needed."""
    rows = s.lib.household(q, limit if not s.kid else 2000, offset)
    if s.kid:  # only what her controls allow (songs not checked yet wait for the check)
        rows = _kid_filter(s.lib).tracks(rows)[:limit]
    return TrackList(tracks=[_track_out(t) for t in rows])


def _household_track(s: Session, track_id: int):
    t = s.lib.household_track(track_id)
    if t is not None and s.kid and not _kid_filter(s.lib).tracks([t]):
        return None
    return t


@router.post("/library/add", response_model=Added, tags=["library"])
def library_add(body: AddSongs, s: Session = Depends(session)) -> Added:
    """Add songs that are already on the PC to your library."""
    ids = body.track_ids
    if s.kid:
        ids = [t["id"] for t in _kid_filter(s.lib).tracks(filter(None, map(s.lib.household_track, ids)))]
    return Added(added=s.lib.add_many(ids, "household"))


@router.get("/library/tracks/{track_id}/stream", tags=["library"],
            response_class=FileResponse, responses={200: {"content": {"audio/*": {}}}})
def library_stream(track_id: int, s: Session = Depends(media_session)) -> FileResponse:
    """The original file (supports Range requests for seeking). Also plays songs on the
    Household shelf (in your household's store, not yet in your library)."""
    _quiet(s)
    t = s.lib.track(track_id) or _household_track(s, track_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such track")
    path = s.lib.path_of(t)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing; run a library scan")
    return FileResponse(path, media_type=CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))


def _image(data: bytes) -> Response:
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


def _cover_response(s: Session, track_id: int | None, size: int, album_id: int | None = None) -> Response:
    """The song's / album's cover; one is drawn (album name on a colour) when it has none."""
    from . import artwork
    from .subsonic_api import _cover_bytes
    t = (s.lib.track(track_id) or _household_track(s, track_id)) if track_id else None
    path = s.lib.path_of(t) if t else None
    data = _cover_bytes(str(path), path.stat().st_mtime, size) if path and path.exists() and t["has_cover"] else None
    if data:
        return _image(data)
    a = s.lib.album(album_id or t["album_id"]) if (album_id or t is not None) else None
    if a is None and t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such song or album")
    name = a["name"] if a else t["album"] or t["title"]
    artist = a["artist"] if a else t["artist"]
    return _image(artwork.designed(name or "Unknown album", None, artist, seed=f"{artist}|{name}", size=size or 600))


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
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such album")
    return _cover_response(s, a["cover_track_id"], size, album_id=album_id)


@router.get("/library/artists/{artist_id}/image", tags=["library"],
            responses={200: {"content": {"image/jpeg": {}}}})
def library_artist_image(artist_id: int, size: int = Query(0, ge=0, le=3000),
                         s: Session = Depends(media_session)) -> Response:
    """The artist's photo (from YouTube Music, fetched once in the background); until there
    is one, their first album's cover."""
    from . import artwork
    r = s.lib.artist(artist_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such artist")
    photo = artwork.photo_path(r["name"])
    if photo.exists():
        data = photo.read_bytes()
        if size and size < 600:
            from PIL import Image
            import io as _io
            data = artwork._jpeg(Image.open(_io.BytesIO(data)), size)
        return _image(data)
    if r["first_album_id"]:
        return library_album_cover(r["first_album_id"], size, s)
    return _image(artwork.designed(r["name"], "Artist", seed=r["name"], size=size or 600))


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
