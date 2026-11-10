"""Songs saved without their album (0.9.11).

When YouTube answered a song lookup with an empty page (it does for a minute now and then),
downloads before 0.9.11 saved the song as a plain video: in "Singles", without album, track
number or year (33 songs in Josh's log on 9 Nov). The adapter now asks again; this worker
repairs the songs already saved that way. Each song in "Singles" with no year and no track
number is looked up once more at quiet moments. If YouTube Music now gives its album, the
file's tags and cover are rewritten and it moves to its album folder; the song keeps its id,
so libraries, playlists, ratings and play counts stay with it. Real music videos (not in
YouTube Music's catalogue) stay as they are. Each song is checked once (table details_checked).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from .library import connect, library_for

log = logging.getLogger(__name__)


def candidates(limit: int = 20) -> list:
    with connect() as conn:
        return conn.execute(
            "SELECT t.* FROM tracks t JOIN albums al ON al.id = t.album_id "
            "WHERE al.name = 'Singles' AND t.year IS NULL AND t.track_no IS NULL AND t.video_id IS NOT NULL "
            "AND t.video_id NOT IN (SELECT video_id FROM details_checked) ORDER BY t.id LIMIT ?",
            (limit,)).fetchall()


def _done(video_id: str, result: str) -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO details_checked (video_id, checked_at, result) VALUES (?, ?, ?)",
                     (video_id, time.time(), result))


def fix(track, call) -> str:
    """Look one song up again; returns what happened. `call(profile, fn_name, *args)` runs an
    adapter method (the API's youtube.background). Raises OSError when the file is in use
    (playing): it's tried again on a later round."""
    from .downloader import library_relpath
    from .tagging import prepare_cover, tag_file
    lib = library_for(track["profile"])
    info = call(track["profile"], "get_track", track["video_id"])
    if not info.album:
        _done(track["video_id"], "no album")
        return "no album"
    old = lib.path_of(track)
    if not old.exists():
        _done(track["video_id"], "file missing")
        return "file missing"
    base = lib.root / library_relpath(info)
    new = base.with_name(base.name + old.suffix.lower())
    if new.exists() and new != old:
        _done(track["video_id"], "already there")
        return "already there"
    cover = prepare_cover(call(track["profile"], "fetch_cover", info.cover_url))
    new.parent.mkdir(parents=True, exist_ok=True)
    os.replace(old, new)  # fails while the song is being read on Windows: next round
    tag_file(new, info, cover)
    lib.moved(track["id"], new)
    for folder in (old.parent, old.parent.parent):  # "Singles", then the artist, if now empty
        try:
            if folder != lib.root and lib.root in folder.parents:
                folder.rmdir()
        except OSError:
            break
    _done(track["video_id"], "fixed")
    log.info("Song details fixed: %s -> %s", old.relative_to(lib.root), new.relative_to(lib.root))
    return "fixed"


class Worker:
    """Background: a few songs a round, at quiet moments, until none are left."""

    def __init__(self, call=None):
        self.call = call  # the API's youtube.background
        self._stop = threading.Event()

    def run_once(self, limit: int = 10) -> int:
        done = 0
        for t in candidates(limit):
            if self._stop.is_set():
                break
            try:
                fix(t, self.call)
                done += 1
            except OSError as e:
                log.info("Song %s is in use, trying later: %s", t["video_id"], e)
            except Exception as e:  # noqa: BLE001  (offline / YouTube trouble: next round)
                log.info("Couldn't look up %s again: %s", t["video_id"], e)
                return done
        return done

    def _loop(self) -> None:
        from . import settings as settings_mod
        self._stop.wait(600)  # after start-up's own work
        while not self._stop.is_set():
            busy = False
            try:
                if not settings_mod.load().offline:
                    busy = self.run_once() > 0
            except Exception:  # noqa: BLE001
                log.exception("Song details worker failed")
            self._stop.wait(30 if busy else 6 * 3600)

    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="dielify-details").start()

    def stop(self) -> None:
        self._stop.set()
