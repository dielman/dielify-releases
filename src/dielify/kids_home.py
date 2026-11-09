"""Kids discovery (0.9.3): a kids account's Discover home, made only from Dielify's own data
(never the parent's YouTube home feed), and filtered by the parent's controls.

Shelves: Picked for you (the parent's picks), Your favourites (her most-played songs),
Because you like <song> (radio of her top song: new songs), On the PC (household songs she
could add, by artists she likes first). Kept for 30 minutes per child.
"""

from __future__ import annotations

import threading
import time

from . import history, kids
from .library import Library
from .yt_adapter import Shelf, YTItem

KEEP_S = 30 * 60
_cache: dict[str, tuple[float, list[Shelf]]] = {}
_lock = threading.Lock()


def forget(profile: str | None = None) -> None:
    """Controls changed: build again next time."""
    with _lock:
        if profile is None:
            _cache.clear()
        else:
            _cache.pop(profile, None)


def _song(row) -> YTItem:
    vid = row["video_id"]
    return YTItem("song", vid, row["title"], [row["artist"]], row["album"],
                  thumbnail=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")


def shelves(lib: Library, call: kids.Call) -> list[Shelf]:
    with _lock:
        hit = _cache.get(lib.profile)
        if hit and time.time() - hit[0] < KEEP_S:
            return hit[1]
    f = kids.KidFilter(lib.profile, call, lookups=15)
    out: list[Shelf] = []

    picks = [YTItem(**{k: v for k, v in p.items() if k in YTItem.__dataclass_fields__}) for p in f.c.picks]
    picks = f.items(picks)
    if picks:
        out.append(Shelf("Picked for you", picks))

    favourite_ids = history.on_repeat(lib, days=30, limit=20) or history.forgotten(lib, limit=20)
    favourites = [_song(t) for t in map(lib.track, favourite_ids) if t is not None and t["video_id"]]
    if not favourites:  # nothing played much yet: her newest songs
        newest = sorted(lib.search("", 0, 0, 0, 0, 500)[2], key=lambda t: -(t["created_at"] or 0))
        favourites = [_song(t) for t in newest if t["video_id"]]
    if favourites:
        out.append(Shelf("Your favourites", favourites[:20]))

    have = lib.video_ids()
    seeds = history.seeds(lib, limit=2)
    for vid in seeds[:1]:
        t = lib.track_by_video(vid)
        try:
            radio = call("similar", vid, 40)
        except Exception:  # noqa: BLE001 - offline / signed out: the other shelves still work
            radio = []
        new = f.items([i for i in radio if i.id not in have])[:15]
        if new:
            out.append(Shelf(f"Because you like {t['title'] if t else 'your favourites'}", new))

    rows = lib.household("", 600)
    liked = {r["artist"].casefold() for r in lib.search("", 0, 0, 0, 0, 2000)[2]}
    rows = sorted(rows, key=lambda r: (r["artist"].casefold() not in liked, -(r["created_at"] or 0)))
    on_pc = [_song(r) for r in f.tracks(rows) if r["video_id"]][:20]
    if on_pc:
        out.append(Shelf("On the PC: add to your library", on_pc))

    with _lock:
        _cache[lib.profile] = (time.time(), out)
    return out
