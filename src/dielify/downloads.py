"""Download queue: requests from phones/clients, worked through one at a time.

Jobs live in the database, so a restart picks up where it left off. One worker
thread downloads one track at a time (modest, human-paced traffic), retries
failures with back-off, and can cancel a running download.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from typing import Callable

from . import credstore
from . import settings as settings_mod
from .downloader import download_track
from .library import Library, connect
from .yt_adapter import NotSignedIn, Offline, YTItem, YTMusicAdapter

log = logging.getLogger(__name__)

ACTIVE = ("queued", "downloading", "processing")
FINISHED = ("done", "failed", "cancelled")
MAX_ATTEMPTS = 3
RETRY_DELAYS_S = (30, 120)  # wait before the 2nd and 3rd attempt
SIGNIN_CHECK_S = 600        # re-confirm the YouTube sign-in at most this often
SIGNIN_WAIT_S = 300         # while signed out (or offline), check again this often, ONCE
                            # per profile, not once per waiting download


class _Cancelled(Exception):
    pass


def _default_adapter(profile: str) -> YTMusicAdapter:
    auth = credstore.load(profile)
    if auth is None:
        raise NotSignedIn(f"Profile '{profile}' is not signed in to YouTube Music on the PC "
                          "(run: dielify auth login)")
    return YTMusicAdapter(auth=auth, request_delay_s=settings_mod.load().request_delay_s)


class DownloadQueue:
    def __init__(self, adapter_factory: Callable[[str], object] = _default_adapter):
        self._adapter_factory = adapter_factory
        self._adapters: dict[str, object] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancel: set[int] = set()
        self._signin_ok: dict[str, float] = {}  # profile -> when the sign-in was last confirmed
        self._paused: dict[str, tuple[float, str]] = {}  # profile or "*" -> (until, reason)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # --- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        self._recover()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dielify-downloads", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def _recover(self) -> None:
        """Jobs interrupted by a crash or shutdown go back in the queue."""
        with connect() as conn:
            rows = conn.execute("SELECT DISTINCT profile FROM downloads WHERE status IN "
                                "('downloading', 'processing')").fetchall()
            conn.execute("UPDATE downloads SET status = 'queued', progress = 0, updated_at = ? "
                         "WHERE status IN ('downloading', 'processing')", (time.time(),))
        s = settings_mod.load()
        for r in rows:  # half-finished temp folders from the interrupted downloads
            for tmp in s.profile_library(r["profile"]).glob(".dielify-dl-*"):
                shutil.rmtree(tmp, ignore_errors=True)

    def signin_changed(self, profile: str) -> None:
        """A new YouTube sign-in was saved: use it, and retry waiting jobs now."""
        self._adapters.pop(profile, None)
        self._signin_ok.pop(profile, None)
        self._paused.pop(profile, None)
        with connect() as conn:
            conn.execute("UPDATE downloads SET not_before = 0, error = NULL WHERE profile = ? AND "
                         "status = 'queued'", (profile,))
        self._wake.set()

    # --- requests ------------------------------------------------------------------

    def enqueue(self, profile: str, items: list[YTItem], request_type: str,
                request_title: str | None = None, requested_by: str | None = None) -> list[dict]:
        """Queue songs/videos. Ones already in the library, or already queued, aren't
        downloaded twice."""
        lib = Library(profile, settings_mod.load().profile_library(profile))
        in_library = lib.video_ids()
        request_id = uuid.uuid4().hex[:12]
        now = time.time()
        # while the queue is paused (dead sign-in, offline), new requests wait with it
        pauses = [p for p in (self._paused.get(profile), self._paused.get("*")) if p and p[0] > now]
        hold_until, hold_reason = max(pauses) if pauses else (0.0, None)
        ids = []
        with connect() as conn:
            for item in items:
                if item.type not in ("song", "video"):
                    continue
                existing = conn.execute(
                    "SELECT id FROM downloads WHERE profile = ? AND video_id = ? AND status IN "
                    "('queued', 'downloading', 'processing')", (profile, item.id)).fetchone()
                if existing:
                    ids.append(existing["id"])
                    continue
                done = item.id in in_library
                ids.append(conn.execute(
                    "INSERT INTO downloads (profile, video_id, title, artist, album, request_id, "
                    "request_type, request_title, requested_by, status, progress, track_id, "
                    "not_before, error, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (profile, item.id, item.title, ", ".join(item.artists) or None, item.album,
                     request_id, request_type, request_title or item.title, requested_by,
                     "done" if done else "queued", 1.0 if done else 0.0,
                     in_library.get(item.id), 0.0 if done else hold_until,
                     None if done else hold_reason, now, now)).lastrowid)
        self._wake.set()
        return [j for j in (self.get(profile, i) for i in ids) if j]

    def list(self, profile: str, active_only: bool = False, limit: int = 200,
             finished_only: bool = False) -> list[dict]:
        """active_only: in the order they'll download (the running one first).
        finished_only / everything: newest first."""
        if active_only:
            where = " AND status IN ('queued', 'downloading', 'processing')"
            order = "CASE status WHEN 'queued' THEN 1 ELSE 0 END, id"  # same order as _next_job
        else:
            where = " AND status IN ('done', 'failed', 'cancelled')" if finished_only else ""
            order = "id DESC"
        with connect() as conn:
            rows = conn.execute(f"SELECT * FROM downloads WHERE profile = ?{where} "
                                f"ORDER BY {order} LIMIT ?", (profile, limit)).fetchall()
        return [dict(r) for r in rows]

    def summary(self, profile: str) -> dict:
        """How many are waiting, and how long a song has recently taken (for an estimate)."""
        with connect() as conn:
            active = conn.execute("SELECT COUNT(*) FROM downloads WHERE profile = ? AND status IN "
                                  "('queued', 'downloading', 'processing')", (profile,)).fetchone()[0]
            recent = [r[0] for r in conn.execute(
                "SELECT updated_at FROM downloads WHERE profile = ? AND status = 'done' AND track_id IS NOT NULL "
                "AND attempts > 0 ORDER BY updated_at DESC LIMIT 11", (profile,))]
        gaps = [a - b for a, b in zip(recent, recent[1:]) if 0 < a - b < 600]
        return {"active": active, "seconds_per_song": sum(gaps) / len(gaps) if gaps else None}

    def get(self, profile: str, job_id: int) -> dict | None:
        with connect() as conn:
            row = conn.execute("SELECT * FROM downloads WHERE id = ? AND profile = ?",
                               (job_id, profile)).fetchone()
        return dict(row) if row else None

    def cancel(self, profile: str, job_id: int) -> dict | None:
        job = self.get(profile, job_id)
        if job is None or job["status"] in FINISHED:
            return job
        with self._lock:
            self._cancel.add(job_id)  # stops it if the worker is on it right now
        self._set(job_id, status="cancelled", error=None)
        return self.get(profile, job_id)

    # --- worker --------------------------------------------------------------------

    def _set(self, job_id: int, **fields) -> None:
        fields["updated_at"] = time.time()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with connect() as conn:
            conn.execute(f"UPDATE downloads SET {sets} WHERE id = ?", (*fields.values(), job_id))

    def _pause_queue(self, profile: str | None, reason: str) -> None:
        """Hold every waiting download (of one profile, or all) for SIGNIN_WAIT_S, so a
        dead sign-in or offline mode costs one check per wait, not one per download."""
        until = time.time() + SIGNIN_WAIT_S
        self._paused[profile or "*"] = (until, reason)  # also holds downloads requested meanwhile
        sql = "UPDATE downloads SET not_before = ?, error = ?, updated_at = ? WHERE status = 'queued'"
        args: list = [until, reason, time.time()]
        if profile is not None:
            sql += " AND profile = ?"
            args.append(profile)
        with connect() as conn:
            conn.execute(sql, args)

    def _next_job(self) -> tuple[dict | None, float]:
        """The next job that's due, and how long until the next one becomes due."""
        now = time.time()
        with connect() as conn:
            row = conn.execute("SELECT * FROM downloads WHERE status = 'queued' AND not_before <= ? "
                               "ORDER BY id LIMIT 1", (now,)).fetchone()
            later = conn.execute("SELECT MIN(not_before) FROM downloads WHERE status = 'queued'"
                                 ).fetchone()[0]
        wait = max(1.0, (later or now + 60) - now)
        return (dict(row) if row else None), min(wait, 60.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job, wait = self._next_job()
            except Exception:
                log.exception("Download queue: database error")
                job, wait = None, 10.0
            if job is None:
                self._wake.wait(wait)
                self._wake.clear()
                continue
            self._process(job)

    def _adapter(self, profile: str):
        if profile not in self._adapters:
            self._adapters[profile] = self._adapter_factory(profile)
        return self._adapters[profile]

    def _progress_hook(self, job_id: int):
        last = {"t": 0.0, "p": 0.0}

        def hook(d: dict) -> None:
            if job_id in self._cancel:
                raise _Cancelled()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if not total:
                    return
                p = min(0.99, d.get("downloaded_bytes", 0) / total)
                now = time.monotonic()
                if p - last["p"] >= 0.02 or now - last["t"] >= 1.0:
                    last.update(t=now, p=p)
                    self._set(job_id, progress=p)
            elif d.get("status") == "finished":
                self._set(job_id, status="processing", progress=0.99)  # tagging + filing
        return hook

    def _confirm_signin(self, profile: str):
        """The profile's adapter, after checking (at most every SIGNIN_CHECK_S) that
        YouTube still accepts the sign-in. A dead sign-in doesn't fail downloads; it
        would silently drop Premium quality, so jobs wait for `dielify auth login` instead."""
        adapter = self._adapter(profile)
        check = getattr(adapter, "account_name", None)
        if check and time.time() - self._signin_ok.get(profile, 0) > SIGNIN_CHECK_S:
            check()  # raises NotSignedIn
            self._signin_ok[profile] = time.time()
            if self._paused.pop(profile, None):  # signed in again: drop the "waiting" notes
                with connect() as conn:
                    conn.execute("UPDATE downloads SET error = NULL WHERE profile = ? AND "
                                 "status = 'queued'", (profile,))
        return adapter

    def _process(self, job: dict) -> None:
        job_id, profile = job["id"], job["profile"]
        if settings_mod.load().offline:
            self._pause_queue(None, "Waiting: offline mode is on. Turn it off to download.")
            return
        try:
            adapter = self._confirm_signin(profile)
        except NotSignedIn as e:
            self._adapters.pop(profile, None)  # pick up a fresh sign-in next time
            self._signin_ok.pop(profile, None)
            self._pause_queue(profile, f"Waiting for YouTube sign-in on the PC (Settings, then Sign in). {e}")
            log.warning("Profile %s: YouTube sign-in not working; its downloads wait %ds. %s",
                        profile, SIGNIN_WAIT_S, e)
            return
        attempt = job["attempts"] + 1
        self._set(job_id, status="downloading", attempts=attempt, error=None, progress=0.0)
        log.info("Downloading %s (%s), attempt %d", job["video_id"], job["title"], attempt)
        try:
            s = settings_mod.load()
            lib = Library(profile, s.profile_library(profile))
            res = download_track(adapter, job["video_id"], s, profile, self._progress_hook(job_id))
            track = lib.track_by_video(job["video_id"])
            track_id = track["id"] if track else lib.index_file(res.path)
            if job_id in self._cancel:  # cancelled at the very end: keep the file, report it
                log.info("Job %d finished after cancel was requested", job_id)
            self._set(job_id, status="done", progress=1.0, track_id=track_id, error=None,
                      title=res.info.title, artist=res.info.artist, album=res.info.album)
            log.info("Done %s -> track %s", job["video_id"], track_id)
        except Exception as e:
            if isinstance(e, Offline):  # switched offline mid-download: wait, don't count it
                self._set(job_id, status="queued", attempts=attempt - 1, progress=0.0)
                self._pause_queue(None, "Waiting: offline mode is on. Turn it off to download.")
            elif job_id in self._cancel or isinstance(e, _Cancelled) or "_Cancelled" in repr(e):
                self._set(job_id, status="cancelled", error=None)
                log.info("Cancelled %s", job["video_id"])
            elif isinstance(e, NotSignedIn):  # sign-in died mid-download: wait, don't count it
                self._adapters.pop(profile, None)
                self._signin_ok.pop(profile, None)
                self._set(job_id, status="queued", attempts=attempt - 1, progress=0.0)
                self._pause_queue(profile, f"Waiting for YouTube sign-in on the PC (Settings, then Sign in). {e}")
            elif attempt < MAX_ATTEMPTS:
                delay = RETRY_DELAYS_S[min(attempt - 1, len(RETRY_DELAYS_S) - 1)]
                self._set(job_id, status="queued", progress=0.0, not_before=time.time() + delay,
                          error=f"Attempt {attempt} failed, retrying in {delay}s: {e}")
                log.warning("Download %s failed (attempt %d), retrying: %s", job["video_id"], attempt, e)
            else:
                self._set(job_id, status="failed", error=str(e))
                log.warning("Download %s failed: %s", job["video_id"], e)
        finally:
            with self._lock:
                self._cancel.discard(job_id)
