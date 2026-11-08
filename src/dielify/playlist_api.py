"""/api/playlists: your playlists, synced with YouTube Music (see playlists.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from . import playlists as pl
from .custom_api import Item, Session, _items, session
from .yt_adapter import YTItem

router = APIRouter(prefix="/api", tags=["playlists"])


class PlaylistSummary(BaseModel):
    id: int
    name: str
    yt_id: str | None = Field(description="Set when synced with this YouTube Music playlist")
    read_only: bool = Field(description="Synced one way only (e.g. Liked Music)")
    count: int
    pending: int = Field(description="Edits waiting to be sent to YouTube")
    synced_at: float | None
    sync_error: str | None
    thumbnail: str | None


class PlaylistEntry(BaseModel):
    entry_id: int = Field(description="Use to remove this entry")
    item: Item


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


def _engine(request: Request) -> pl.Playlists:
    return request.app.state.playlists


def _thumb(video_id: str | None) -> str | None:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def _summary(p: dict) -> PlaylistSummary:
    first = p.get("first_video") or (p["items"][0]["video_id"] if p.get("items") else None)
    return PlaylistSummary(id=p["id"], name=p["name"], yt_id=p["yt_id"], read_only=bool(p["read_only"]),
                           count=p["count"] if "count" in p else len(p.get("items", [])),
                           pending=p.get("pending", 0), synced_at=p["synced_at"], sync_error=p["sync_error"],
                           thumbnail=_thumb(first))


def _detail(s: Session, p: dict) -> PlaylistDetail:
    yt = [YTItem("song", i["video_id"], i["title"], [i["artist"]] if i["artist"] else [], i["album"],
                 duration_s=i["duration_s"], thumbnail=i["thumbnail"] or _thumb(i["video_id"])) for i in p["items"]]
    return PlaylistDetail(playlist=_summary(p), entries=[PlaylistEntry(entry_id=i["id"], item=it)
                                                         for i, it in zip(p["items"], _items(yt, s.lib))])


def _guard(fn):
    try:
        return fn()
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e).strip("'\"")) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/playlists", response_model=PlaylistList)
def list_playlists(s: Session = Depends(session)) -> PlaylistList:
    return PlaylistList(playlists=[_summary(p) for p in pl.all_playlists(s.user.profile)])


@router.post("/playlists", response_model=PlaylistDetail, status_code=201)
def create_playlist(body: NewPlaylist, request: Request, s: Session = Depends(session)) -> PlaylistDetail:
    return _detail(s, _guard(lambda: _engine(request).create(s.user.profile, body.name, body.on_youtube)))


@router.post("/playlists/import", response_model=PlaylistDetail)
def import_playlist(body: ImportPlaylist, request: Request, s: Session = Depends(session)) -> PlaylistDetail:
    """Start syncing one of your YouTube Music playlists (its songs are downloaded)."""
    return _detail(s, _guard(lambda: _engine(request).import_youtube(s.user.profile, body.yt_id)))


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
    _guard(lambda: _engine(request).delete(s.user.profile, playlist_id, on_youtube))
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


@router.post("/playlists/{playlist_id}/sync", response_model=PlaylistDetail)
def sync_playlist(playlist_id: int, request: Request, s: Session = Depends(session)) -> PlaylistDetail:
    return _detail(s, _guard(lambda: _engine(request).sync(s.user.profile, playlist_id)))
