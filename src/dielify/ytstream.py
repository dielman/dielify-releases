"""Play a YouTube song straight away, before it's downloaded.

The PC asks yt-dlp (with the profile's Premium sign-in) where the audio is, then relays
it to the phone/desktop player, passing seeks (Range requests) through. The phone never
sees the YouTube address or the cookies. Addresses are reused for STREAM_TTL_S.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable, Iterator

import requests

from .yt_adapter import StreamInfo

log = logging.getLogger(__name__)

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
STREAM_TTL_S = 30 * 60      # YouTube's addresses last hours; stay well inside that
CHUNK = 64 * 1024
PASS_HEADERS = ("content-length", "content-range", "accept-ranges")


class StreamCache:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], StreamInfo] = {}
        self._lock = threading.Lock()

    def get(self, profile: str, video_id: str, resolve: Callable[[], StreamInfo],
            fresh: bool = False) -> StreamInfo:
        key = (profile, video_id)
        with self._lock:
            hit = self._cache.get(key)
            if hit and not fresh and time.time() - hit.fetched_at < STREAM_TTL_S:
                return hit
        info = resolve()
        with self._lock:
            self._cache[key] = info
            for k in [k for k, v in self._cache.items() if time.time() - v.fetched_at > STREAM_TTL_S]:
                del self._cache[k]
        return info


cache = StreamCache()
_http = requests.Session()


def open_upstream(info: StreamInfo, range_header: str | None) -> requests.Response:
    # YouTube only accepts a fresh address a few seconds after handing it out (yt-dlp
    # waits too: "Sleeping ... as required by the site").
    wait = info.available_at - time.time()
    if wait > 0:
        time.sleep(min(wait, 15))
    headers = dict(info.headers)
    if range_header:
        headers["Range"] = range_header
    return _http.get(info.url, headers=headers, stream=True, timeout=(10, 30))


def relay(resp: requests.Response) -> tuple[int, dict, Iterator[bytes]]:
    """Status, headers to pass on, and the body for a StreamingResponse."""
    headers = {k: v for k, v in resp.headers.items() if k.lower() in PASS_HEADERS}
    headers.setdefault("Accept-Ranges", "bytes")

    def body() -> Iterator[bytes]:
        try:
            for chunk in resp.iter_content(CHUNK):
                if chunk:
                    yield chunk
        except requests.RequestException as e:  # the player will ask again (Range)
            log.info("YouTube stream interrupted: %s", e)
        finally:
            resp.close()

    return resp.status_code, headers, body()
