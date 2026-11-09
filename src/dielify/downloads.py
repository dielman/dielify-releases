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
from .library import connect, library_for
from .yt_adapter import NotSignedIn, Offline, YTItem, YTMusicAdapter

log = logging.getLogger(__name__)

ACTIVE = ("queued", "downloading", "processing")
WAITING = ("approval", "queued", "downloading", "processing")  # approval: a kids account's request, waiting for a parent
FINISHED = ("done", "failed", "cancelled")
MAX_ATTEMPTS = 3
RETRY_DELAYS_S = (30, 120)  # wait before the 2nd and 3rd attempt
SIGNIN_CHECK_S = 600        # re-confirm the YouTube sign-in at most this often
NEXT_ORDER = "CASE WHEN priority > 0 THEN 0 ELSE 1 END, priority, id"  # "next" first, in order
SIGNIN_WAIT_S = 300         # while signed out (or offline), check again this often, ONCE
                            # per profile, not once per waiting download


class _Cancelled(Exception):
    pass


def _default_adapter(profile: str) -> YTMusicAdapter:
    from .library import signin_of
    auth = credstore.load(signin_of(profile))  # a child downloads with the parent's sign-in
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
        self._served: dict[str, float] = {}  # profile -> when its last download started (turns)
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
            for tmp in library_for(r["profile"], s).root.glob(".dielify-dl-*"):
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
                request_title: str | None = None, requested_by: str | None = None,
                next_up: bool = False) -> list[dict]:
        """Queue songs/videos. Ones already in the library, or already queued, aren't
        downloaded twice. next_up: put them ahead of everything else that's waiting
        (after earlier "next" requests); an already-waiting song is moved up too."""
        # priority = when it was marked "next" (ms); 0 = normal. "Next" ones go first, in
        # the order they were marked.
        priority = int(time.time() * 1000) if next_up else 0
        lib = library_for(profile)
        in_library = lib.video_ids()
        in_store = lib.store_video_ids()  # already on the PC for someone else: no download
        kid = None
        if lib.role == "child":  # a kids account: the parent's controls decide (kids.py)
            from . import kids
            controls = kids.load(lib.profile)
            kid = {"filter": kids.KidFilter(lib.profile), "c": controls,
                   "left": controls.daily_limit - kids.downloads_today(profile)}
        for item in items:
            if item.id in in_store and item.id not in in_library:
                if kid and kid["filter"].why_not(item.id, item.title, item.artists, item.explicit) is not None:
                    continue
                if lib.add(in_store[item.id], "download"):
                    in_library[item.id] = in_store[item.id]
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
                    "('approval', 'queued', 'downloading', 'processing')", (profile, item.id)).fetchone()
                if existing:
                    if next_up:
                        conn.execute("UPDATE downloads SET priority = ? WHERE id = ? AND priority = 0",
                                     (priority, existing["id"]))
                    ids.append(existing["id"])
                    continue
                done = item.id in in_library
                status, error = ("done" if done else "queued"), None if done else hold_reason
                if kid and not done:
                    reason = kid["filter"].why_not(item.id, item.title, item.artists, item.explicit)
                    if reason and reason != "not checked yet":  # unchecked ones are checked before downloading
                        status, error = "failed", f"Not allowed in your account ({reason})"
                    elif kid["left"] <= 0:
                        status, error = "failed", (f"Daily download limit reached ({kid['c'].daily_limit} songs). "
                                                   "Try again tomorrow.")
                    else:
                        kid["left"] -= 1
                        if kid["c"].downloads == "approve":
                            status, error = "approval", "Waiting for a parent's OK"
                ids.append(conn.execute(
                    "INSERT INTO downloads (profile, video_id, title, artist, album, request_id, "
                    "request_type, request_title, requested_by, status, progress, track_id, "
                    "not_before, error, created_at, updated_at, priority) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (profile, item.id, item.title, ", ".join(item.artists) or None, item.album,
                     request_id, request_type, request_title or item.title, requested_by,
                     status, 1.0 if done else 0.0,
                     in_library.get(item.id), 0.0 if done else hold_until,
                     error, now, now, priority)).lastrowid)
        self._wake.set()
        return [j for j in (self.get(profile, i) for i in ids) if j]

    def list(self, profile: str, active_only: bool = False, limit: int = 200,
             finished_only: bool = False) -> list[dict]:
        """active_only: in the order they'll download (the running one first).
        finished_only / everything: newest first."""
        if active_only:
            where = " AND status IN ('approval', 'queued', 'downloading', 'processing')"
            order = f"CASE status WHEN 'queued' THEN 1 WHEN 'approval' THEN 2 ELSE 0 END, {NEXT_ORDER}"  # as _next_job
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
                                  "('approval', 'queued', 'downloading', 'processing')", (profile,)).fetchone()[0]
            recent = [r[0] for r in conn.execute(
                "SELECT updated_at FROM downloads WHERE profile = ? AND status = 'done' AND track_id IS NOT NULL "
                "AND attempts > 0 ORDER BY updated_at DESC LIMIT 11", (profile,))]
        gaps = [a - b for a, b in zip(recent, recent[1:]) if 0 < a - b < 600]
        return {"active": active, "seconds_per_song": sum(gaps) / len(gaps) if gaps else None}

    def clear_finished(self, profile: str) -> int:
        """Take downloaded and cancelled songs off the list (the songs stay in the library;
        failed ones stay so you can see what went wrong). Returns how many were removed."""
        with connect() as conn:
            return conn.execute("DELETE FROM downloads WHERE profile = ? AND status IN ('done', 'cancelled')",
                                (profile,)).rowcount

    def get(self, profile: str, job_id: int) -> dict | None:
        with connect() as conn:
            row = conn.execute("SELECT * FROM downloads WHERE id = ? AND profile = ?",
                               (job_id, profile)).fetchone()
        return dict(row) if row else None

    def approvals(self, profiles: list[str]) -> list[dict]:
        """Kids' download requests waiting for a parent's OK (oldest first)."""
        if not profiles:
            return []
        with connect() as conn:
            rows = conn.execute(f"SELECT * FROM downloads WHERE status = 'approval' AND profile IN "
                                f"({','.join('?' * len(profiles))}) ORDER BY id", profiles).fetchall()
        return [dict(r) for r in rows]

    def decide(self, job_ids: list[int], allow: bool) -> int:
        with connect() as conn:
            n = conn.execute(
                f"UPDATE downloads SET status = ?, error = ?, updated_at = ? WHERE status = 'approval' "
                f"AND id IN ({','.join('?' * len(job_ids))})",
                ("queued" if allow else "cancelled", None if allow else "A parent said no",
                 time.time(), *job_ids)).rowcount
        self._wake.set()
        return n

    def move_next(self, profile: str, job_id: int) -> dict | None:
        """Move a waiting download to the front of the line."""
        with connect() as conn:
            conn.execute("UPDATE downloads SET priority = ? WHERE id = ? AND profile = ? AND "
                         "status = 'queued' AND priority = 0", (int(time.time() * 1000), job_id, profile))
        self._wake.set()
        return self.get(profile, job_id)

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
            # Each person's next song (in their own order); then people take turns, so one
            # person's 200-song playlist doesn't hold up everyone else's songs.
            rows = conn.execute(
                "SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY profile "
                f"ORDER BY {NEXT_ORDER}) AS turn FROM downloads WHERE status = 'queued' "
                "AND not_before <= ?) WHERE turn = 1", (now,)).fetchall()
            later = conn.execute("SELECT MIN(not_before) FROM downloads WHERE status = 'queued'"
                                 ).fetchone()[0]
        wait = max(1.0, (later or now + 60) - now)
        if not rows:
            return None, min(wait, 60.0)
        row = min(rows, key=lambda r: (self._served.get(r["profile"], 0.0), r["id"]))
        self._served[row["profile"]] = time.monotonic()
        job = dict(row)
        job.pop("turn", None)
        return job, min(wait, 60.0)

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

    @staticmethod
    def _fetch_lyrics(adapter, video_id: str, info) -> None:
        """Keep the song's lyrics with it (so they show offline). Never fails the download."""
        from . import lyrics
        try:
            if lyrics.cached(video_id)[0]:
                return
            yt = (lambda: adapter.lyrics(video_id, info.lyrics_id)) if info.lyrics_id else None
            lyrics.find(video_id, yt, info.artist, info.title, info.album, info.duration_s)
        except Exception as e:  # noqa: BLE001
            log.info("Lyrics for %s not kept: %s", video_id, e)

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
        lib = library_for(profile)
        if lib.role == "child":  # checked now if it had no explicit mark yet
            from . import kids
            reason = kids.KidFilter(profile, lambda fn, *a: getattr(adapter, fn)(*a), lookups=1).why_not(
                job["video_id"], job["title"], [a.strip() for a in (job["artist"] or "").split(",") if a.strip()])
            if reason and reason != "not checked yet":
                self._set(job_id, status="failed", error=f"Not allowed in your account ({reason})")
                return
        attempt = job["attempts"] + 1
        self._set(job_id, status="downloading", attempts=attempt, error=None, progress=0.0)
        log.info("Downloading %s (%s), attempt %d", job["video_id"], job["title"], attempt)
        try:
            s = settings_mod.load()
            lib = library_for(profile, s)
            res = download_track(adapter, job["video_id"], s, profile, self._progress_hook(job_id))
            track = lib.track_by_video(job["video_id"])
            track_id = track["id"] if track else lib.index_file(res.path)
            if job_id in self._cancel:  # cancelled at the very end: keep the file, report it
                log.info("Job %d finished after cancel was requested", job_id)
            if lib.role == "child":  # the lyrics decide too: kept first, then checked
                from . import kids
                self._fetch_lyrics(adapter, job["video_id"], res.info)
                c = kids.load(profile)
                if c.lyrics_check and kids.lyrics_bad(job["video_id"], c.extra_words):
                    lib.remove_track(track_id)  # out of her library (a child never deletes files)
                    self._set(job_id, status="failed", error="Not allowed in your account (language in the lyrics)",
                              title=res.info.title, artist=res.info.artist, album=res.info.album)
                    return
            self._set(job_id, status="done", progress=1.0, track_id=track_id, error=None,
                      title=res.info.title, artist=res.info.artist, album=res.info.album)
            log.info("Done %s -> track %s", job["video_id"], track_id)
            self._fetch_lyrics(adapter, job["video_id"], res.info)
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
