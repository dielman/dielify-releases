"""The Dielify desktop app: one window, a tray icon, and the server running behind them.

    pythonw -m dielify.desktop          open the window
    pythonw -m dielify.desktop --tray   start in the tray (used by "start with Windows")

Closing the window keeps Dielify running in the tray, so phones can still play.
"Quit Dielify" in the tray stops everything.

The window is Windows' built-in WebView2. YouTube sign-in happens in a second Dielify
window: the person signs in to Google there, clicks "Use this account", and Dielify
reads the login from its own window. No browser runs in the background.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

import webview

from . import __version__, auth, credstore, winint
from . import settings as settings_mod
from .paths import app_data_dir, use_bundled_tools

log = logging.getLogger("dielify.desktop")

SIGNIN_URL = ("https://accounts.google.com/ServiceLogin?service=youtube&passive=true"
              "&continue=https%3A%2F%2Fmusic.youtube.com%2F")
YTM_URL = "https://music.youtube.com/"

# Shown on top of YouTube Music in the sign-in window, so the person chooses the
# account (brand accounts!) before Dielify reads anything. textContent only: no HTML.
_CONFIRM_BAR_JS = r"""
(() => {
  if (document.getElementById('dielify-bar')) return;
  const bar = document.createElement('div');
  bar.id = 'dielify-bar';
  bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#e5484d;color:#fff;' +
    'font:15px Segoe UI,sans-serif;padding:12px 18px;display:flex;gap:14px;align-items:center;box-shadow:0 -4px 16px #0006';
  const text = document.createElement('div');
  text.style.flex = '1';
  text.textContent = 'Dielify: you are signed in. If you listen on a different channel or brand account, switch to it ' +
    'first (profile picture, top right, then "Switch account"). Then click:';
  const btn = document.createElement('button');
  btn.textContent = 'Use this account';
  btn.style.cssText = 'font:600 15px Segoe UI,sans-serif;padding:8px 16px;border:0;border-radius:8px;cursor:pointer';
  btn.onclick = () => { window.__dielifyUseAccount = true; btn.textContent = 'Reading…'; btn.disabled = true; };
  bar.append(text, btn);
  document.body.append(bar);
})();
"""

_CONFIG_JS = ("window.ytcfg ? {loggedIn: !!ytcfg.get('LOGGED_IN'), authuser: String(ytcfg.get('SESSION_INDEX') ?? '0'),"
              " pageid: ytcfg.get('DELEGATED_SESSION_ID') || null, ua: navigator.userAgent,"
              " confirmed: !!window.__dielifyUseAccount} : null")


class Bridge:
    """Called from the page's JavaScript (window.pywebview.api.*). Keep this small:
    anything here can be called by any script running in the window."""

    def __init__(self):
        self._window: webview.Window | None = None  # underscore: pywebview must not expose it to JS
        self._signin_lock = threading.Lock()

    def pick_folder(self) -> str | None:
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return result[0] if result else None

    def open_library(self) -> None:
        """Open the active profile's music folder in Explorer (folders only)."""
        folder = settings_mod.load().profile_library()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # a directory: Explorer opens it, nothing runs

    def clear_sign_in(self) -> None:
        """Forget any Google cookies in the main window (it never needs them)."""
        self._window.clear_cookies()

    def sign_in(self, profile: str, fresh: bool = False) -> dict:
        if not self._signin_lock.acquire(blocking=False):
            return {"ok": False, "error": "A sign-in window is already open."}
        try:
            result = _run_signin_process(profile)
            if result.get("ok"):
                _signin_changed(profile)
            return result
        finally:
            self._signin_lock.release()


# --- YouTube sign-in, in its own private process ----------------------------------------
# The sign-in window must not share cookies with anything that keeps running: Google
# refreshes ("rotates") session cookies whenever a page using them loads, and then
# rejects the copy Dielify saved. So sign-in runs as a separate Dielify process with a
# private (in-memory) browser profile that disappears when the window closes: the same
# reason the Incognito method works.

def _run_signin_process(profile: str) -> dict:
    import json
    import subprocess
    import tempfile
    fd, result_path = tempfile.mkstemp(prefix="dielify-signin-", suffix=".json")
    os.close(fd)
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [str(Path(sys.executable).with_name("pythonw.exe")), "-m", "dielify.desktop"]
    try:
        subprocess.run(cmd + ["--signin", profile, "--result", result_path], timeout=35 * 60)
        text = Path(result_path).read_text(encoding="utf-8")
        return json.loads(text) if text else {"ok": False, "error": None}
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"The sign-in window couldn't run: {e}"}
    finally:
        Path(result_path).unlink(missing_ok=True)


def signin_main(profile: str, result_path: str) -> int:
    """`Dielify.exe --signin PROFILE --result FILE`: one private sign-in window."""
    import json
    result: dict = {"ok": False, "error": None}
    win = webview.create_window("Dielify: sign in to YouTube Music", SIGNIN_URL, width=1000, height=780)

    def watch() -> None:
        try:
            result.update(_watch_signin(win, profile))
        except Exception as e:  # report it rather than leave the window hanging
            log.exception("Sign-in failed")
            result.update(ok=False, error=f"Sign-in failed: {e}")
        finally:
            try:
                win.destroy()
            except Exception:
                pass

    webview.start(watch, private_mode=True)  # nothing is kept after the window closes
    Path(result_path).write_text(json.dumps(result), encoding="utf-8")
    return 0


