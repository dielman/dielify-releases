"""Playlists, kept in step with YouTube Music.

A playlist with a `yt_id` is synced; YouTube Music is the master copy:
  - edits made in Dielify (add, remove, rename) are sent to YouTube straight away; if
    YouTube can't be reached they wait in `playlist_ops` and are retried on the next sync,
  - a sync (every SYNC_EVERY_S, or "Sync now") sends waiting edits, then takes YouTube's
    list as the playlist (plus any adds still waiting), so changes made in the YouTube
    Music app show up here,
  - songs new to a playlist (from either side) are downloaded.
A playlist without `yt_id` lives only in Dielify. Read-only ones (Liked Music) sync one
way: YouTube -> Dielify.
Removing songs or deleting a playlist on YouTube only happens when the caller says so
(the apps ask first).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .library import connect, library_for
from .yt_adapter import YTItem

log = logging.getLogger(__name__)

SYNC_EVERY_S = 20 * 60
READ_ONLY_IDS = {"LM"}  # Liked Music: adding would mean "liking" songs; not done yet

Caller = Callable[..., object]  # call(profile, adapter_method_name, *args)


def _err(e: Exception) -> str:
    return str(getattr(e, "detail", None) or e)


# --- reading ----------------------------------------------------------------------------

def all_playlists(profile: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM playlist_items i WHERE i.playlist_id = p.id) AS count, "
            "(SELECT COUNT(*) FROM playlist_ops o WHERE o.playlist_id = p.id) AS pending, "
            "(SELECT i.video_id FROM playlist_items i WHERE i.playlist_id = p.id ORDER BY i.position LIMIT 1) "
            "AS first_video FROM playlists p WHERE p.profile = ? ORDER BY p.name COLLATE NOCASE", (profile,)).fetchall()
    return [dict(r) for r in rows]


def get(profile: str, playlist_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM playlists WHERE id = ? AND profile = ?", (playlist_id, profile)).fetchone()
        if row is None:
            return None
        items = conn.execute("SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY position, id",
                             (playlist_id,)).fetchall()
        pending = conn.execute("SELECT COUNT(*) FROM playlist_ops WHERE playlist_id = ?", (playlist_id,)).fetchone()[0]
    return {**dict(row), "items": [dict(i) for i in items], "pending": pending}


def by_yt_id(profile: str, yt_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM playlists WHERE profile = ? AND yt_id = ?", (profile, yt_id)).fetchone()
    return get(profile, row["id"]) if row else None


def _read_only_reason(pl: dict) -> str:
    if pl.get("kind") == "mix":
        return f"\"{pl['name']}\" is a Dielify mix: it's rebuilt every week, so it can't be edited"
    return f"\"{pl['name']}\" can only be changed in YouTube Music"


# --- local changes ------------------------------------------------------------------------

def _insert_items(conn, playlist_id: int, items: list[YTItem], start: int, sets: list[str | None] | None = None):
    now = time.time()
    for n, it in enumerate(items):
        conn.execute(
            "INSERT INTO playlist_items (playlist_id, position, video_id, set_video_id, title, artist, album, "
            "duration_s, thumbnail, added_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (playlist_id, start + n, it.id, sets[n] if sets else None, it.title, ", ".join(it.artists) or None,
             it.album, it.duration_s, it.thumbnail, now))


def _touch(conn, playlist_id: int) -> None:
    conn.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (time.time(), playlist_id))


class Playlists:
    """Playlist changes for one server (all profiles), talking to YouTube via `call`
    and downloading via `queue` (a DownloadQueue or None)."""

    def __init__(self, call: Caller, queue=None):
        self.call, self.queue = call, queue
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()
        self._stop = threading.Event()

    def _lock(self, playlist_id: int) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(playlist_id, threading.Lock())

    def _download(self, profile: str, name: str, items: list[YTItem]) -> None:
        if self.queue is None or not items:
            return
        from . import settings as settings_mod
        have = library_for(profile).video_ids()
        missing, seen = [], set()
        for it in items:
            if it.id not in have and it.id not in seen:
                seen.add(it.id)
                missing.append(it)
        if missing:
            self.queue.enqueue(profile, missing, "playlist", name, "playlist sync")

    def create(self, profile: str, name: str, on_youtube: bool) -> dict:
        name = name.strip()[:150]
        if not name:
            raise ValueError("Give the playlist a name")
        yt_id = self.call(profile, "create_playlist", name, "Made in Dielify") if on_youtube else None
        now = time.time()
        with connect() as conn:
            pid = conn.execute("INSERT INTO playlists (profile, name, yt_id, created_at, updated_at, synced_at) "
                               "VALUES (?,?,?,?,?,?)", (profile, name, yt_id, now, now, now if yt_id else None)).lastrowid
        return get(profile, pid)

    def import_youtube(self, profile: str, yt_id: str) -> dict:
        """Start syncing one of the account's YouTube Music playlists."""
        existing = by_yt_id(profile, yt_id)
        if existing:
            return self.sync(profile, existing["id"])
        now = time.time()
        with connect() as conn:
            pid = conn.execute("INSERT INTO playlists (profile, name, yt_id, read_only, created_at, updated_at) "
                               "VALUES (?,?,?,?,?,?)", (profile, yt_id, yt_id, int(yt_id in READ_ONLY_IDS), now, now)
                               ).lastrowid
        return self.sync(profile, pid)

    def add(self, profile: str, playlist_id: int, items: list[YTItem]) -> dict:
        pl = get(profile, playlist_id)
        if pl is None:
            raise KeyError("No such playlist")
        if pl["read_only"]:
            raise ValueError(_read_only_reason(pl))
        items = [i for i in items if i.type in ("song", "video")]
        with self._lock(playlist_id), connect() as conn:
            start = (conn.execute("SELECT MAX(position) FROM playlist_items WHERE playlist_id = ?",
                                  (playlist_id,)).fetchone()[0] or 0) + 1
            _insert_items(conn, playlist_id, items, start)
            _touch(conn, playlist_id)
            if pl["yt_id"]:
                for it in items:
                    conn.execute("INSERT INTO playlist_ops (playlist_id, op, video_id, created_at) VALUES (?,?,?,?)",
                                 (playlist_id, "add", it.id, time.time()))
        self._download(profile, pl["name"], items)
        if pl["yt_id"]:
            self.push(profile, playlist_id)
        return get(profile, playlist_id)

    def remove(self, profile: str, playlist_id: int, item_id: int, on_youtube: bool) -> dict:
        """Remove one entry. On a synced playlist, `on_youtube` must be True (the app has
        asked): a song removed only here would come back with the next sync."""
        pl = get(profile, playlist_id)
        if pl is None:
            raise KeyError("No such playlist")
        if pl["read_only"]:
            raise ValueError(_read_only_reason(pl))
        if pl["yt_id"] and not on_youtube:
            raise ValueError("This playlist is synced with YouTube Music: removing it here also "
                             "removes it there (confirm with on_youtube=true)")
        with self._lock(playlist_id), connect() as conn:
            row = conn.execute("SELECT * FROM playlist_items WHERE id = ? AND playlist_id = ?",
                               (item_id, playlist_id)).fetchone()
            if row is None:
                raise KeyError("No such song in the playlist")
            conn.execute("DELETE FROM playlist_items WHERE id = ?", (item_id,))
            _touch(conn, playlist_id)
            if pl["yt_id"]:
                pending_add = conn.execute("SELECT id FROM playlist_ops WHERE playlist_id = ? AND op = 'add' "
                                           "AND video_id = ? ORDER BY id DESC LIMIT 1",
                                           (playlist_id, row["video_id"])).fetchone()
                if pending_add and not row["set_video_id"]:
                    conn.execute("DELETE FROM playlist_ops WHERE id = ?", (pending_add["id"],))  # never reached YouTube
                else:
                    conn.execute("INSERT INTO playlist_ops (playlist_id, op, video_id, set_video_id, created_at) "
                                 "VALUES (?,?,?,?,?)", (playlist_id, "remove", row["video_id"],
                                                        row["set_video_id"], time.time()))
        if pl["yt_id"]:
            self.push(profile, playlist_id)
        return get(profile, playlist_id)

    def rename(self, profile: str, playlist_id: int, name: str) -> dict:
        pl = get(profile, playlist_id)
        if pl is None:
            raise KeyError("No such playlist")
        name = name.strip()[:150]
        if not name:
            raise ValueError("Give the playlist a name")
        with connect() as conn:
            conn.execute("UPDATE playlists SET name = ?, updated_at = ? WHERE id = ?", (name, time.time(), playlist_id))
            if pl["yt_id"] and not pl["read_only"]:
                conn.execute("DELETE FROM playlist_ops WHERE playlist_id = ? AND op = 'rename'", (playlist_id,))
                conn.execute("INSERT INTO playlist_ops (playlist_id, op, title, created_at) VALUES (?,?,?,?)",
                             (playlist_id, "rename", name, time.time()))
        if pl["yt_id"] and not pl["read_only"]:
            self.push(profile, playlist_id)
        return get(profile, playlist_id)

    def delete(self, profile: str, playlist_id: int, on_youtube: bool) -> None:
        """Delete here; with on_youtube, delete the YouTube Music playlist too (the app asks).
        Otherwise the YouTube playlist just stops syncing."""
        pl = get(profile, playlist_id)
        if pl is None:
            raise KeyError("No such playlist")
        if on_youtube and pl["yt_id"]:
            if pl["read_only"]:
                raise ValueError(f"\"{pl['name']}\" can't be deleted")
            self.call(profile, "delete_playlist", pl["yt_id"])  # fails loudly: nothing deleted here then
        with connect() as conn:
            conn.execute("DELETE FROM playlist_ops WHERE playlist_id = ?", (playlist_id,))
            conn.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (playlist_id,))
            conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))

    # --- talking to YouTube -------------------------------------------------------------

    def push(self, profile: str, playlist_id: int) -> bool:
        """Send waiting edits to YouTube, oldest first. Stops at the first failure (kept
        for next time). True if nothing is left waiting."""
        pl = get(profile, playlist_id)
        if pl is None or not pl["yt_id"]:
            return True
        with self._lock(playlist_id):
            with connect() as conn:
                ops = [dict(r) for r in conn.execute("SELECT * FROM playlist_ops WHERE playlist_id = ? ORDER BY id",
                                                     (playlist_id,))]
            for op in ops:
                try:
                    if op["op"] == "add":
                        self.call(profile, "add_to_playlist", pl["yt_id"], [op["video_id"]])
                    elif op["op"] == "remove":
                        set_id = op["set_video_id"] or self._find_set_id(profile, pl["yt_id"], op["video_id"])
                        if set_id:
                            self.call(profile, "remove_from_playlist", pl["yt_id"], [(op["video_id"], set_id)])
                    elif op["op"] == "rename":
                        self.call(profile, "rename_playlist", pl["yt_id"], op["title"])
                except Exception as e:  # offline, signed out, YouTube refused: keep it for later
                    with connect() as conn:
                        conn.execute("UPDATE playlist_ops SET error = ? WHERE id = ?", (_err(e), op["id"]))
                        conn.execute("UPDATE playlists SET sync_error = ? WHERE id = ?", (_err(e), playlist_id))
                    log.info("Playlist %s: edit waits for later: %s", playlist_id, _err(e))
                    return False
                with connect() as conn:
                    conn.execute("DELETE FROM playlist_ops WHERE id = ?", (op["id"],))
            with connect() as conn:
                conn.execute("UPDATE playlists SET sync_error = NULL WHERE id = ?", (playlist_id,))
        return True

    def _find_set_id(self, profile: str, yt_id: str, video_id: str) -> str | None:
        """An entry added from Dielify before the next sync has no setVideoId yet."""
        _, entries = self.call(profile, "playlist_entries", yt_id)
        return next((s for it, s in entries if it.id == video_id and s), None)

    def sync(self, profile: str, playlist_id: int) -> dict:
        """Send waiting edits, then take YouTube's list (plus adds still waiting)."""
        pl = get(profile, playlist_id)
        if pl is None:
            raise KeyError("No such playlist")
        if not pl["yt_id"]:
            return pl
        self.push(profile, playlist_id)
        try:
            info, entries = self.call(profile, "playlist_entries", pl["yt_id"])
        except Exception as e:
            with connect() as conn:
                conn.execute("UPDATE playlists SET sync_error = ? WHERE id = ?", (_err(e), playlist_id))
            return get(profile, playlist_id)
        with self._lock(playlist_id), connect() as conn:
            before = {r[0] for r in conn.execute("SELECT video_id FROM playlist_items WHERE playlist_id = ?",
                                                  (playlist_id,))}
            waiting = [r[0] for r in conn.execute("SELECT video_id FROM playlist_ops WHERE playlist_id = ? "
                                                  "AND op = 'add' ORDER BY id", (playlist_id,))]
            kept = {r["video_id"]: dict(r) for r in conn.execute(
                "SELECT * FROM playlist_items WHERE playlist_id = ? AND video_id IN (%s)" % ",".join("?" * len(waiting)),
                (playlist_id, *waiting))} if waiting else {}
            conn.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (playlist_id,))
            _insert_items(conn, playlist_id, [it for it, _ in entries], 1, [s for _, s in entries])
            on_remote = {it.id for it, _ in entries}
            for n, vid in enumerate(v for v in waiting if v not in on_remote):
                k = kept.get(vid)
                if k:
                    _insert_items(conn, playlist_id, [YTItem("song", vid, k["title"], [k["artist"]] if k["artist"] else [],
                                                             k["album"], duration_s=k["duration_s"],
                                                             thumbnail=k["thumbnail"])], len(entries) + 1 + n)
            pending_rename = conn.execute("SELECT 1 FROM playlist_ops WHERE playlist_id = ? AND op = 'rename'",
                                          (playlist_id,)).fetchone()
            name = pl["name"] if pending_rename or not info.title else info.title
            conn.execute("UPDATE playlists SET name = ?, synced_at = ?, updated_at = ?, sync_error = NULL WHERE id = ?",
                         (name, time.time(), time.time(), playlist_id))
        new = [it for it, _ in entries if it.id not in before]
        self._download(profile, name, new)
        return get(profile, playlist_id)

    def sync_all(self) -> None:
        with connect() as conn:
            rows = conn.execute("SELECT id, profile FROM playlists WHERE yt_id IS NOT NULL").fetchall()
        for r in rows:
            if self._stop.is_set():
                return
            try:
                self.sync(r["profile"], r["id"])
            except Exception:
                log.exception("Playlist sync failed for %s", r["id"])

    # --- background ---------------------------------------------------------------------

    def _loop(self) -> None:
        self._stop.wait(90)  # let startup (and the first downloads) settle
        while not self._stop.is_set():
            from . import settings as settings_mod
            if not settings_mod.load().offline:
                self.sync_all()
            self._stop.wait(SYNC_EVERY_S)

    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="dielify-playlists").start()

    def stop(self) -> None:
        self._stop.set()
