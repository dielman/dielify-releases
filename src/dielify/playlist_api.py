"""/api/playlists: your playlists, synced with YouTube Music (see playlists.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from . import playlists as pl
from .custom_api import Item, Session, _items, media_session, session
from .yt_adapter import YTItem

router = APIRouter(prefix="/api", tags=["playlists"])


class PlaylistSummary(BaseModel):
    id: int
    name: str
    yt_id: str | None = Field(description="Set when synced with this YouTube Music playlist")
    read_only: bool = Field(description="Can't be edited (Liked Music, Dielify mixes)")
    kind: str = Field("user", description="user = your playlist, mix = made by Dielify weekly, "
                                          "smart = picked by rules (GET/PUT /playlists/{id}/rules)")
    description: str | None = None
    count: int
    pending: int = Field(description="Edits waiting to be sent to YouTube")
    synced_at: float | None
    sync_error: str | None
    thumbnail: str | None
    shared: bool = Field(False, description="Shared with the household: everyone can add and remove songs")
    cover_url: str | None = Field(None, description="Always set: a 2x2 grid of its album covers, or a designed cover")
    colors: dict | None = Field(None, description="bg / accent / fg from the cover")
    owner: str | None = Field(None, description="Who made it")
    mine: bool = Field(True, description="False: someone else's list shared with you (you can't rename/delete it)")


class PlaylistEntry(BaseModel):
    entry_id: int = Field(description="Use to remove this entry")
    item: Item
    added_by: str | None = Field(None, description="Who added it (shared playlists)")


class PlaylistDetail(BaseModel):
    playlist: PlaylistSummary
    entries: list[PlaylistEntry]


class PlaylistList(BaseModel):
    playlists: list[PlaylistSummary]


class NewPlaylist(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    on_youtube: bool = Field(True, description="Also create it (private) on YouTube Music and keep it synced")


class ImportPlaylist(BaseModel):
    yt_id: str = Field(min_length=2, max_length=80)


class RenamePlaylist(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class SongIn(BaseModel):
    id: str = Field(min_length=1, max_length=20, description="YouTube video id")
    type: str = "song"
    title: str = Field(max_length=300)
    artists: list[str] = []
    album: str | None = None
    duration_s: int | None = None
    thumbnail: str | None = None


class AddSongs(BaseModel):
    songs: list[SongIn] = Field(min_length=1, max_length=500)


class SmartRule(BaseModel):
    field: str = Field(description="artist | album | title | genre | plays | year | length_s | last_played | added | rating")
    op: str = Field(description="text: is, is_not, contains, not_contains; numbers: gt, lt, eq; "
                                "last_played/added: within, not_within (days); rating: is")
    value: str | float = Field(description="text, a number (days for last_played/added), or up/down/none for rating")


class SmartRules(BaseModel):
    match: str = Field("all", description="all = every rule, any = at least one")
    rules: list[SmartRule] = Field(min_length=1, max_length=20)
    sort: str = Field("random", description="random (new order daily) | most_played | least_played | "
                                            "recently_added | recently_played | title | artist | year")
    limit: int = Field(100, ge=1, le=1000)


class SmartPlaylistIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    rules: SmartRules


def _smart(fn):
    try:
        return fn()
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


def _engine(request: Request) -> pl.Playlists:
    return request.app.state.playlists


def _thumb(video_id: str | None) -> str | None:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def _summary(p: dict, viewer: str | None = None) -> PlaylistSummary:
    first = p.get("first_video") or (p["items"][0]["video_id"] if p.get("items") else None)
    mine = viewer is None or p["profile"].casefold() == viewer.casefold()
    return PlaylistSummary(id=p["id"], name=p["name"], yt_id=p["yt_id"], read_only=bool(p["read_only"]),
                           kind=p.get("kind") or "user", description=p.get("description"),
                           count=p["count"] if "count" in p else len(p.get("items", [])),
                           pending=p.get("pending", 0), synced_at=p["synced_at"], sync_error=p["sync_error"],
                           thumbnail=_thumb(first), shared=bool(p.get("shared")), owner=p["profile"], mine=mine,
                           cover_url=f"/api/playlists/{p['id']}/cover", colors=_cover_colours(p))


def _cover_colours(p: dict) -> dict | None:
    """Colours for a playlist card: designed covers have theirs from the name; grids take
    the first album's (worked out when the cover is drawn)."""
    from . import artwork
    if (p.get("kind") or "user") != "user" or not p.get("first_video"):
        return artwork.seed_colours(p["name"])
    return _grid_colours.get(p["id"])