def _watch_signin(win: webview.Window, profile: str) -> dict:
    from .yt_adapter import YouTubeError, YTMusicAdapter, headers_from_cookies

    closed = threading.Event()
    win.events.closed += closed.set
    end = time.time() + 30 * 60
    while time.time() < end and not closed.is_set():
        time.sleep(1)
        try:
            url = win.get_current_url() or ""
            cfg = win.evaluate_js(_CONFIG_JS) if url.startswith(YTM_URL) else None
        except Exception:
            continue  # page loading, or window closing
        if not (cfg and cfg["loggedIn"]):
            continue
        if not cfg["confirmed"]:
            win.evaluate_js(_CONFIRM_BAR_JS)
            continue
        cookies = {m.key: m.value for c in win.get_cookies() for m in c.values()}
        try:
            auth_headers = headers_from_cookies(cookies, cfg["authuser"], cfg.get("pageid"), cfg["ua"])
            s = settings_mod.load()
            name = YTMusicAdapter(auth=auth_headers, request_delay_s=s.request_delay_s).account_name()
        except YouTubeError as e:
            return {"ok": False, "error": f"YouTube didn't accept that sign-in: {e}"}
        credstore.save(profile, auth_headers)
        log.info("Profile %s signed in to YouTube Music", profile)
        return {"ok": True, "account": name}
    return {"ok": False, "error": None if closed.is_set() else "Sign-in timed out."}


def _signin_changed(profile: str) -> None:
    """Drop cached YouTube clients so the new sign-in is used straight away."""
    from .custom_api import youtube
    youtube.reset()
    if _app_server is not None:
        _app_server.config.app.state.queue.signin_changed(profile)


# --- tray --------------------------------------------------------------------------------

def tray_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(229, 72, 77, 255))
    d.polygon([(24, 18), (24, 46), (47, 32)], fill=(255, 255, 255, 255))
    return img


def _make_tray(show, quit_app):
    import pystray

    def offline_checked(item):
        return settings_mod.load().offline

    def toggle_offline(icon, item):
        settings_mod.set_value("offline", str(not settings_mod.load().offline))

    menu = pystray.Menu(
        pystray.MenuItem("Open Dielify", lambda icon, item: show(), default=True),
        pystray.MenuItem("Offline mode", toggle_offline, checked=offline_checked),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Dielify", lambda icon, item: quit_app()),
    )
    return pystray.Icon("Dielify", tray_image(), f"Dielify {__version__}", menu)


# --- main -----------------------------------------------------------------------------------

_app_server = None


def main(argv: list[str] | None = None) -> int:
    global _app_server
    p = argparse.ArgumentParser(prog="dielify-desktop")
    p.add_argument("--tray", action="store_true", help="start hidden in the tray")
    p.add_argument("--signin", metavar="PROFILE", help=argparse.SUPPRESS)  # internal
    p.add_argument("--result", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.signin:
        from . import server
        server.setup_file_logging()
        return signin_main(args.signin, args.result)

    use_bundled_tools()
    if not winint.claim_single_instance():
        winint.signal_show()  # already running: bring its window forward
        return 0

    from . import server
    log_file = server.setup_file_logging()
    if sys.stdout is None or sys.stderr is None:  # the installed app has no console
        out = open(log_file.with_name("desktop.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or out
        sys.stderr = sys.stderr or out
    s = settings_mod.load()
    token = auth.enable_desktop_token()
    try:
        _app_server = server.start_background(s, server.bind_addresses(s))
    except OSError as e:
        winint.message_box(f"Dielify couldn't start its server: {e}\n\nIf `dielify serve` is running in a "
                           "terminal, stop it (Ctrl+C) and open Dielify again.")
        return 1

    bridge = Bridge()
    window = webview.create_window(
        "Dielify", f"http://127.0.0.1:{s.server_port}/ui/#t={token}", js_api=bridge,
        width=1200, height=800, min_size=(860, 560), hidden=args.tray, background_color="#111214")
    bridge._window = window
    quitting = threading.Event()

    def show() -> None:
        window.show()
        window.restore()

    def on_closing() -> bool:
        if quitting.is_set():
            return True
        window.hide()  # keep running in the tray
        return False

    def quit_app() -> None:
        quitting.set()
        tray.stop()
        for w in list(webview.windows):
            w.destroy()

    window.events.closing += on_closing
    # Earlier versions signed in inside this window's cookie store; those Google
    # cookies kept rotating and spoiled the saved sign-in. This window needs none.
    window.events.loaded += lambda: window.clear_cookies()
    tray = _make_tray(show, quit_app)

    from .updater import updater
    # The installer waits for Dielify to close; give the window a moment to show
    # "Installing…" first.
    updater.on_installer_started = lambda: threading.Timer(1.5, quit_app).start()
    updater.start_background_checks()
    threading.Thread(target=winint.wait_for_show, args=(show,), daemon=True, name="dielify-show").start()
    threading.Thread(target=winint.keep_awake_loop, args=(lambda: settings_mod.load().keep_awake,),
                     daemon=True, name="dielify-keep-awake").start()

    webview.start(tray.run_detached, private_mode=False, storage_path=str(app_data_dir() / "webview"))

    _app_server.watcher.stop()
    _app_server.should_exit = True
    time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
