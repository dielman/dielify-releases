"""Never-ending discovery play: an endless list of songs that aren't in your library yet.

The apps ask for the next few songs whenever the list is about to run out (seeded by the
songs heard so far, thumbs-up ones first). Each new song is downloaded so you can check it
out; songs this mode brought in are remembered in `explore_songs`. Thumbs down (or ban) on
one of those deletes its download from the PC. Thumbs up and unrated songs stay.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from .library import Library, connect
from .ratings import BAN, DOWN, Ratings
from .yt_adapter import YTItem

log = logging.getLogger(__name__)

SIMILAR_PER_SEED = 25
MAX_SEEDS = 4


def next_songs(lib: Library, ratings: Ratings, similar: Callable[[str, int], list[YTItem]],
               seeds: list[str], exclude: set[str], fallback_seeds: list[str], count: int = 10,
               new_only: bool = True) -> list[YTItem]:
    """Up to `count` new songs like the seeds (newest seed first): not in the library, not
    already in the list, nothing banned or thumbed down. Seeds that give nothing new fall
    back to your most-played songs. new_only=False (radio): library songs may come too."""
    have = lib.video_ids() if new_only else {}
    picked: list[YTItem] = []
    seen = set(exclude)
    order = [v for v in dict.fromkeys(list(reversed(seeds))[:MAX_SEEDS] + fallback_seeds[:MAX_SEEDS]) if v]
    pools = []
    for vid in order:
        try:
            pools.append(similar(vid, SIMILAR_PER_SEED))
        except Exception as e:  # noqa: BLE001  (one seed failing shouldn't stop the list)
            log.info("Discovery play: no similar songs for %s (%s)", vid, e)
        if sum(len(p) for p in pools) >= count * 4:
            break
    # take from each seed's songs in turn, so one seed doesn't fill the list
    while len(picked) < count and any(pools):
        for pool in pools:
            while pool:
                it = pool.pop(0)
                if it.type not in ("song", "video") or it.id in seen or it.id in have:
                    continue
                seen.add(it.id)
                if ratings.value(it.id, it.artists) in (BAN, DOWN):
                    continue
                picked.append(it)
                break
            if len(picked) >= count:
                break
    return picked


def remember(profile: str, items: list[YTItem]) -> None:
    """These songs were brought in by discovery play (so thumbs down may delete them)."""
    now = time.time()
    with connect() as conn:
        conn.executemany("INSERT OR IGNORE INTO explore_songs (profile, video_id, title, added_at) VALUES (?,?,?,?)",
                         [(profile, it.id, it.title[:300], now) for it in items])


def is_explore(profile: str, video_id: str | None) -> bool:
    if not video_id:
        return False
    with connect() as conn:
        return conn.execute("SELECT 1 FROM explore_songs WHERE profile = ? AND video_id = ?",
                            (profile, video_id)).fetchone() is not None


def disliked(profile: str, lib: Library, queue, video_id: str | None, track_id: int | None) -> str | None:
    """Thumbs down / ban on a song: if discovery play brought it in, stop its download and
    delete the file. Returns the song's title when something was removed."""
    if not video_id and track_id:
        t = lib.track(track_id)
        video_id = t["video_id"] if t else None
    if not is_explore(profile, video_id):
        return None
    with connect() as conn:
        jobs = [r["id"] for r in conn.execute(
            "SELECT id FROM downloads WHERE profile = ? AND video_id = ? AND status IN "
            "('queued', 'downloading', 'processing')", (profile, video_id))]
        row = conn.execute("SELECT title FROM explore_songs WHERE profile = ? AND video_id = ?",
                           (profile, video_id)).fetchone()
    for j in jobs:
        queue.cancel(profile, j)
    tid = lib.video_ids().get(video_id)
    if tid:
        lib.remove_track(tid)
    with connect() as conn:
        conn.execute("DELETE FROM explore_songs WHERE profile = ? AND video_id = ?", (profile, video_id))
        # still on the downloads list as "done": it isn't in the library any more
        conn.execute("UPDATE downloads SET status = 'cancelled', track_id = NULL, error = 'Thumbs down: removed' "
                     "WHERE profile = ? AND video_id = ? AND status = 'done'", (profile, video_id))
    log.info("Discovery play: thumbs down, removed %s (%s)", video_id, "file deleted" if tid else "download stopped")
    return row["title"] if row else video_id
