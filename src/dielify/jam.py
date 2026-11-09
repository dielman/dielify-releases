"""Jam: one shared queue for the household, e.g. in the car.

One device hosts (it plays the music); everyone else in the household can join from their
phone or the PC app, see what's playing and add songs. The host's app picks up new songs
(it asks every few seconds) and reports which song is playing.

Kids: a child may join unless a parent turned that off (her controls: jam). While a child is
in the Jam, every song added has to pass her controls, and songs already queued that don't
are taken out when she joins.

Kept in memory (a Jam is a one-off): it ends when the host ends it, when the server restarts,
or after IDLE_S without anything happening.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field

from .library import person
from .playlists import household
from .yt_adapter import YTItem

IDLE_S = 6 * 3600
MAX_SONGS = 500

_lock = threading.Lock()
_jams: dict[str, "Jam"] = {}  # by household (store owner)
_ids = itertools.count(1)


class JamError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


@dataclass
class Song:
    id: int
    video_id: str
    title: str
    artists: list[str]
    album: str | None
    duration_s: int | None
    thumbnail: str | None
    added_by: str


@dataclass
class Jam:
    store: str
    host: str
    device: str
    started_at: float
    members: list[str] = field(default_factory=list)
    songs: list[Song] = field(default_factory=list)
    index: int = -1
    updated_at: float = 0.0
    version: int = 0

    def touch(self) -> None:
        self.updated_at = time.time()
        self.version += 1


def _store(profile: str) -> str:
    return person(profile)["store"].casefold()


def _children(jam: Jam) -> list[str]:
    return [m for m in jam.members if person(m)["role"] == "child"]


def _allowed(jam: Jam, items: list[YTItem], call=None) -> tuple[list[YTItem], list[str]]:
    """Songs every child in the Jam may hear (and why the others were left out)."""
    from . import kids
    out = list(items)
    why: list[str] = []
    for child in _children(jam):
        f = kids.KidFilter(child, call, lookups=4)
        ok = {i.id for i in f.items(out)}
        why += [f"{i.title}: not for {child}" for i in out if i.id not in ok]
        out = [i for i in out if i.id in ok]
    return out, why


def current(profile: str) -> Jam | None:
    with _lock:
        jam = _jams.get(_store(profile))
        if jam and time.time() - jam.updated_at > IDLE_S:
            _jams.pop(jam.store, None)
            return None
        if jam and profile.casefold() not in {p.casefold() for p in household(profile)}:
            return None
        return jam


def start(profile: str, device: str, songs: list[YTItem] | None = None, call=None) -> Jam:
    with _lock:
        jam = _jams.get(_store(profile))
        if jam and time.time() - jam.updated_at <= IDLE_S and jam.host.casefold() != profile.casefold():
            raise JamError(f"{jam.host} is already hosting a Jam: join it instead", 409)
        jam = Jam(store=_store(profile), host=profile, device=device[:60] or "a device", started_at=time.time(),
                  members=[profile])
        jam.touch()
        _jams[jam.store] = jam
    if songs:
        add(profile, songs, call)
    return jam


def join(profile: str, call=None) -> tuple[Jam, list[str]]:
    jam = current(profile)
    if jam is None:
        raise JamError("There's no Jam going in your household", 404)
    removed: list[str] = []
    if person(profile)["role"] == "child":
        from . import kids
        if not getattr(kids.load(profile), "jam", True):
            raise JamError("A parent has turned Jams off for this account", 403)
    with _lock:
        if profile.casefold() not in {m.casefold() for m in jam.members}:
            jam.members.append(profile)
        if _children(jam):  # songs still to come must pass her controls
            upcoming = jam.songs[jam.index + 1:]
            items = [YTItem("song", s.video_id, s.title, s.artists, s.album) for s in upcoming]
            ok, removed = _allowed(jam, items, call)
            keep = {i.id for i in ok}
            jam.songs = jam.songs[:jam.index + 1] + [s for s in upcoming if s.video_id in keep]
        jam.touch()
    return jam, removed


def leave(profile: str) -> None:
    jam = current(profile)
    if jam is None:
        return
    if jam.host.casefold() == profile.casefold():
        end(profile)
        return
    with _lock:
        jam.members = [m for m in jam.members if m.casefold() != profile.casefold()]
        jam.touch()


def add(profile: str, items: list[YTItem], call=None) -> tuple[Jam, list[str]]:
    jam = current(profile)
    if jam is None:
        raise JamError("There's no Jam going in your household", 404)
    if profile.casefold() not in {m.casefold() for m in jam.members}:
        join(profile, call)
    items = [i for i in items if i.type in ("song", "video")]
    ok, why = _allowed(jam, items, call)
    with _lock:
        for i in ok:
            if len(jam.songs) >= MAX_SONGS:
                why.append(f"{i.title}: the Jam is full")
                continue
            jam.songs.append(Song(next(_ids), i.id, i.title, i.artists, i.album, i.duration_s, i.thumbnail, profile))
        jam.touch()
    return jam, why


def remove(profile: str, song_id: int) -> Jam:
    jam = current(profile)
    if jam is None:
        raise JamError("There's no Jam going in your household", 404)
    with _lock:
        for n, s in enumerate(jam.songs):
            if s.id == song_id:
                if profile.casefold() not in (s.added_by.casefold(), jam.host.casefold()):
                    raise JamError("Only whoever added a song (or the host) can take it out", 403)
                if n <= jam.index:
                    raise JamError("That song has already played")
                jam.songs.pop(n)
                jam.touch()
                return jam
    raise JamError("No such song in the Jam", 404)


def playing(profile: str, index: int) -> Jam:
    """The host says which song is playing."""
    jam = current(profile)
    if jam is None or jam.host.casefold() != profile.casefold():
        raise JamError("Only the host's player reports what's playing", 403)
    with _lock:
        jam.index = max(-1, min(index, len(jam.songs) - 1))
        jam.touch()
    return jam


def end(profile: str) -> None:
    jam = current(profile)
    if jam is None:
        return
    if jam.host.casefold() != profile.casefold() and person(profile)["role"] == "child":
        raise JamError("Only the host (or a parent) can end the Jam", 403)
    with _lock:
        _jams.pop(jam.store, None)


def reset() -> None:
    """Tests: no Jams."""
    with _lock:
        _jams.clear()
