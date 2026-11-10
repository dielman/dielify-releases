"""Backups of Dielify's own data (not the music): database, settings and login files.

A backup is one zip file, dielify-backup-<date>_<time>.zip, in the folder chosen in
Settings. One is made when Dielify starts if the last is over a day old, then daily
while it runs; the newest KEEP are kept.

What's inside, and why it's safe to keep on a data drive:
  dielify.db       play counts, stars, the download queue, phone sign-ins (only token
                   hashes), the library index
  settings.json    music folder, quality, ...
  credentials/     YouTube sign-ins     } encrypted with Windows DPAPI: only this Windows
  server_users/    phone logins         } user on this PC can read them

The music files aren't included: they carry their own tags and cover art, and a library
scan rebuilds the index from them.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import settings as settings_mod
from .library import db_path
from .paths import app_data_dir

log = logging.getLogger(__name__)

PREFIX = "dielify-backup-"
KEEP = 14
EVERY_S = 24 * 3600
STORES = ("credentials", "server_users")

README = """Dielify backup ({when})

Restore (Dielify must be closed: right-click the tray icon > Quit):
    dielify-cli backup restore "<this file>"
That puts back the database, settings and login files. The music isn't in here; it
stays in your music folder.
Login files only work for the same Windows user on the same PC.
"""


def backups(folder: Path) -> list[Path]:
    """Existing backups, oldest first."""
    return sorted(folder.glob(PREFIX + "*.zip")) if folder.is_dir() else []


def last_backup(folder: Path) -> Path | None:
    found = backups(folder)
    return found[-1] if found else None


def is_due(folder: Path) -> bool:
    last = last_backup(folder)
    return last is None or time.time() - last.stat().st_mtime > EVERY_S


def make_backup(folder: Path, prune: bool = True) -> Path:
    """Write a new backup into `folder` and (prune) drop old ones beyond KEEP."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = f"{PREFIX}{datetime.now():%Y-%m-%d_%H%M%S}"
    name, n = f"{stamp}.zip", 1
    while (folder / name).exists():  # never overwrite an existing backup
        n += 1
        name = f"{stamp}-{n}.zip"
    target = folder / name
    part = folder / (name + ".part")
    data = app_data_dir()
    with tempfile.TemporaryDirectory() as td:
        db_copy = Path(td) / "dielify.db"
        if db_path().exists():
            src = sqlite3.connect(db_path(), timeout=30)
            dst = sqlite3.connect(db_copy)
            try:
                src.backup(dst)  # a consistent copy even while Dielify is writing
            finally:
                dst.close()
                src.close()
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("README.txt", README.format(when=datetime.now().strftime("%d %b %Y %H:%M")))
            if db_copy.exists():
                z.write(db_copy, "dielify.db")
            if settings_mod.settings_path().exists():
                z.write(settings_mod.settings_path(), "settings.json")
            for store in STORES:
                for f in sorted((data / store).glob("*.dpapi")):
                    z.write(f, f"{store}/{f.name}")
    _replace(part, target)
    if prune:
        for old in backups(folder)[:-KEEP]:
            old.unlink(missing_ok=True)
    log.info("Backup written: %s", target)
    return target


def _replace(src: Path, dst: Path, tries: int = 20) -> None:
    """Rename, retrying briefly: right after a file is written, Windows (e.g. a virus
    scanner taking a look) can hold it for a moment."""
    for i in range(tries):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.25)


def check(zip_path: Path) -> str | None:
    """None if this is a Dielify backup, else what's wrong (in words for the wizard)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            if "dielify.db" not in z.namelist():
                return "That file isn't a Dielify backup."
            if z.testzip() is not None:
                return "That backup is damaged."
    except FileNotFoundError:
        return "That file can't be found."
    except (zipfile.BadZipFile, OSError):
        return "That file isn't a Dielify backup."
    return None


def restore(zip_path: Path) -> Path:
    """Put a backup's database, settings and login files back. Dielify must be closed.
    The current data is backed up first (into the same folder as `zip_path`); returns
    that safety copy."""
    with zipfile.ZipFile(zip_path) as z:
        if "dielify.db" not in z.namelist():
            raise ValueError(f"{zip_path} isn't a Dielify backup (no dielify.db inside)")
    # before touching anything; no pruning, which could delete the backup being restored
    try:
        safety = make_backup(zip_path.parent, prune=False)
    except OSError:  # e.g. a read-only stick: keep it in Dielify's own folder instead
        safety = make_backup(app_data_dir() / "before-restore", prune=False)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        data = app_data_dir()
        db = db_path()
        for suffix in ("-wal", "-shm"):
            db.with_name(db.name + suffix).unlink(missing_ok=True)
        with z.open("dielify.db") as src, open(db, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if "settings.json" in names:
            with z.open("settings.json") as src, open(settings_mod.settings_path(), "wb") as dst:
                shutil.copyfileobj(src, dst)
        for n in names:
            store, _, fname = n.partition("/")
            if store in STORES and fname.endswith(".dpapi") and "/" not in fname and ".." not in fname:
                (data / store).mkdir(parents=True, exist_ok=True)
                with z.open(n) as src, open(data / store / fname, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    return safety


def suggested_folder(s: settings_mod.Settings | None = None) -> Path:
    """Where backups go unless someone picks a folder: beside the music folder."""
    s = s or settings_mod.load()
    root = Path(s.library_root) if s.library_root else None
    return (root.parent if root and root.parent != root else Path.home()) / "Dielify-backups"


def ensure_default() -> Path | None:
    """Backups are on by default: the first time, use the suggested folder."""
    s = settings_mod.load()
    if s.backup_folder or s.backup_chosen:
        return Path(s.backup_folder) if s.backup_folder else None
    folder = suggested_folder(s)
    settings_mod.set_value("backup_folder", str(folder))
    settings_mod.set_value("backup_chosen", "true")
    log.info("Backups turned on by default: %s", folder)
    return folder


class BackupScheduler:
    """Checks hourly; backs up when the last backup is over a day old."""

    def __init__(self) -> None:
        self.last_error: str | None = None
        self._stop = threading.Event()

    def folder(self) -> Path | None:
        f = settings_mod.load().backup_folder
        return Path(f) if f else None

    def run_once(self) -> Path | None:
        folder = self.folder()
        if folder is None or not is_due(folder):
            return None
        try:
            path = make_backup(folder)
            self.last_error = None
            return path
        except Exception as e:  # never take the app down over a backup
            self.last_error = f"{type(e).__name__}: {e}"
            log.exception("Backup failed")
            return None

    def _loop(self) -> None:
        self._stop.wait(60)  # let startup finish first
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(3600)

    def start(self) -> None:
        try:
            ensure_default()
        except Exception:  # never take the app down over a backup
            log.exception("Couldn't turn on backups")
        threading.Thread(target=self._loop, daemon=True, name="dielify-backup").start()

    def stop(self) -> None:
        self._stop.set()


scheduler = BackupScheduler()
