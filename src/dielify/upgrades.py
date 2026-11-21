"""Songs below Premium quality get a full-quality copy (Josh, 21 Nov 2026): when YouTube Music
Premium is back, or any time the account is Premium and a song in the store is below it (e.g.
downloaded while Premium had lapsed, or with a stale sign-in). The new copy replaces the old file
in place (same song, same plays and playlists) and never if it isn't better (downloader.py).

Runs when premium.py says Premium is back, and every few hours. Only while the account is known to
be Premium: a lapsed account would only get the same quality again. Each song is tried once a
month at most, after everything else waiting (priority -1)."""

from __future__ import annotations

import logging
import threading
import time

from . import premium
from .library import connect

log = logging.getLogger(__name__)

EVERY_S = 6 * 3600
FIRST_RUN_S = 10 * 60
RETRY_AFTER_S = 30 * 86400
BATCH = 200


def run_once(queue) -> int:
    """Queue full-quality copies for every Premium account's lower-quality songs. Returns how many."""
    now, total = time.time(), 0
    with connect() as conn:
        accounts = [r[0] for r in conn.execute("SELECT account FROM premium_state WHERE premium = 1")]
    for account in accounts:
        with connect() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, video_id, title, artist FROM tracks WHERE profile = ? COLLATE NOCASE "
                "AND video_id IS NOT NULL AND bitrate_kbps IS NOT NULL AND bitrate_kbps < ? "
                "AND (upgrade_tried_at IS NULL OR upgrade_tried_at < ?) ORDER BY id LIMIT ?",
                (account, premium.LOW_KBPS, now - RETRY_AFTER_S, BATCH))]
            for r in rows:
                conn.execute("UPDATE tracks SET upgrade_tried_at = ? WHERE id = ?", (now, r["id"]))
        if rows:
            n = queue.enqueue_upgrades(account, rows)
            log.info("Queued %d full-quality copies for %s", n, account)
            total += n
    return total


class Worker:
    def __init__(self, queue):
        self.queue = queue
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._thread: threading.Thread | None = None

    def kick(self, account: str | None = None) -> None:
        self._kick.set()

    def _loop(self) -> None:
        wait = FIRST_RUN_S
        while not self._stop.is_set():
            self._kick.wait(wait)
            if self._stop.is_set():
                return
            self._kick.clear()
            try:
                run_once(self.queue)
            except Exception as e:  # noqa: BLE001
                log.warning("Upgrades: %s", e)
            wait = EVERY_S

    def start(self) -> None:
        premium._on_back.append(self.kick)
        self._thread = threading.Thread(target=self._loop, name="upgrades", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        if self.kick in premium._on_back:
            premium._on_back.remove(self.kick)
