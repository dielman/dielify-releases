"""Fetch -> tag -> file into the library.

Phase 1 is one track at a time. Phase 3 adds a queue, progress reporting and retries
on top of `download_track`, which is deliberately a single self-contained step.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .paths import safe_name
from .settings import Settings
from .tagging import prepare_cover, tag_file
from .yt_adapter import ProgressFn, TrackInfo, YTMusicAdapter

log = logging.getLogger(__name__)

AUDIO_EXTS = (".m4a", ".opus", ".ogg", ".mp3", ".flac")


@dataclass
class DownloadResult:
    path: Path
    info: TrackInfo
    already_existed: bool = False
    kept_better: bool = False      # overwrite asked, but the copy already there was better
    track_id: int | None = None    # set when an existing song's file was replaced in place


def library_relpath(info: TrackInfo) -> Path:
    """Artist / Album / NN Title  (extension added once the format is known).

    Album-less tracks (e.g. music videos) go under "Singles". The folder artist is
    the album artist when known so multi-artist albums stay together.
    """
    folder_artist = safe_name(info.album_artist or info.artist, "Unknown Artist")
    album = safe_name(info.album or "Singles", "Singles")
    title = safe_name(info.title, info.video_id)
    if info.track_number:
        title = f"{info.track_number:02d} {title}"
    return Path(folder_artist) / album / title


def find_existing(base: Path) -> Path | None:
    for ext in AUDIO_EXTS:
        p = base.with_name(base.name + ext)
        if p.exists():
            return p
    return None


def _kbps(path: Path) -> int | None:
    try:
        from .tagging import read_tags
        return read_tags(path).get("bitrate_kbps")
    except Exception:  # noqa: BLE001 - unreadable: treated as unknown
        return None


# A new copy has to be at least this close to the old one's bitrate to replace it: the same quality
# measures a few kbps apart between downloads (cover art, container), a downgrade is ~100 kbps.
SAME_QUALITY_KBPS = 16


def download_track(adapter: YTMusicAdapter, video_id: str, settings: Settings,
                   profile: str | None = None, progress: ProgressFn | None = None,
                   overwrite: bool = False) -> DownloadResult:
    """Download one song into the library. overwrite: replace the copy already there (an upgrade
    to full quality, or `dielify download --overwrite`), but never with a lower-quality one
    (Josh, 21 Nov 2026): the better file always stays."""
    info = adapter.get_track(video_id)
    from .library import connect, library_for
    lib = library_for(profile or settings.active_profile, settings)
    library = lib.root  # the household's music store
    base = library / library_relpath(info)

    existing = find_existing(base)
    store_track = None
    if overwrite:  # the song's current file, wherever it is (its tags may have moved it)
        with connect() as conn:
            store_track = conn.execute("SELECT id, relpath FROM tracks WHERE profile = ? AND video_id = ? "
                                       "ORDER BY id LIMIT 1", (lib.store, video_id)).fetchone()
        if store_track is not None and (library / store_track["relpath"]).exists():
            existing = library / store_track["relpath"]
    if existing and not overwrite:
        log.info("Already in library: %s", existing)
        return DownloadResult(existing, info, already_existed=True)

    # Download into a temp folder on the same drive as the library so the final
    # move is atomic and a half-finished download never appears in the library.
    library.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dielify-dl-", dir=library) as tmp:
        audio = adapter.fetch_audio(video_id, Path(tmp), settings.quality,
                                    settings.preferred_format, progress)
        if existing:
            old_kbps, new_kbps = _kbps(existing), _kbps(audio)
            if old_kbps and (not new_kbps or new_kbps < old_kbps - SAME_QUALITY_KBPS):
                log.info("Kept %s (%s kbps): the new copy is lower quality (%s kbps)", existing, old_kbps, new_kbps)
                return DownloadResult(existing, info, already_existed=True, kept_better=True,
                                      track_id=store_track["id"] if store_track else None)
        cover = prepare_cover(adapter.fetch_cover(info.cover_url))
        tag_file(audio, info, cover)
        final = base.with_name(base.name + audio.suffix.lower())
        final.parent.mkdir(parents=True, exist_ok=True)
        if existing and existing != final:
            existing.unlink()
        shutil.move(str(audio), final)
    log.info("Saved %s", final)
    try:
        if store_track is not None:  # the same song, a new file: its row (plays, playlists) stays
            lib.moved(store_track["id"], final)
            return DownloadResult(final, info, track_id=store_track["id"])
        lib.index_file(final)
    except Exception as e:  # the file is safe on disk; a later scan picks it up
        log.warning("Saved but not indexed (run `dielify library scan`): %s", e)
    return DownloadResult(final, info)
