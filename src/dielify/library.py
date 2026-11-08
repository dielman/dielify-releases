"""SQLite index of each profile's music folder.

The audio files are the source of truth: everything here can be rebuilt with a
scan. Only listening data (play counts, stars, pins) lives solely in the database.
Paths are stored relative to the profile's folder, so moving `library_root` keeps
play counts and stars.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .downloader import AUDIO_EXTS
from .paths import app_data_dir
from .tagging import read_tags

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    id         INTEGER PRIMARY KEY,
    profile    TEXT NOT NULL,
    name       TEXT NOT NULL,
    starred_at REAL,
    UNIQUE (profile, name)
);
CREATE TABLE IF NOT EXISTS albums (
    id         INTEGER PRIMARY KEY,
    profile    TEXT NOT NULL,
    artist_id  INTEGER NOT NULL REFERENCES artists(id),
    name       TEXT NOT NULL,
    created_at REAL NOT NULL,
    starred_at REAL,
    UNIQUE (artist_id, name)
);
CREATE TABLE IF NOT EXISTS tracks (
    id           INTEGER PRIMARY KEY,
    profile      TEXT NOT NULL,
    relpath      TEXT NOT NULL,          -- posix-style, relative to the profile folder
    album_id     INTEGER NOT NULL REFERENCES albums(id),
    artist_id    INTEGER NOT NULL REFERENCES artists(id),  -- album artist
    title        TEXT NOT NULL,
    artist       TEXT NOT NULL,          -- track artist(s), for display
    year         INTEGER,
    track_no     INTEGER,
    duration_s   INTEGER,
    bitrate_kbps INTEGER,
    suffix       TEXT NOT NULL,
    size         INTEGER NOT NULL,
    mtime        REAL NOT NULL,
    video_id     TEXT,
    has_cover    INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    play_count   INTEGER NOT NULL DEFAULT 0,
    last_played  REAL,
    starred_at   REAL,
    pinned       INTEGER NOT NULL DEFAULT 0,  -- never evicted by the cache limit
    UNIQUE (profile, relpath)
);
CREATE INDEX IF NOT EXISTS tracks_album ON tracks(album_id);
CREATE INDEX IF NOT EXISTS tracks_video ON tracks(profile, video_id);

-- Download queue (downloads.py): one row per track.
CREATE TABLE IF NOT EXISTS downloads (
    id            INTEGER PRIMARY KEY,
    profile       TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    title         TEXT NOT NULL,
    artist        TEXT,
    album         TEXT,
    request_id    TEXT NOT NULL,   -- groups the tracks of one album/playlist request
    request_type  TEXT NOT NULL,   -- song | video | album | playlist
    request_title TEXT,
    requested_by  TEXT,
    status        TEXT NOT NULL,   -- queued downloading processing done failed cancelled
    progress      REAL NOT NULL DEFAULT 0,
    error         TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    not_before    REAL NOT NULL DEFAULT 0,  -- retry back-off
    track_id      INTEGER,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS downloads_status ON downloads(status, not_before);

-- Play history (history.py): one row per play or skip.
CREATE TABLE IF NOT EXISTS plays (
    id          INTEGER PRIMARY KEY,
    profile     TEXT NOT NULL,
    client_id   TEXT,                 -- set by the phone so a resend isn't counted twice
    track_id    INTEGER,              -- library track, if it is (or later is) downloaded
    video_id    TEXT,
    title       TEXT NOT NULL,
    artist      TEXT,
    album       TEXT,
    duration_s  INTEGER,
    played_s    INTEGER,              -- how much was actually heard (NULL = unknown, counted)
    counted     INTEGER NOT NULL,
    started_at  REAL NOT NULL,
    device      TEXT,
    UNIQUE (profile, client_id)
);
CREATE INDEX IF NOT EXISTS plays_when ON plays(profile, started_at);

-- Playlists (playlists.py). yt_id set = synced with that YouTube Music playlist.
CREATE TABLE IF NOT EXISTS playlists (
    id          INTEGER PRIMARY KEY,
    profile     TEXT NOT NULL,
    name        TEXT NOT NULL,
    yt_id       TEXT,
    read_only   INTEGER NOT NULL DEFAULT 0,   -- e.g. Liked Music: synced one way only
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    synced_at   REAL,
    sync_error  TEXT,
    UNIQUE (profile, yt_id)
);
CREATE TABLE IF NOT EXISTS playlist_items (
    id            INTEGER PRIMARY KEY,
    playlist_id   INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    video_id      TEXT NOT NULL,
    set_video_id  TEXT,               -- YouTube's id for this entry (needed to remove it)
    title         TEXT NOT NULL,
    artist        TEXT,
    album         TEXT,
    duration_s    INTEGER,
    thumbnail     TEXT,
    added_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS playlist_items_list ON playlist_items(playlist_id, position);
-- Edits not yet sent to YouTube (it couldn't be reached); retried on the next sync.
CREATE TABLE IF NOT EXISTS playlist_ops (
    id           INTEGER PRIMARY KEY,
    playlist_id  INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    op           TEXT NOT NULL,        -- add | remove | rename
    video_id     TEXT,
    set_video_id TEXT,
    title        TEXT,
    created_at   REAL NOT NULL,
    error        TEXT
);

-- Artist genres from MusicBrainz (tags.py); tags = JSON [[name, count], ...].
CREATE TABLE IF NOT EXISTS artist_tags (
    name_key   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    mbid       TEXT,
    tags       TEXT,
    fetched_at REAL NOT NULL
);

-- Logins for our own API (auth.py): only a hash of each token is kept.
CREATE TABLE IF NOT EXISTS device_tokens (
    id           INTEGER PRIMARY KEY,
    username     TEXT NOT NULL,
    device_name  TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    created_at   REAL NOT NULL,
    last_used_at REAL
);
"""

