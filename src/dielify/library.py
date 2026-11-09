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

-- Outside discovery (discovery.py): YouTube Music matches for outside songs/artists,
-- and the daily lists (radio charts, ListenBrainz) per profile.
CREATE TABLE IF NOT EXISTS ext_matches (
    key        TEXT PRIMARY KEY,   -- song:<artist>|<title> or artist:<artist>
    item       TEXT,               -- JSON YTItem (or list); NULL = nothing found
    matched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS discovery_lists (
    profile    TEXT NOT NULL,
    key        TEXT NOT NULL,
    title      TEXT NOT NULL,
    subtitle   TEXT,
    items      TEXT NOT NULL,
    position   INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (profile, key)
);

-- Thumbs up / down / ban (ratings.py), per profile, for songs and artists.
CREATE TABLE IF NOT EXISTS ratings (
    profile    TEXT NOT NULL,
    kind       TEXT NOT NULL,      -- song | artist
    key        TEXT NOT NULL,      -- video id (or tr-<id>) | ratings.artist_key(name)
    name       TEXT NOT NULL,      -- for showing it (song: "Title - Artist")
    value      INTEGER NOT NULL,   -- 1 up, -1 down, -2 banned
    updated_at REAL NOT NULL,
    PRIMARY KEY (profile, kind, key)
);

-- Lyrics (lyrics.py), kept so they show offline. key = video id, or tr-<track id> for
-- library songs without one. body = JSON {"lines": [[ms, text], ...] | null, "text": ...};
-- NULL = looked, none found (looked again after a while).
CREATE TABLE IF NOT EXISTS lyrics (
    key        TEXT PRIMARY KEY,
    body       TEXT,
    source     TEXT,
    fetched_at REAL NOT NULL
);

-- Songs never-ending discovery play brought in (explore.py): thumbs down deletes these.
CREATE TABLE IF NOT EXISTS explore_songs (
    profile  TEXT NOT NULL,
    video_id TEXT NOT NULL,
    title    TEXT NOT NULL,
    added_at REAL NOT NULL,
    PRIMARY KEY (profile, video_id)
);

-- People (0.9.1). Files live in a household's music store: tracks.profile is the store's
-- owner (that profile's folder). Each person's library is their own list of songs in the
-- store (library_items), with their own play counts and stars. role: parent | child.
CREATE TABLE IF NOT EXISTS people (
    profile    TEXT PRIMARY KEY COLLATE NOCASE,   -- "Josh" and "josh" are one person
    role       TEXT NOT NULL DEFAULT 'parent',
    store      TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS library_items (
    profile     TEXT NOT NULL,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    added_at    REAL NOT NULL,
    added_by    TEXT,                 -- how it got there: scan | download | <who>
    play_count  INTEGER NOT NULL DEFAULT 0,
    last_played REAL,
    starred_at  REAL,
    pinned      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile, track_id)
);
CREATE INDEX IF NOT EXISTS library_items_track ON library_items(track_id);
-- Starred albums and artists, per person (tracks: library_items.starred_at).
CREATE TABLE IF NOT EXISTS stars (
    profile    TEXT NOT NULL,
    kind       TEXT NOT NULL,         -- album | artist
    item_id    INTEGER NOT NULL,
    starred_at REAL NOT NULL,
    PRIMARY KEY (profile, kind, item_id)
);

-- Kids accounts (kids.py): the parent's controls per child, and YouTube's explicit marks
-- (explicit NULL = looked up, YouTube didn't say; no row = never checked).
CREATE TABLE IF NOT EXISTS kid_controls (
    profile    TEXT PRIMARY KEY COLLATE NOCASE,
    body       TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS yt_flags (
    video_id   TEXT PRIMARY KEY,
    explicit   INTEGER,
    checked_at REAL NOT NULL
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
    tcols = {r[1] for r in conn.execute("PRAGMA table_info(tracks)")}
    if "loudness" not in tcols:  # 0.9: volume levelling (leveller.py); NULL = not measured yet
        conn.execute("ALTER TABLE tracks ADD COLUMN loudness REAL")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        _to_households(conn)


def _to_households(conn: sqlite3.Connection) -> None:
    """0.9.1: every song moves into its owner's library (library_items), with its play
    count, last play, star and pin; album/artist stars move to `stars`; every profile that
    has songs becomes a parent with its own store. The old tracks/albums/artists columns
    are left as they were (no longer read). A copy of the database is taken first."""
    if conn.execute("SELECT 1 FROM tracks LIMIT 1").fetchone():
        copy = db_path().with_name("dielify-before-0.9.1.db")
        if not copy.exists():
            conn.commit()
            try:
                conn.execute("VACUUM INTO ?", (str(copy),))
                log.info("Database copied to %s before moving to per-person libraries", copy)
            except sqlite3.Error as e:  # another thread got there first; the move itself keeps all data
                log.warning("Database copy before 0.9.1 not made: %s", e)
    conn.execute("INSERT OR IGNORE INTO library_items (profile, track_id, added_at, added_by, "
                 "play_count, last_played, starred_at, pinned) SELECT profile, id, created_at, 'scan', "
                 "play_count, last_played, starred_at, pinned FROM tracks")
    for kind, table in (("album", "albums"), ("artist", "artists")):
        conn.execute(f"INSERT OR IGNORE INTO stars (profile, kind, item_id, starred_at) "
                     f"SELECT profile, '{kind}', id, starred_at FROM {table} WHERE starred_at IS NOT NULL")
    conn.execute("INSERT OR IGNORE INTO people (profile, role, store, created_at) "
                 "SELECT DISTINCT profile, 'parent', profile, ? FROM tracks", (time.time(),))
    conn.execute("PRAGMA user_version = 1")
    conn.commit()


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


# --- people -----------------------------------------------------------------------

ROLES = ("parent", "child")


def person(profile: str) -> dict:
    """A profile's role and music store. A profile not seen before is a parent with its
    own store (its own folder), which is how every profile worked before 0.9.1."""
    with connect() as conn:
        row = conn.execute("SELECT profile, role, store FROM people WHERE profile = ?", (profile,)).fetchone()
        if row is None:
            conn.execute("INSERT OR IGNORE INTO people (profile, role, store, created_at) "
                         "VALUES (?, 'parent', ?, ?)", (profile, profile, time.time()))
            row = conn.execute("SELECT profile, role, store FROM people WHERE profile = ?", (profile,)).fetchone()
    return dict(row)


def set_person(profile: str, role: str = "parent", store: str | None = None) -> dict:
    """Add or change a person: a child (or a second parent) can share another's store."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    store = person(store)["profile"] if store else None
    p = person(profile)
    with connect() as conn:
        conn.execute("UPDATE people SET role = ?, store = ? WHERE profile = ?",
                     (role, store or p["store"], p["profile"]))
    return person(profile)


def people() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT profile, role, store, created_at FROM people ORDER BY created_at")]


def signin_of(profile: str) -> str:
    """Whose YouTube sign-in a person uses: the owner of their store (a child uses the
    parent's, behind the scenes)."""
    return person(profile)["store"]


# Tables with one row set per person (removing a person clears these; files stay).
_PERSON_TABLES = ("library_items", "stars", "plays", "playlists", "ratings", "explore_songs",
                  "discovery_lists")


def forget_person(profile: str) -> None:
    """Remove a person's library, history, ratings and playlists (not their files: songs
    only they had stay in the store, shown under Household). Their waiting downloads stop."""
    p = person(profile)["profile"]
    with connect() as conn:
        for table in _PERSON_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE profile = ?", (p,))
        conn.execute("UPDATE downloads SET status = 'cancelled', error = 'Person removed' "
                     "WHERE profile = ? AND status IN ('queued', 'downloading', 'processing')", (p,))
        conn.execute("DELETE FROM people WHERE profile = ?", (p,))


def profiles() -> list[str]:
    """Everyone who has songs in their library (for the background jobs: mixes, discovery)."""
    with connect() as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT profile FROM library_items ORDER BY profile")]


def library_for(profile: str, settings=None) -> "Library":
    """The Library of this person: their own song list, over their household's store."""
    from . import settings as settings_mod
    p = person(profile)
    s = settings or settings_mod.load()
    return Library(p["profile"], s.profile_library(p["store"]), store=p["store"], role=p["role"])


class Library:
    """One person's music. The files live in a store: `root` is the store owner's folder
    (Artist/Album/Track), and tracks.profile is that owner. The person's library is their
    own list of songs in it (library_items), with their own play counts and stars, so two
    people can share one copy of a file and still have separate libraries.
    Before 0.9.1 (and still, for one person) store = profile."""

    def __init__(self, profile: str, root: Path, store: str | None = None, role: str = "parent"):
        self.profile = profile
        self.store = store or profile
        self.role = role
        self.root = Path(root)

    def path_of(self, track: sqlite3.Row) -> Path:
        return self.root / Path(track["relpath"])

    # --- indexing (the store's files) ------------------------------------------------

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
        """Bring the index in line with the store's folder. New files found this way join
        the store owner's library (whoever copied them in there)."""
        res = ScanResult()
        with connect() as conn:
            known = {r["relpath"]: r for r in conn.execute(
                "SELECT id, relpath, size, mtime, video_id FROM tracks WHERE profile = ?",
                (self.store,))}
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
                self._upsert(conn, path, rel, tags, row["id"] if row else None, owner=self.store, how="scan")
                if row:
                    res.updated += 1
                else:
                    res.added += 1
            for row in gone.values():  # the file is gone, so it's gone from every library
                conn.execute("DELETE FROM tracks WHERE id = ?", (row["id"],))
                res.removed += 1
            self._prune(conn)
        return res

    def index_file(self, path: Path, added_by: str = "download") -> int:
        """Add or refresh one file (called right after a download) and put it in this
        person's library."""
        rel = Path(path).relative_to(self.root).as_posix()
        tags = read_tags(Path(path))
        with connect() as conn:
            row = conn.execute("SELECT id FROM tracks WHERE profile = ? AND relpath = ?",
                               (self.store, rel)).fetchone()
            if row is None and tags.get("video_id"):
                row = conn.execute("SELECT id FROM tracks WHERE profile = ? AND video_id = ?",
                                   (self.store, tags["video_id"])).fetchone()
            track_id = self._upsert(conn, Path(path), rel, tags, row["id"] if row else None,
                                    owner=self.profile, how=added_by)
            self._join(conn, track_id, added_by)
            self._prune(conn)
        return track_id

    def _join(self, conn, track_id: int, added_by: str) -> bool:
        return conn.execute(
            "INSERT OR IGNORE INTO library_items (profile, track_id, added_at, added_by) "
            "SELECT ?, id, ?, ? FROM tracks WHERE id = ? AND profile = ?",
            (self.profile, time.time(), added_by, track_id, self.store)).rowcount > 0

    def _upsert(self, conn, path: Path, rel: str, tags: dict, track_id: int | None,
                owner: str | None = None, how: str = "scan") -> int:
        parts = Path(rel).parts
        folder_artist = parts[0] if len(parts) >= 3 else None
        folder_album = parts[1] if len(parts) >= 3 else None
        artist = tags.get("artist") or folder_artist or "Unknown Artist"
        album_artist = tags.get("album_artist") or artist
        album = tags.get("album") or folder_album or "Singles"
        now = time.time()

        conn.execute("INSERT OR IGNORE INTO artists (profile, name) VALUES (?, ?)",
                     (self.store, album_artist))
        artist_id = conn.execute("SELECT id FROM artists WHERE profile = ? AND name = ?",
                                 (self.store, album_artist)).fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO albums (profile, artist_id, name, created_at) "
                     "VALUES (?, ?, ?, ?)", (self.store, artist_id, album, now))
        album_id = conn.execute("SELECT id FROM albums WHERE artist_id = ? AND name = ?",
                                (artist_id, album)).fetchone()["id"]

        st = path.stat()
        values = dict(profile=self.store, relpath=rel, album_id=album_id, artist_id=artist_id,
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
            track_id = conn.execute(f"INSERT INTO tracks ({cols}) VALUES ({marks})",
                                    tuple(values.values())).lastrowid
            conn.execute("INSERT OR IGNORE INTO library_items (profile, track_id, added_at, added_by) "
                         "VALUES (?, ?, ?, ?)", (owner or self.store, track_id, now, how))
            return track_id
        sets = ", ".join(f"{k} = ?" for k in values)
        # the file changed: measure its loudness again (leveller.py)
        conn.execute("UPDATE tracks SET loudness = NULL WHERE id = ? AND (mtime != ? OR size != ?)",
                     (track_id, st.st_mtime, st.st_size))
        conn.execute(f"UPDATE tracks SET {sets} WHERE id = ?", (*values.values(), track_id))
        return track_id

    def _prune(self, conn) -> None:
        conn.execute("DELETE FROM albums WHERE profile = ? AND id NOT IN "
                     "(SELECT DISTINCT album_id FROM tracks WHERE profile = ?)",
                     (self.store, self.store))
        conn.execute("DELETE FROM artists WHERE profile = ? AND id NOT IN "
                     "(SELECT DISTINCT artist_id FROM albums WHERE profile = ?)",
                     (self.store, self.store))

    # --- this person's library -----------------------------------------------------

    def add(self, track_id: int, added_by: str = "added") -> bool:
        """Put a song that's already in the store into this library (no download).
        False if it isn't in the store."""
        with connect() as conn:
            self._join(conn, track_id, added_by)
            return conn.execute("SELECT 1 FROM library_items WHERE profile = ? AND track_id = ?",
                                (self.profile, track_id)).fetchone() is not None

    def add_many(self, track_ids: list[int], added_by: str = "added") -> int:
        """Put songs from the store into this library. Returns how many were new to it."""
        with connect() as conn:
            return sum(self._join(conn, int(t), added_by) for t in track_ids)

    # Songs in the store that aren't in this library (the Household shelf).
    _HOUSEHOLD_SELECT = """
        SELECT t.id, t.profile AS store, t.relpath, t.album_id, t.artist_id, t.title, t.artist,
               t.year, t.track_no, t.duration_s, t.bitrate_kbps, t.suffix, t.size, t.mtime,
               t.video_id, t.has_cover, t.loudness, t.created_at, 0 AS play_count,
               NULL AS last_played, NULL AS starred_at, 0 AS pinned,
               al.name AS album, ar.name AS album_artist
        FROM tracks t JOIN albums al ON al.id = t.album_id JOIN artists ar ON ar.id = t.artist_id
        WHERE t.profile = :store
          AND NOT EXISTS (SELECT 1 FROM library_items li WHERE li.track_id = t.id AND li.profile = :p)"""

    def household(self, query: str = "", limit: int = 200, offset: int = 0) -> list[sqlite3.Row]:
        """Songs already on the PC (in the household's store) that aren't in this library:
        newest first, or matching `query`."""
        q = query.strip().casefold()
        if q:
            return self._q(self._HOUSEHOLD_SELECT + " AND (fold(t.title) LIKE :q OR fold(t.artist) LIKE :q "
                           "OR fold(al.name) LIKE :q) ORDER BY fold(t.artist), fold(al.name), t.track_no "
                           "LIMIT :n OFFSET :o", store=self.store, q=f"%{q}%", n=limit, o=offset)
        return self._q(self._HOUSEHOLD_SELECT + " ORDER BY t.created_at DESC, t.album_id, t.track_no "
                       "LIMIT :n OFFSET :o", store=self.store, n=limit, o=offset)

    def store_track_by_video(self, video_id: str) -> sqlite3.Row | None:
        """A song in the store (whoever's library it's in) with this YouTube id."""
        sql = self._HOUSEHOLD_SELECT.split("AND NOT EXISTS")[0] + " AND t.video_id = :v ORDER BY t.id LIMIT 1"
        rows = self._q(sql, store=self.store, v=video_id)
        return rows[0] if rows else None

    def household_track(self, track_id: int) -> sqlite3.Row | None:
        rows = self._q(self._HOUSEHOLD_SELECT + " AND t.id = :id", store=self.store, id=track_id)
        return rows[0] if rows else None

    def store_video_ids(self) -> dict[str, int]:
        """video id -> track id for every song in the store, in this library or not."""
        with connect() as conn:
            return {r[0]: r[1] for r in conn.execute(
                "SELECT video_id, id FROM tracks WHERE profile = ? AND video_id IS NOT NULL", (self.store,))}

    # --- queries (all scoped to this person's library) ---------------------------------

    # Per-person columns come from library_items (li); created_at = when it joined this library.
    _TRACK_SELECT = """
        SELECT t.id, t.profile AS store, t.relpath, t.album_id, t.artist_id, t.title, t.artist,
               t.year, t.track_no, t.duration_s, t.bitrate_kbps, t.suffix, t.size, t.mtime,
               t.video_id, t.has_cover, t.loudness, li.added_at AS created_at, li.play_count,
               li.last_played, li.starred_at, li.pinned, al.name AS album, ar.name AS album_artist
        FROM library_items li JOIN tracks t ON t.id = li.track_id
        JOIN albums al ON al.id = t.album_id JOIN artists ar ON ar.id = t.artist_id
        WHERE li.profile = :p"""

    _ALBUM_SELECT = """
        SELECT al.id, al.profile, al.artist_id, al.name, MIN(li.added_at) AS created_at,
               sa.starred_at AS starred_at, ar.name AS artist,
               COUNT(t.id) AS song_count, COALESCE(SUM(t.duration_s), 0) AS duration,
               MAX(t.year) AS year, COALESCE(SUM(li.play_count), 0) AS play_count,
               MAX(li.last_played) AS last_played,
               (SELECT c.id FROM tracks c JOIN library_items cl ON cl.track_id = c.id AND cl.profile = :p
                WHERE c.album_id = al.id AND c.has_cover = 1 ORDER BY c.track_no LIMIT 1) AS cover_track_id
        FROM library_items li JOIN tracks t ON t.id = li.track_id
        JOIN albums al ON al.id = t.album_id JOIN artists ar ON ar.id = al.artist_id
        LEFT JOIN stars sa ON sa.profile = :p AND sa.kind = 'album' AND sa.item_id = al.id
        WHERE li.profile = :p"""

    _ARTIST_SELECT = """
        SELECT ar.id, ar.profile, ar.name, sr.starred_at AS starred_at,
               COUNT(DISTINCT al.id) AS album_count, MIN(al.id) AS first_album_id
        FROM library_items li JOIN tracks t ON t.id = li.track_id
        JOIN albums al ON al.id = t.album_id JOIN artists ar ON ar.id = al.artist_id
        LEFT JOIN stars sr ON sr.profile = :p AND sr.kind = 'artist' AND sr.item_id = ar.id
        WHERE li.profile = :p"""

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
                       "ORDER BY MAX(t.year), fold(al.name)", id=artist_id)

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
            "newest": "MIN(li.added_at) DESC",
            "alphabeticalByName": "fold(al.name)",
            "alphabeticalByArtist": "fold(ar.name), MAX(t.year), fold(al.name)",
            "frequent": "SUM(li.play_count) DESC",
            "highest": "SUM(li.play_count) DESC",
            "recent": "MAX(li.last_played) DESC",
            "starred": "fold(al.name)",
            "random": "RANDOM()",
        }.get(kind)
        if kind == "byYear":
            lo, hi = from_year or 0, to_year or 9999
            order = "MAX(t.year) DESC" if lo > hi else "MAX(t.year)"
            lo, hi = min(lo, hi), max(lo, hi)
            where = f" HAVING MAX(t.year) BETWEEN {int(lo)} AND {int(hi)}"
        elif kind == "starred":
            where = " HAVING MAX(sa.starred_at) IS NOT NULL"
        elif kind in ("frequent", "highest"):
            where = " HAVING SUM(li.play_count) > 0"
        elif kind == "recent":
            where = " HAVING MAX(li.last_played) IS NOT NULL"
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
        """video id -> track id of the songs in this library (for marking discovery
        results "in your library")."""
        return {r["video_id"]: r["id"] for r in self._q(
            "SELECT t.video_id, t.id FROM library_items li JOIN tracks t ON t.id = li.track_id "
            "WHERE li.profile = :p AND t.video_id IS NOT NULL")}

    def random_tracks(self, size: int) -> list[sqlite3.Row]:
        rows = self._q(self._TRACK_SELECT)
        return random.sample(rows, min(size, len(rows)))

    def starred(self) -> tuple[list, list, list]:
        return (self._q(self._ARTIST_SELECT + " AND sr.starred_at IS NOT NULL GROUP BY ar.id"),
                self._q(self._ALBUM_SELECT + " AND sa.starred_at IS NOT NULL GROUP BY al.id"),
                self._q(self._TRACK_SELECT + " AND li.starred_at IS NOT NULL"))

    def set_starred(self, table: str, item_id: int, starred: bool) -> None:
        assert table in ("tracks", "albums", "artists")
        with connect() as conn:
            if table == "tracks":
                conn.execute("UPDATE library_items SET starred_at = ? WHERE profile = ? AND track_id = ?",
                             (time.time() if starred else None, self.profile, item_id))
                return
        kind = "album" if table == "albums" else "artist"
        if starred and (self.album(item_id) if kind == "album" else self.artist(item_id)) is None:
            return  # not in this library
        with connect() as conn:
            if starred:
                conn.execute("INSERT OR IGNORE INTO stars (profile, kind, item_id, starred_at) "
                             "VALUES (?, ?, ?, ?)", (self.profile, kind, item_id, time.time()))
            else:
                conn.execute("DELETE FROM stars WHERE profile = ? AND kind = ? AND item_id = ?",
                             (self.profile, kind, item_id))

    def remove_track(self, track_id: int) -> bool:
        """Take a song out of this library. Its file is deleted (and empty album/artist
        folders with it) only when no other library has the song, and never by a child.
        Returns whether the song was in this library."""
        t = self.track(track_id)
        if t is None:
            return False
        with connect() as conn:
            shared = conn.execute("SELECT COUNT(*) FROM library_items WHERE track_id = ? AND profile != ?",
                                  (track_id, self.profile)).fetchone()[0]
        if shared or self.role == "child":
            with connect() as conn:
                conn.execute("DELETE FROM library_items WHERE profile = ? AND track_id = ?",
                             (self.profile, track_id))
            return True
        path = self.path_of(t)
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            raise OSError(f"Couldn't delete {path.name}: {e}") from e
        with connect() as conn:
            conn.execute("DELETE FROM tracks WHERE id = ? AND profile = ?", (track_id, self.store))
            self._prune(conn)
        folder = path.parent
        root = self.root.resolve()
        while folder.resolve() != root and root in folder.resolve().parents:
            try:
                folder.rmdir()  # only if empty (a cover.jpg or other files keep it)
            except OSError:
                break
            folder = folder.parent
        return True

    def record_play(self, track_id: int, when: float | None = None) -> None:
        with connect() as conn:
            conn.execute("UPDATE library_items SET play_count = play_count + 1, last_played = ? "
                         "WHERE profile = ? AND track_id = ?", (when or time.time(), self.profile, track_id))

    def stats(self) -> dict:
        with connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS tracks, COALESCE(SUM(t.size), 0) AS bytes, "
                "COUNT(DISTINCT t.album_id) AS albums, COUNT(DISTINCT t.artist_id) AS artists "
                "FROM library_items li JOIN tracks t ON t.id = li.track_id WHERE li.profile = ?",
                (self.profile,)).fetchone()
        return dict(row)
