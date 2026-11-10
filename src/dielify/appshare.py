"""The phone / TV app, handed out by the PC (0.9.10, Josh: "get updates from the PC first, they
are compiled there to begin with").

packaging/build.py builds the signed Android app together with the PC app and puts it in
dist/android/ (Dielify.apk + Dielify.json); the installer copies that folder to {app}/android.
Phones and TVs ask the PC first and only fall back to GitHub when the PC has nothing newer for
them or can't be reached. (Josh's TCL TV can't reach GitHub at all.)

Safety: the file is only handed out when its size and SHA-256 match Dielify.json, and Android
itself installs an update only if it's signed with the same key as the installed app.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from pathlib import Path

APK = "Dielify.apk"
INFO = "Dielify.json"
_lock = threading.Lock()
_checked: dict[tuple[str, float, int], dict | None] = {}


def folder() -> Path:
    """Where the app is: DIELIFY_ANDROID_DIR (tests), next to Dielify.exe when installed,
    else dist/android in the project (a development copy)."""
    if os.environ.get("DIELIFY_ANDROID_DIR"):
        return Path(os.environ["DIELIFY_ANDROID_DIR"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "android"
    return Path(__file__).resolve().parents[2] / "dist" / "android"


def version_code(version: str) -> int:
    """Same rule as android/app/build.gradle.kts: 0.9.10 -> 910."""
    code = 0
    for part in version.split("."):
        code = code * 100 + int(part)
    return code


def available() -> dict | None:
    """{version, version_code, sha256, size, path} of the app this PC can hand out, or None
    (none here, or the file doesn't match its description)."""
    d = folder()
    apk, info = d / APK, d / INFO
    if not apk.is_file() or not info.is_file():
        return None
    st = apk.stat()
    key = (str(apk), st.st_mtime, st.st_size)
    with _lock:
        if key in _checked:
            return _checked[key]
    try:
        meta = json.loads(info.read_text(encoding="utf-8"))
        h = hashlib.sha256()
        with apk.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        ok = h.hexdigest() == meta["sha256"].lower() and st.st_size == int(meta["size"])
        out = {"version": str(meta["version"]), "version_code": int(meta["version_code"]),
               "sha256": h.hexdigest(), "size": st.st_size, "path": apk} if ok else None
    except (OSError, ValueError, KeyError, TypeError):
        out = None
    with _lock:
        _checked[key] = out
    return out


def describe(apk: Path, version: str) -> dict:
    """What build.py writes next to the app."""
    data = apk.read_bytes()
    return {"version": version, "version_code": version_code(version),
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