_grid_colours: dict[int, dict] = {}


def _detail(s: Session, p: dict) -> PlaylistDetail:
    yt = [YTItem("song", i["video_id"], i["title"], [i["artist"]] if i["artist"] else [], i["album"],
                 duration_s=i["duration_s"], thumbnail=i["thumbnail"] or _thumb(i["video_id"])) for i in p["items"]]
    # a kids account only sees the songs her controls allow (also in a shared list): match by video id
    allowed = {it.id: it for it in _items(yt, s.lib)}
    entries = [PlaylistEntry(entry_id=i["id"], item=allowed[i["video_id"]], added_by=i.get("added_by"))
               for i in p["items"] if i["video_id"] in allowed]
    summary = _summary(p, s.user.profile)
    if s.kid:
        summary.count = len(entries)
    return PlaylistDetail(playlist=summary, entries=entries)


def _not_kid(s: Session) -> None:
    """A kids account's playlists stay in Dielify: the YouTube account is the parent's."""
    if s.kid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kids accounts' playlists stay in Dielify")


def _guard(fn):
    try:
        return fn()
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e).strip("'\"")) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/playlists", response_model=PlaylistList)
def list_playlists(s: Session = Depends(session)) -> PlaylistList:
    return PlaylistList(playlists=[_summary(p, s.user.profile) for p in pl.all_playlists(s.user.profile)])


@router.post("/playlists", response_model=PlaylistDetail, status_code=201)
def create_playlist(body: NewPlaylist, request: Request, s: Session = Depends(session)) -> PlaylistDetail:
    return _detail(s, _guard(lambda: _engine(request).create(s.user.profile, body.name, body.on_youtube and not s.kid)))


@router.post("/playlists/import", response_model=PlaylistDetail)
def import_playlist(body: ImportPlaylist, request: Request, s: Session = Depends(session)) -> PlaylistDetail:
    """Start syncing one of your YouTube Music playlists (its songs are downloaded)."""
    _not_kid(s)
    return _detail(s, _guard(lambda: _engine(request).import_youtube(s.user.profile, body.yt_id)))


@router.post("/playlists/smart", response_model=PlaylistDetail, status_code=201)
def create_smart(body: SmartPlaylistIn, s: Session = Depends(session)) -> PlaylistDetail:
    """A smart playlist: songs from your library picked by rules, kept up to date."""
    from . import smart
    pid = _smart(lambda: smart.create(s.user.profile, body.name, body.rules.model_dump()))
    return _detail(s, pl.get(s.user.profile, pid))


@router.get("/playlists/{playlist_id}/rules", response_model=SmartPlaylistIn)
def smart_rules(playlist_id: int, s: Session = Depends(session)) -> SmartPlaylistIn:
    from . import smart
    rules = smart.rules_of(s.user.profile, playlist_id)
    p = pl.get(s.user.profile, playlist_id) if rules else None
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such smart playlist")
    return SmartPlaylistIn(name=p["name"], rules=SmartRules(**rules))


