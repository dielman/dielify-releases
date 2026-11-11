"""The PC installs Dielify updates on the TVs (0.9.10, Josh: "PC installs via USB").

Josh's TV can't install updates itself: a Family Link kids profile on it turns "install unknown
apps" off for the whole TV. With the TV's USB debugging on, the PC installs the phone/TV app it
carries (appshare.py) over the home network, the same way it was first installed:
`adb connect <tv>:5555`, then `adb install -r`. Only a TV that has allowed this PC (the "Allow
USB debugging?" prompt, once) accepts it, and Android still checks the app's signature.

The TVs: every TV that connects for remote control (kind "tv") is remembered with its
home-network address (tvs.json in the data folder). adb comes from the Android SDK on this PC
(Google's licence doesn't let Dielify ship it); Settings > People & phones says when it's missing.
A TV that's playing music is left alone until it isn't (installing restarts the app).
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import appshare
from .paths import app_data_dir

log = logging.getLogger(__name__)
PACKAGE = "com.dielify.app"
ADB_PORT = 5555
CHECK_EVERY_S = 6 * 3600
_lock = threading.Lock()
_busy = threading.Lock()  # one round of installs at a time


# --- which TVs ------------------------------------------------------------------------------

def _file() -> Path:
    return app_data_dir() / "tvs.json"


def _home_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.version == 4 and a.is_private and not a.is_loopback and a not in ipaddress.ip_network("100.64.0.0/10")


def known() -> dict[str, dict]:
    """{address: {name, last_seen, version_code?, result?}}"""
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if _home_ip(k) and isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    _file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def remember(ip: str | None, name: str) -> None:
    """A TV connected from this home-network address (Tailscale / loopback are ignored)."""
    if not ip or not _home_ip(ip):
        return
    with _lock:
        data = known()
        entry = data.get(ip, {})
        entry.update(name=name[:60], last_seen=time.time())
        data[ip] = entry
        _save(data)


def forget(ip: str) -> bool:
    with _lock:
        data = known()
        if data.pop(ip, None) is None:
            return False
        _save(data)
        return True


def _note(ip: str, **fields) -> None:
    with _lock:
        data = known()
        if ip in data:
            data[ip].update(fields)
            _save(data)


# --- adb ------------------------------------------------------------------------------------

def find_adb() -> str | None:
    """adb.exe from the Android SDK on this PC (or on PATH)."""
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    if os.environ.get("LOCALAPPDATA"):
        roots.append(str(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk"))
    roots += [f"{d}:\\Android\\Sdk" for d in "CDEFGH"]
    for r in roots:
        if r:
            exe = Path(r) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
            if exe.is_file():
                return str(exe)
    return shutil.which("adb")


def _run(adb: str, *args: str, timeout: float = 60) -> tuple[int, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run([adb, *args], capture_output=True, text=True, timeout=timeout, creationflags=flags)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as e:
        return 127, str(e)


def installed_code(adb: str, target: str) -> int | None:
    rc, out = _run(adb, "-s", target, "shell", "dumpsys", "package", PACKAGE, timeout=30)
    m = re.search(r"versionCode=(\d+)", out) if rc == 0 else None
    return int(m.group(1)) if m else None


def update_tv(ip: str, adb: str | None = None, app: dict | None = None) -> str:
    """Bring one TV up to the app this PC carries. Returns what happened, in words."""
    adb = adb or find_adb()
    app = app or appshare.available()
    if app is None:
        return "This PC has no TV app to install"
    from . import remote
    tv = remote.tv_at(ip)
    if tv is not None and tv.version >= app["version_code"]:  # it told us its version itself
        result = f"Up to date ({app['version']})"
        _note(ip, version_code=tv.version, result=result, checked=time.time())
        return result
    target = f"{ip}:{ADB_PORT}"
    rc, out = _run(adb, "connect", target, timeout=20) if adb else (127, "")
    if "unauthorized" in out or "failed to authenticate" in out:
        result = "The TV hasn't allowed this PC yet: press Allow on the TV, then try again"
    elif rc != 0 or not ("connected" in out):
        # No installs over the network (on a cable, where Android allows no network debugging,
        # or debugging is off). A TV that's open in Dielify can update itself instead.
        if remote.ask_tv_to_update(ip):
            result = "Asked the TV to update itself: press Install on the TV"
        elif tv is not None:
            result = ("This TV can't take installs from the PC (on a cable, Android allows none). Update it once on "
                      "the TV: Dielify > Settings > Check for updates. After that the PC asks it to update itself")
        else:
            result = "The TV isn't connected: open Dielify on it (and turn on USB debugging in Developer options "                      "if it's on Wi-Fi)"
    else:
        have = installed_code(adb, target)
        if have is None:
            result = "The TV didn't answer (allow this PC on the TV, or try again)"
        elif have >= app["version_code"]:
            result = f"Up to date ({app['version']})"
        else:
            rc, out = _run(adb, "-s", target, "install", "-r", str(app["path"]), timeout=300)
            result = f"Updated to {app['version']}" if rc == 0 and "Success" in out else \
                f"Install didn't work: {out.splitlines()[-1] if out else rc}"
            if rc == 0 and "Success" in out:  # open it again where it was
                _run(adb, "-s", target, "shell", "am", "start", "-n", f"{PACKAGE}/.tv.TvActivity", timeout=20)
            have = installed_code(adb, target) or have
        _note(ip, version_code=have)
    _note(ip, result=result, checked=time.time())
    log.info("TV %s: %s", ip, result)
    return result


def update_all(playing=lambda ip: False) -> dict[str, str]:
    """Every known TV that isn't playing right now. {address: what happened}"""
    if not _busy.acquire(blocking=False):
        return {}
    try:
        adb, app = find_adb(), appshare.available()
        out = {}
        for ip in known():
            if playing(ip):
                out[ip] = "Playing music: it'll update when it stops"
                _note(ip, result=out[ip], checked=time.time())
            else:
                out[ip] = update_tv(ip, adb, app)
        return out
    finally:
        _busy.release()


class Worker:
    """Checks the TVs a few minutes after the PC starts (e.g. after it updated itself) and then
    every CHECK_EVERY_S. A TV that's playing gets another try 10 minutes later."""

    def __init__(self, playing=lambda ip: False):
        self.playing = playing
        self._stop = threading.Event()

    def _loop(self) -> None:
        wait = 5 * 60
        while not self._stop.wait(wait):
            wait = CHECK_EVERY_S
            try:
                if appshare.available() and known():  # adb, or the TV updating itself
                    results = update_all(self.playing)
                    if any(r.startswith("Playing") for r in results.values()):
                        wait = 10 * 60
            except Exception:  # noqa: BLE001
                log.exception("Updating the TVs failed")

    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="dielify-tv-updates").start()

    def stop(self) -> None:
        self._stop.set()
