"""Is the YouTube account still Premium? (Josh, 21 Nov 2026)

Rules Josh set:
- Downloads NEVER stop. If Premium lapses, everything carries on at standard quality (~128-160 kbps
  instead of ~256); this module only decides when to tell people (a notice in Notifications).
- A lower-quality copy never replaces a higher one (downloader.download_track).
- When Premium is back, songs below Premium quality are downloaded again at full quality and
  replace the lower copies (upgrades.py).

How it's spotted: with Premium, YouTube offers the 256 kbps formats (itag 774 Opus, 141 AAC) on
music; without, it doesn't. Every download and instant play reports what YouTube offered
(yt_adapter). One song without them proves nothing (some videos never have them), so after
MISSES_TO_CHECK in a row the adapter re-checks a song that had them before: still there = those were
odd songs; gone = lapsed. With no earlier song to re-check, MISSES_TO_LAPSE in a row decides.
The first song with Premium formats ends it."""

from __future__ import annotations

import logging
import threading
import time

from .library import connect

log = logging.getLogger(__name__)

PREMIUM_ITAGS = {"774", "141"}
MISSES_TO_CHECK = 3
MISSES_TO_LAPSE = 8
LOW_KBPS = 200  # below this a file isn't Premium quality (Premium Opus is ~250-270 kbps)

_lock = threading.Lock()
_on_back: list = []  # called with the account when Premium returns (upgrades.Worker.kick)


def has_premium_formats(formats: list[dict]) -> bool:
    return any(str(f.get("format_id") or "").split("-")[0] in PREMIUM_ITAGS for f in formats or [])


def state(account: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM premium_state WHERE account = ?", (account,)).fetchone()
    return dict(row) if row else {"account": account, "premium": None, "misses": 0, "ref_video": None,
                                  "changed_at": None}


def is_premium(account: str) -> bool | None:
    """True / False once known; None before any download or instant play has shown it."""
    p = state(account)["premium"]
    return None if p is None else bool(p)


def _save(conn, s: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO premium_state (account, premium, misses, ref_video, changed_at, checked_at) "
                 "VALUES (?,?,?,?,?,?)", (s["account"], s["premium"], s["misses"], s["ref_video"], s["changed_at"],
                                          time.time()))


def observe(account: str, premium: bool, video_id: str) -> str | None:
    """What YouTube offered for one song. Returns a video id to re-check (an earlier song that had
    Premium formats) when it's starting to look lapsed, else None."""
    back = False
    with _lock, connect() as conn:
        s = state(account)
        if premium:
            back = s["premium"] == 0
            if s["premium"] != 1:
                s["changed_at"] = time.time()
            s.update(premium=1, misses=0, ref_video=video_id)
            _save(conn, s)
        else:
            s["misses"] += 1
            check = None
            if s["premium"] != 0:
                if s["ref_video"] and s["ref_video"] != video_id and s["misses"] >= MISSES_TO_CHECK:
                    check = s["ref_video"]
                elif s["misses"] >= MISSES_TO_LAPSE:
                    _lapse(conn, s)
            _save(conn, s)
            return check
    if back:
        _returned(account)
    return None


def confirm(account: str, ref_has_premium: bool) -> None:
    """The re-check of an earlier Premium song: still Premium formats = the misses were odd songs."""
    with _lock, connect() as conn:
        s = state(account)
        if ref_has_premium:
            s["misses"] = 0
        elif s["premium"] != 0:
            _lapse(conn, s)
        _save(conn, s)


def _lapse(conn, s: dict) -> None:
    from . import notices
    s.update(premium=0, changed_at=time.time())
    log.warning("YouTube Music Premium seems to have lapsed for %s: downloads carry on at standard quality",
                s["account"])
    notices.remove(f"premium-back:{s['account']}")
    notices.post(
        f"premium-lapsed:{s['account']}", s["account"],
        "YouTube Music Premium has lapsed",
        "The YouTube account Dielify uses no longer has Premium. Downloads and instant play carry on at "
        "standard quality (about 128-160 kbps instead of 256). Songs you already have keep their quality: "
        "Dielify never replaces a better copy with a worse one. When Premium is back, Dielify notices by "
        "itself and downloads the lower-quality songs again at full quality.")


def _returned(account: str) -> None:
    from . import notices
    log.info("YouTube Music Premium is back for %s", account)
    notices.remove(f"premium-lapsed:{account}")
    with connect() as conn:
        low = conn.execute("SELECT COUNT(*) FROM tracks WHERE profile = ? COLLATE NOCASE AND video_id IS NOT NULL "
                           "AND bitrate_kbps IS NOT NULL AND bitrate_kbps < ?", (account, LOW_KBPS)).fetchone()[0]
    notices.post(
        f"premium-back:{account}", account, "YouTube Music Premium is back",
        "Downloads are at full quality again." + (
            f" {low} song{'s' if low != 1 else ''} below Premium quality will be downloaded again at full quality "
            "and replace the lower-quality copies (after your other downloads)." if low else ""),
        level=notices.INFO)
    for fn in list(_on_back):
        try:
            fn(account)
        except Exception as e:  # noqa: BLE001
            log.warning("After Premium came back: %s", e)