@router.put("/playlists/{playlist_id}/rules", response_model=PlaylistDetail)
def set_smart_rules(playlist_id: int, body: SmartPlaylistIn, s: Session = Depends(session)) -> PlaylistDetail:
    from . import smart
    if smart.rules_of(s.user.profile, playlist_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such smart playlist")
    _smart(lambda: smart.update(s.user.profile, playlist_id, body.name, body.rules.model_dump()))
    return _detail(s, pl.get(s.user.profile, playlist_id))


@router.get("/playlists/{playlist_id}/cover", tags=["playlists"],
            responses={200: {"content": {"image/jpeg": {}}}})
def playlist_cover(playlist_id: int, size: int = Query(600, ge=64, le=1200),
                   s: Session = Depends(media_session)) -> Response:
    """The playlist's cover: four of its album covers, or a designed one (mixes, Blends,
    smart playlists, and playlists whose songs have no covers on this PC)."""
    from . import artwork
    p = pl.get(s.user.profile, playlist_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such playlist")
    data, colours = artwork.playlist_cover(s.lib, p, size)
    _grid_colours[playlist_id] = {k: colours[k] for k in ("bg", "accent", "fg")}
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


class ShareIn(BaseModel):
    shared: bool = True


@router.put("/playlists/{playlist_id}/share", response_model=PlaylistDetail)
def share_playlist(playlist_id: int, body: ShareIn, s: Session = Depends(session)) -> PlaylistDetail:
    """Share your playlist with the household: everyone sees it and can add and remove songs
    (a kids account sees only the songs her controls allow). Only Dielify-only playlists."""
    return _detail(s, _guard(lambda: pl.set_shared(s.user.profile, playlist_id, body.shared)))


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetail)
def get_playlist(playlist_id: int, s: Session = Depends(session)) -> PlaylistDetail:
    p = pl.get(s.user.profile, playlist_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such playlist")
    return _detail(s, p)


@router.patch("/playlists/{playlist_id}", response_model=PlaylistDetail)
def rename_playlist(playlist_id: int, body: RenamePlaylist, request: Request,
                    s: Session = Depends(session)) -> PlaylistDetail:
    return _detail(s, _guard(lambda: _engine(request).rename(s.user.profile, playlist_id, body.name)))


@router.delete("/playlists/{playlist_id}", status_code=204)
def delete_playlist(playlist_id: int, request: Request, s: Session = Depends(session),
                    on_youtube: bool = Query(False, description="Also delete it on YouTube Music")) -> Response:
    _guard(lambda: _engine(request).delete(s.user.profile, playlist_id, on_youtube and not s.kid))
    return Response(status_code=204)


@router.post("/playlists/{playlist_id}/songs", response_model=PlaylistDetail)
def add_songs(playlist_id: int, body: AddSongs, request: Request, s: Session = Depends(session)) -> PlaylistDetail:
    """Add songs (also on YouTube Music if synced). Songs not in your library download."""
    items = [YTItem("video" if x.type == "video" else "song", x.id, x.title, x.artists, x.album,
                    duration_s=x.duration_s, thumbnail=x.thumbnail) for x in body.songs]
    return _detail(s, _guard(lambda: _engine(request).add(s.user.profile, playlist_id, items)))


@router.delete("/playlists/{playlist_id}/entries/{entry_id}", response_model=PlaylistDetail)
def remove_entry(playlist_id: int, entry_id: int, request: Request, s: Session = Depends(session),
                 on_youtube: bool = Query(False, description="Required for synced playlists: removes it there too")
                 ) -> PlaylistDetail:
    return _detail(s, _guard(lambda: _engine(request).remove(s.user.profile, playlist_id, entry_id, on_youtube)))


class MixStatus(BaseModel):
    mixes: list[PlaylistSummary]
    artists: int = Field(description="Artists in your library")
    looked_up: int = Field(description="Artists whose genres have been looked up (MusicBrainz)")
    built_at: float | None


@router.get("/mixes", response_model=MixStatus, tags=["discover"])
def list_mixes(s: Session = Depends(session)) -> MixStatus:
    """Dielify-made genre, decade and vibe mixes (rebuilt weekly)."""
    from . import mixes, tags
    st = tags.status()
    return MixStatus(mixes=[_summary(p) for p in pl.all_playlists(s.user.profile) if p.get("kind") == "mix"],
                     artists=st["artists"], looked_up=st["looked_up"], built_at=mixes.last_built(s.user.profile))


@router.post("/mixes/refresh", status_code=202, tags=["discover"])
def refresh_mixes(request: Request, s: Session = Depends(session)) -> Response:
    """Rebuild the mixes now (in the background; takes a minute)."""
    request.app.state.mixes.refresh_soon()
    return Response(status_code=202)


@router.post("/playlists/{playlist_id}/sync", response_model=PlaylistDetail)
def sync_playlist(playlist_id: int, request: Request, s: Session = Depends(session)) -> PlaylistDetail:
    _not_kid(s)
    return _detail(s, _guard(lambda: _engine(request).sync(s.user.profile, playlist_id)))
