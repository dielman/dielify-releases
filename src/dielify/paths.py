"""Application folders and Windows-safe file naming."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from platformdirs import user_data_dir, user_music_dir

from . import APP_NAME

LEGACY_APP_NAME = "ymp"  # the working name before Dielify


def app_data_dir() -> Path:
    """Where settings, credentials and the database live.

    Windows: %LOCALAPPDATA%\\Dielify. Override with DIELIFY_HOME (used by tests).
    """
    override = os.environ.get("DIELIFY_HOME")
    base = Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False))
    if not override and not base.exists():
        legacy = base.with_name(LEGACY_APP_NAME)
        if legacy.is_dir():
            legacy.rename(base)  # one-off move from the old name: settings, logins, database
    base.mkdir(parents=True, exist_ok=True)
    return base


def use_bundled_tools() -> None:
    """In the installed app, FFmpeg and Deno ship in {app}\\bin: put them first on PATH
    so yt-dlp finds them without anything else being installed."""
    import sys
    if getattr(sys, "frozen", False):
        bin_dir = Path(sys.executable).parent / "bin"
        if bin_dir.is_dir():
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def default_library_root() -> Path:
    return Path(user_music_dir()) / "Dielify"


# --- Filename safety -------------------------------------------------------

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_COMPONENT = 120  # keeps full paths well under Windows' 260-char legacy limit


def safe_name(text: str, fallback: str = "Unknown") -> str:
    """Make one path component that is valid on Windows (and everywhere else)."""
    text = unicodedata.normalize("NFC", text or "")
    text = _INVALID.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(". ")  # Windows forbids trailing dots and spaces
    if not text:
        text = fallback
    if text.split(".")[0].upper() in _RESERVED:
        text = f"_{text}"
    if len(text) > MAX_COMPONENT:
        text = text[:MAX_COMPONENT].rstrip(". ")
    return text
