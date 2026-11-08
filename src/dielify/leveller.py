"""Volume levelling: every song's loudness, measured once, so the players can even out
loud and quiet songs (like ReplayGain / Spotify's "normalise volume").

FFmpeg's EBU R128 meter reads each file (no changes to the files); the integrated loudness
(LUFS) goes into tracks.loudness. A background thread works through songs that don't
have one yet (new downloads, files that changed), one at a time at low priority.
Players get `gain_db` = TARGET_LUFS - loudness (clamped).
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .library import connect
from . import settings as settings_mod

log = logging.getLogger(__name__)

TARGET_LUFS = -14.0      # what Spotify / YouTube aim for
MIN_GAIN, MAX_GAIN = -20.0, 8.0
_SUMMARY = re.compile(r"Integrated loudness:\s*I:\s*(-?[\d.]+|-inf)\s*LUFS")
_PAUSE_S = 0.3           # between files, so the PC stays quiet
_IDLE_S = 120            # nothing to measure: look again after this


def gain_db(loudness: float | None) -> float | None:
    if loudness is None or loudness <= -70:
        return None
    return round(max(MIN_GAIN, min(MAX_GAIN, TARGET_LUFS - loudness)), 1)


def measure(path: Path) -> float | None:
    """Integrated loudness in LUFS (None: silent or unreadable)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("FFmpeg not found")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
    r = subprocess.run([ffmpeg, "-nostats", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128=framelog=quiet",
                        "-f", "null", "-"], capture_output=True, text=True, errors="replace", timeout=600,
                       creationflags=flags)
    m = _SUMMARY.search(r.stderr)
    if not m or m.group(1) == "-inf":
        return None
    return float(m.group(1))


class Leveller:
    """Measures songs without a loudness yet, in the background."""

    def __init__(self):
        self._stop = threading.Event()
        self._wake = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="dielify-leveller", daemon=True).start()

    def stop(self) -> None:
        self._stop.set(); self._wake.set()

    def nudge(self) -> None:
        """A song was just downloaded: measure it soon."""
        self._wake.set()

    def _next(self):
        with connect() as conn:
            return conn.execute("SELECT id, profile, relpath FROM tracks WHERE loudness IS NULL "
                                "ORDER BY created_at DESC LIMIT 1").fetchone()

    def run_once(self) -> bool:
        """Measure one song. False: nothing left to do."""
        row = self._next()
        if row is None:
            return False
        path = settings_mod.load().profile_library(row["profile"]) / Path(row["relpath"])
        try:
            lufs = measure(path) if path.exists() else None
        except FileNotFoundError:
            raise
        except Exception as e:  # noqa: BLE001  (a bad file shouldn't stop the rest)
            log.info("Leveller: couldn't measure %s: %s", path.name, e)
            lufs = None
        with connect() as conn:  # -99 = measured, nothing usable (silent / unreadable)
            conn.execute("UPDATE tracks SET loudness = ? WHERE id = ?", (lufs if lufs is not None else -99.0, row["id"]))
        return True

    def _loop(self) -> None:
        self._stop.wait(20)  # let the app start first
        done = 0
        while not self._stop.is_set():
            try:
                if self.run_once():
                    done += 1
                    if done % 200 == 0:
                        log.info("Leveller: %d songs measured so far", done)
                    self._stop.wait(_PAUSE_S)
                    continue
            except FileNotFoundError:
                log.warning("Leveller: FFmpeg not found, volume levelling is off")
                return
            except Exception as e:  # noqa: BLE001
                log.warning("Leveller: %s", e)
            if done:
                log.info("Leveller: all songs measured (%d this run)", done)
                done = 0
            self._wake.wait(_IDLE_S)
            self._wake.clear()
