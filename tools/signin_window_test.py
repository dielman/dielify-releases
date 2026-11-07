"""Two-minute test: can you sign in to Google inside a Dielify window (Edge WebView2)?

Opens a window at Google's sign-in page. Sign in as usual. When YouTube Music shows
you signed in, the test reads the login from its own window, checks it with
YouTube, prints the result and closes. Nothing is saved: the window runs in
private mode, so the session is gone when it closes.

    .venv\\Scripts\\python tools\\signin_window_test.py
"""

import sys
import time

import webview

SIGNIN_URL = ("https://accounts.google.com/ServiceLogin?service=youtube&passive=true"
              "&continue=https%3A%2F%2Fmusic.youtube.com%2F")
result = {"status": "window closed before sign-in finished"}


def watch(window: webview.Window) -> None:
    from dielify.yt_adapter import YouTubeError, YTMusicAdapter, headers_from_cookies

    end = time.time() + 15 * 60
    last_url = None
    while time.time() < end:
        time.sleep(1)
        try:
            url = window.get_current_url() or ""
        except Exception:
            return  # window closed
        if url != last_url:
            print("page:", url.split("?")[0], flush=True)
            last_url = url
        if "rejected" in url or "disallowed" in url:
            result["status"] = f"Google refused the sign-in in this window ({url.split('?')[0]})"
            return
        if not url.startswith("https://music.youtube.com"):
            continue
        cfg = window.evaluate_js(
            "window.ytcfg ? {loggedIn: !!ytcfg.get('LOGGED_IN'), authuser: String(ytcfg.get('SESSION_INDEX') ?? '0'),"
            " pageid: ytcfg.get('DELEGATED_SESSION_ID') || null, ua: navigator.userAgent} : null")
        if not cfg or not cfg.get("loggedIn"):
            continue
        cookies = {}
        for c in window.get_cookies():
            for morsel in c.values():
                cookies[morsel.key] = morsel.value
        try:
            auth = headers_from_cookies(cookies, cfg["authuser"], cfg.get("pageid"), cfg["ua"])
            name = YTMusicAdapter(auth=auth, request_delay_s=0).account_name()
            result["status"] = (f"WORKS: signed in as {name}; {len(cookies)} cookies read from the window"
                                f"{', brand account' if cfg.get('pageid') else ''}. Nothing was saved.")
        except YouTubeError as e:
            result["status"] = f"Signed in, but YouTube didn't accept the login read from the window: {e}"
        except Exception as e:  # report, don't leave the window hanging
            result["status"] = f"Test error after sign-in: {type(e).__name__}: {e}"
        window.destroy()
        return
    result["status"] = "Timed out after 15 minutes"


window = webview.create_window("Dielify: sign-in test", SIGNIN_URL, width=520, height=720)
webview.start(watch, window, private_mode=True)
print("RESULT:", result["status"], flush=True)
sys.exit(0 if result["status"].startswith("WORKS") else 1)
