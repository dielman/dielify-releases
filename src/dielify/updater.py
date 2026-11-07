"""Signed self-updates for the installed app.

Each release publishes manifest.json + manifest.json.sig next to the installer:
  {"version": "0.4.1", "url": ".../Dielify-setup-0.4.1.exe", "sha256": "...",
   "size": 180000000, "notes": "...", "published": "2026-11-08"}
The signature is Ed25519 over the exact manifest bytes, made with the private key on
Josh's PC. Dielify only installs a file whose manifest verifies against the public
key built into it AND whose size and SHA-256 match the manifest.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import requests

from . import __version__, update_config
from . import settings as settings_mod
from .paths import app_data_dir

log = logging.getLogger(__name__)

CHECK_EVERY_S = 24 * 3600
FIRST_CHECK_AFTER_S = 30
MAX_INSTALLER_BYTES = 600_000_000


class UpdateError(Exception):
    pass


@dataclass
class UpdateStatus:
    current: str = __version__
    latest: str | None = None
    available: bool = False
    notes: str | None = None
    size: int | None = None
    configured: bool = False
    checked_at: float | None = None
    error: str | None = None
    installing: bool = False


def version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.strip().lstrip("v").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def configured() -> bool:
    return bool(update_config.MANIFEST_URL and update_config.PUBLIC_KEY_PEM)


def verify_manifest(manifest: bytes, signature_b64: str, public_key_pem: str) -> dict:
    """The manifest as a dict, if (and only if) the signature is valid."""
    from Cryptodome.PublicKey import ECC
    from Cryptodome.Signature import eddsa
    try:
        key = ECC.import_key(public_key_pem)
        eddsa.new(key, "rfc8032").verify(manifest, base64.b64decode(signature_b64.strip()))
    except (ValueError, TypeError) as e:
        raise UpdateError("The update's signature is not valid; it was not installed.") from e
    data = json.loads(manifest)
    for field in ("version", "url", "sha256", "size"):
        if field not in data:
            raise UpdateError(f"The update information is missing '{field}'.")
    if not str(data["url"]).startswith("https://"):
        raise UpdateError("The update must be downloaded over HTTPS.")
    return data


class Updater:
    def __init__(self, http: requests.Session | None = None,
                 run_installer: Callable[[Path], None] | None = None):
        self.http = http or requests.Session()
        self.status = UpdateStatus(configured=configured())
        self._manifest: dict | None = None
        self._lock = threading.Lock()
        self._run_installer = run_installer or _launch_installer
        self.on_installer_started: Callable[[], None] = lambda: None  # desktop app quits

    # --- checking ---------------------------------------------------------------

    def check(self) -> UpdateStatus:
        with self._lock:
            st = self.status
            st.configured, st.error = configured(), None
            if not st.configured:
                st.error = "Updates aren't set up yet."
                return st
            if settings_mod.load().offline:
                st.error = "Offline mode is on, so Dielify didn't check for updates."
                return st
            try:
                r = self.http.get(update_config.MANIFEST_URL, timeout=20)
                r.raise_for_status()
                s = self.http.get(update_config.MANIFEST_URL + ".sig", timeout=20)
                s.raise_for_status()
                manifest = verify_manifest(r.content, s.text, update_config.PUBLIC_KEY_PEM)
            except UpdateError as e:
                st.error = str(e)
                log.warning("Update check: %s", e)
                return st
            except (requests.RequestException, ValueError) as e:
                st.error = f"Couldn't check for updates: {e}"
                return st
            self._manifest = manifest
            st.latest, st.notes, st.size = manifest["version"], manifest.get("notes"), manifest["size"]
            st.available = version_tuple(manifest["version"]) > version_tuple(__version__)
            st.checked_at = time.time()
            return st

    def start_background_checks(self) -> None:
        def loop():
            time.sleep(FIRST_CHECK_AFTER_S)
            while True:
                try:
                    self.check()
                except Exception:
                    log.exception("Update check failed")
                time.sleep(CHECK_EVERY_S)
        threading.Thread(target=loop, name="dielify-updates", daemon=True).start()

    # --- installing ----------------------------------------------------------------

    def download(self) -> Path:
        m = self._manifest
        if not (m and self.status.available):
            raise UpdateError("No update to install. Check for updates first.")
        if not 0 < int(m["size"]) <= MAX_INSTALLER_BYTES:
            raise UpdateError("The update's size is not plausible; it was not installed.")
        folder = app_data_dir() / "updates"
        folder.mkdir(exist_ok=True)
        for old in folder.glob("*.exe"):
            old.unlink(missing_ok=True)
        dest = folder / f"Dielify-setup-{m['version']}.exe"
        tmp = dest.with_suffix(".part")
        digest, total = hashlib.sha256(), 0
        with self.http.get(m["url"], stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    total += len(chunk)
                    if total > int(m["size"]):
                        break
                    digest.update(chunk)
                    f.write(chunk)
        if total != int(m["size"]) or digest.hexdigest() != m["sha256"].lower():
            tmp.unlink(missing_ok=True)
            raise UpdateError("The downloaded update doesn't match its signed fingerprint; "
                              "it was deleted and not installed.")
        tmp.replace(dest)
        return dest

    def install(self) -> None:
        """Download, verify, start the installer, then let the app quit."""
        if self.status.installing:
            return
        self.status.installing = True
        try:
            installer = self.download()
            log.info("Installing update %s", self.status.latest)
            self._run_installer(installer)
            self.on_installer_started()
        except Exception:
            self.status.installing = False
            raise

    def as_dict(self) -> dict:
        return asdict(self.status)


def _launch_installer(installer: Path) -> None:
    if not getattr(sys, "frozen", False):
        raise UpdateError("Updates install into the installed app, not a development copy.")
    # Silent, per-user; the installer waits for Dielify to close, then starts it again.
    subprocess.Popen([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RESTARTAPP=1"],
                     close_fds=True, creationflags=subprocess.DETACHED_PROCESS)


updater = Updater()
