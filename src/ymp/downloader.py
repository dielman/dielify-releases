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


def download_track(adapter: YTMusicAdapter, video_id: str, settings: Settings,
                   profile: str | None = None, progress: ProgressFn | None = None,
                   overwrite: bool = False) -> DownloadResult:
    info = adapter.get_track(video_id)
    library = settings.profile_library(profile)
    base = library / library_relpath(info)

    existing = find_existing(base)
    if existing and not overwrite:
        log.info("Already in library: %s", existing)
        return DownloadResult(existing, info, already_existed=True)

    # Download into a temp folder on the same drive as the library so the final
    # move is atomic and a half-finished download never appears in the library.
    library.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ymp-dl-", dir=library) as tmp:
        audio = adapter.fetch_audio(video_id, Path(tmp), settings.quality,
                                    settings.preferred_format, progress)
        cover = prepare_cover(adapter.fetch_cover(info.cover_url))
        tag_file(audio, info, cover)
        final = base.with_name(base.name + audio.suffix.lower())
        final.parent.mkdir(parents=True, exist_ok=True)
        if existing and existing != final:
            existing.unlink()
        shutil.move(str(audio), final)
    log.info("Saved %s", final)
    return DownloadResult(final, info)