CONTENT_TYPES = {".m4a": "audio/mp4", ".opus": "audio/ogg", ".ogg": "audio/ogg",
                 ".mp3": "audio/mpeg", ".flac": "audio/flac"}


def db_path() -> Path:
    path = app_data_dir() / "dielify.db"
    legacy = path.with_name("ymp.db")  # the database's name before the rename to Dielify
    if not path.exists() and legacy.exists():
        for suffix in ("", "-wal", "-shm"):
            old = legacy.with_name(legacy.name + suffix)
            if old.exists():
                old.rename(path.with_name(path.name + suffix))
    return path


def _fold(text: str | None) -> str | None:
    return text.casefold() if text else text


def _migrate(conn: sqlite3.Connection) -> None:
    """Columns added after the first release (CREATE TABLE IF NOT EXISTS won't add them)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(downloads)")}
    if "priority" not in cols:  # 0.6: "download next" (1 = jump the queue)
        conn.execute("ALTER TABLE downloads ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(playlists)")}
    if "kind" not in pcols:  # 0.8.2: Dielify-made mixes are playlists too
        conn.execute("ALTER TABLE playlists ADD COLUMN kind TEXT NOT NULL DEFAULT 'user'")
        conn.execute("ALTER TABLE playlists ADD COLUMN mix_key TEXT")
        conn.execute("ALTER TABLE playlists ADD COLUMN description TEXT")


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.create_function("fold", 1, _fold, deterministic=True)  # Unicode-aware lower()
    conn.executescript(SCHEMA)
    _migrate(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)


def _year(text) -> int | None:
    text = str(text or "")
    return int(text[:4]) if text[:4].isdigit() else None


class Library:
    """One profile's music: `root` is that profile's folder (Artist/Album/Track)."""

    def __init__(self, profile: str, root: Path):
        self.profile = profile
        self.root = Path(root)

    def path_of(self, track: sqlite3.Row) -> Path:
        return self.root / Path(track["relpath"])

    # --- indexing -------------------------------------------------------------

    def _audio_files(self):
        if not self.root.exists():
            return
        for path in self.root.rglob("*"):
            if path.suffix.lower() not in AUDIO_EXTS or not path.is_file():
                continue
            if any(part.startswith(".dielify-dl-") for part in path.relative_to(self.root).parts):
                continue  # download still in progress
            yield path

    def scan(self) -> ScanResult:
        res = ScanResult()
        with connect() as conn:
            known = {r["relpath"]: r for r in conn.execute(
                "SELECT id, relpath, size, mtime, video_id FROM tracks WHERE profile = ?",
                (self.profile,))}
            seen: set[str] = set()
            new_files = []
            for path in self._audio_files():
                rel = path.relative_to(self.root).as_posix()
                seen.add(rel)
                st = path.stat()
                row = known.get(rel)
                if row and row["size"] == st.st_size and row["mtime"] == st.st_mtime:
                    res.unchanged += 1
                    continue
                new_files.append((path, rel, row))
            # Files that disappeared; a re-download under a new name (e.g. .m4a ->
            # .opus) takes over the old row so play counts and stars survive.
            gone = {rel: row for rel, row in known.items() if rel not in seen}
            gone_by_video = {row["video_id"]: row for row in gone.values() if row["video_id"]}
            for path, rel, row in new_files:
                try:
                    tags = read_tags(path)
                except Exception as e:  # unreadable or untagged oddity: report, keep going
                    res.errors.append(f"{rel}: {e}")
                    continue
                if row is None and tags.get("video_id") in gone_by_video:
                    row = gone_by_video.pop(tags["video_id"])
                    gone.pop(row["relpath"], None)
                self._upsert(conn, path, rel, tags, row["id"] if row else None)
                if row:
                    res.updated += 1
                else:
                    res.added += 1
            for row in gone.values():
                conn.execute("DELETE FROM tracks WHERE id = ?", (row["id"],))
                res.removed += 1
            self._prune(conn)
        return res

    def index_file(self, path: Path) -> int:
        """Add or refresh one file (called right after a download)."""
        rel = Path(path).relative_to(self.root).as_posix()
        tags = read_tags(Path(path))
        with connect() as conn:
            row = conn.execute("SELECT id FROM tracks WHERE profile = ? AND relpath = ?",
                               (self.profile, rel)).fetchone()
            if row is None and tags.get("video_id"):
                row = conn.execute("SELECT id FROM tracks WHERE profile = ? AND video_id = ?",
                                   (self.profile, tags["video_id"])).fetchone()
            track_id = self._upsert(conn, Path(path), rel, tags, row["id"] if row else None)
            self._prune(conn)
        return track_id

    def _upsert(self, conn, path: Path, rel: str, tags: dict, track_id: int | None) -> int:
        parts = Path(rel).parts
        folder_artist = parts[0] if len(parts) >= 3 else None
        folder_album = parts[1] if len(parts) >= 3 else None
        artist = tags.get("artist") or folder_artist or "Unknown Artist"
        album_artist = tags.get("album_artist") or artist
        album = tags.get("album") or folder_album or "Singles"
        now = time.time()

        conn.execute("INSERT OR IGNORE INTO artists (profile, name) VALUES (?, ?)",
                     (self.profile, album_artist))
        artist_id = conn.execute("SELECT id FROM artists WHERE profile = ? AND name = ?",
                                 (self.profile, album_artist)).fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO albums (profile, artist_id, name, created_at) "
                     "VALUES (?, ?, ?, ?)", (self.profile, artist_id, album, now))
        album_id = conn.execute("SELECT id FROM albums WHERE artist_id = ? AND name = ?",
                                (artist_id, album)).fetchone()["id"]

        st = path.stat()
        values = dict(profile=self.profile, relpath=rel, album_id=album_id, artist_id=artist_id,
                      title=tags.get("title") or path.stem, artist=artist,
                      year=_year(tags.get("year")), track_no=tags.get("track"),
                      duration_s=round(tags["length_s"]) if tags.get("length_s") else None,
                      bitrate_kbps=tags.get("bitrate_kbps"), suffix=path.suffix.lower().lstrip("."),
                      size=st.st_size, mtime=st.st_mtime, video_id=tags.get("video_id"),
                      has_cover=int(bool(tags.get("cover_bytes"))))
        if track_id is None:
            values["created_at"] = now
            cols = ", ".join(values)
            marks = ", ".join("?" * len(values))
            return conn.execute(f"INSERT INTO tracks ({cols}) VALUES ({marks})",
                                tuple(values.values())).lastrowid
        sets = ", ".join(f"{k} = ?" for k in values)
        conn.execute(f"UPDATE tracks SET {sets} WHERE id = ?", (*values.values(), track_id))
        return track_id

    def _prune(self, conn) -> None:
        conn.execute("DELETE FROM albums WHERE profile = ? AND id NOT IN "
                     "(SELECT DISTINCT album_id FROM tracks WHERE profile = ?)",
                     (self.profile, self.profile))
        conn.execute("DELETE FROM artists WHERE profile = ? AND id NOT IN "
                     "(SELECT DISTINCT artist_id FROM albums WHERE profile = ?)",
                     (self.profile, self.profile))

    # --- queries (all scoped to this profile) -----------------------------------

    _TRACK_SELECT = """
        SELECT t.*, al.name AS album, ar.name AS album_artist
        FROM tracks t JOIN albums al ON al.id = t.album_id JOIN artists ar ON ar.id = t.artist_id
        WHERE t.profile = :p"""

    _ALBUM_SELECT = """
        SELECT al.*, ar.name AS artist,
               COUNT(t.id) AS song_count, COALESCE(SUM(t.duration_s), 0) AS duration,
               MAX(t.year) AS year, COALESCE(SUM(t.play_count), 0) AS play_count,
               MAX(t.last_played) AS last_played,
               (SELECT id FROM tracks c WHERE c.album_id = al.id AND c.has_cover = 1
                ORDER BY c.track_no LIMIT 1) AS cover_track_id
        FROM albums al JOIN artists ar ON ar.id = al.artist_id
        LEFT JOIN tracks t ON t.album_id = al.id
        WHERE al.profile = :p"""

    _ARTIST_SELECT = """
        SELECT ar.*, COUNT(al.id) AS album_count, MIN(al.id) AS first_album_id
        FROM artists ar LEFT JOIN albums al ON al.artist_id = ar.id
        WHERE ar.profile = :p"""

    def _q(self, sql: str, **params) -> list[sqlite3.Row]:
        with connect() as conn:
            return conn.execute(sql, {"p": self.profile, **params}).fetchall()

    def artists(self) -> list[sqlite3.Row]:
        return self._q(self._ARTIST_SELECT + " GROUP BY ar.id ORDER BY fold(ar.name)")

    def artist(self, artist_id: int) -> sqlite3.Row | None:
        rows = self._q(self._ARTIST_SELECT + " AND ar.id = :id GROUP BY ar.id", id=artist_id)
        return rows[0] if rows else None

    def albums_by_artist(self, artist_id: int) -> list[sqlite3.Row]:
        return self._q(self._ALBUM_SELECT + " AND al.artist_id = :id GROUP BY al.id "
                       "ORDER BY year, fold(al.name)", id=artist_id)

    def album(self, album_id: int) -> sqlite3.Row | None:
        rows = self._q(self._ALBUM_SELECT + " AND al.id = :id GROUP BY al.id", id=album_id)
        return rows[0] if rows else None

    def tracks_on_album(self, album_id: int) -> list[sqlite3.Row]:
        return self._q(self._TRACK_SELECT + " AND t.album_id = :id "
                       "ORDER BY t.track_no, fold(t.title)", id=album_id)

    def track(self, track_id: int) -> sqlite3.Row | None:
        rows = self._q(self._TRACK_SELECT + " AND t.id = :id", id=track_id)
        return rows[0] if rows else None

    def album_list(self, kind: str, size: int = 10, offset: int = 0,
                   from_year: int | None = None, to_year: int | None = None) -> list[sqlite3.Row]:
        where, order = "", {
            "newest": "al.created_at DESC",
            "alphabeticalByName": "fold(al.name)",
            "alphabeticalByArtist": "fold(ar.name), year, fold(al.name)",
            "frequent": "play_count DESC",
            "highest": "play_count DESC",
            "recent": "last_played DESC",
            "starred": "fold(al.name)",
            "random": "RANDOM()",
        }.get(kind)
        if kind == "byYear":
            lo, hi = from_year or 0, to_year or 9999
            order = "year DESC" if lo > hi else "year"
            lo, hi = min(lo, hi), max(lo, hi)
            where = f" HAVING year BETWEEN {int(lo)} AND {int(hi)}"
        elif kind == "starred":
            where = " HAVING al.starred_at IS NOT NULL"
        elif kind in ("frequent", "highest"):
            where = " HAVING play_count > 0"
        elif kind == "recent":
            where = " HAVING last_played IS NOT NULL"
        if order is None:  # byGenre and anything unknown: no genres yet
            return []
        return self._q(self._ALBUM_SELECT + f" GROUP BY al.id{where} ORDER BY {order} "
                       "LIMIT :size OFFSET :offset", size=size, offset=offset)

    def search(self, query: str, artist_count=20, artist_offset=0, album_count=20,
               album_offset=0, song_count=20, song_offset=0) -> tuple[list, list, list]:
        """Case-insensitive substring search. An empty query returns everything
        (Symfonium and others sync the whole library this way)."""
        q = query.strip().strip('"').casefold()
        like = f"%{q}%"
        artists = self._q(self._ARTIST_SELECT + " AND fold(ar.name) LIKE :q GROUP BY ar.id "
                          "ORDER BY fold(ar.name) LIMIT :n OFFSET :o",
                          q=like, n=artist_count, o=artist_offset) if artist_count else []
        albums = self._q(self._ALBUM_SELECT + " AND (fold(al.name) LIKE :q OR fold(ar.name) LIKE :q) "
                         "GROUP BY al.id ORDER BY fold(al.name) LIMIT :n OFFSET :o",
                         q=like, n=album_count, o=album_offset) if album_count else []
        songs = self._q(self._TRACK_SELECT + " AND (fold(t.title) LIKE :q OR fold(t.artist) LIKE :q "
                        "OR fold(al.name) LIKE :q) ORDER BY fold(t.artist), fold(al.name), t.track_no "
                        "LIMIT :n OFFSET :o", q=like, n=song_count, o=song_offset) if song_count else []
        return artists, albums, songs

    def track_by_video(self, video_id: str) -> sqlite3.Row | None:
        rows = self._q(self._TRACK_SELECT + " AND t.video_id = :v ORDER BY t.id LIMIT 1", v=video_id)
        return rows[0] if rows else None

    def video_ids(self) -> dict[str, int]:
        """video id -> track id, for marking discovery results already downloaded."""
        return {r["video_id"]: r["id"] for r in self._q(
            "SELECT video_id, id FROM tracks WHERE profile = :p AND video_id IS NOT NULL")}

    def random_tracks(self, size: int) -> list[sqlite3.Row]:
        rows = self._q(self._TRACK_SELECT)
        return random.sample(rows, min(size, len(rows)))

    def starred(self) -> tuple[list, list, list]:
        return (self._q(self._ARTIST_SELECT + " AND ar.starred_at IS NOT NULL GROUP BY ar.id"),
                self._q(self._ALBUM_SELECT + " AND al.starred_at IS NOT NULL GROUP BY al.id"),
                self._q(self._TRACK_SELECT + " AND t.starred_at IS NOT NULL"))

    def set_starred(self, table: str, item_id: int, starred: bool) -> None:
        assert table in ("tracks", "albums", "artists")
        with connect() as conn:
            conn.execute(f"UPDATE {table} SET starred_at = ? WHERE id = ? AND profile = ?",
                         (time.time() if starred else None, item_id, self.profile))

    def record_play(self, track_id: int, when: float | None = None) -> None:
        with connect() as conn:
            conn.execute("UPDATE tracks SET play_count = play_count + 1, last_played = ? "
                         "WHERE id = ? AND profile = ?", (when or time.time(), track_id, self.profile))

    def stats(self) -> dict:
        with connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS tracks, COALESCE(SUM(size), 0) AS bytes, "
                "COUNT(DISTINCT album_id) AS albums, COUNT(DISTINCT artist_id) AS artists "
                "FROM tracks WHERE profile = ?", (self.profile,)).fetchone()
        return dict(row)
