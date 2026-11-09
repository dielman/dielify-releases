"""Artists on YouTube Music and MusicBrainz: which YouTube channel a library artist is,
their About (bio + links), and their latest releases (stored for releases.py).

`call(fn_name, *args)` runs a YouTube adapter method with someone's sign-in (the API passes
its `youtube.call` / `youtube.background`), so this module never imports the adapter.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date
from typing import Callable

from . import tags
from .library import connect
from .ratings import artist_key

log = logging.getLogger(__name__)

NOT_FOUND_RETRY_S = 30 * 86400
ABOUT_KEEP_S = 30 * 86400

Call = Callable[..., object]

_mb: tags.MusicBrainz | None = None
_mb_lock = threading.Lock()


def musicbrainz() -> tags.MusicBrainz:
    """One shared client, so lookups from here keep MusicBrainz's one-a-second rule."""
    global _mb
    with _mb_lock:
        if _mb is None:
            _mb = tags.MusicBrainz()
        return _mb


def channel_for(call: Call, name: str) -> str | None:
    """The artist's YouTube Music channel (exact name match), remembered. None: not found."""
    key = artist_key(name)
    with connect() as conn:
        row = conn.execute("SELECT channel_id, checked_at FROM yt_artists WHERE key = ?", (key,)).fetchone()
    if row and (row["channel_id"] or time.time() - row["checked_at"] < NOT_FOUND_RETRY_S):
        return row["channel_id"]
    found = None
    for it in call("search_items", name, "artist", 5):
        if it.type == "artist" and artist_key(it.title) == key:
            found = it.id
            break
    with connect() as conn:
        conn.execute("INSERT INTO yt_artists (key, name, channel_id, checked_at) VALUES (?,?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET channel_id = excluded.channel_id, checked_at = excluded.checked_at",
                     (key, name, found, time.time()))
    return found


def read_page(call: Call, channel_id: str, name: str) -> tuple[dict, list[str]]:
    """Read the artist's YouTube page and remember their releases. Returns (page, browse ids
    of releases that are new since the last look; none on the first look)."""
    page = call("artist_page", channel_id)
    now = time.time()
    this_year = str(date.today().year)
    fresh: list[str] = []
    with connect() as conn:
        first_look = conn.execute("SELECT 1 FROM artist_releases WHERE channel_id = ? LIMIT 1",
                                  (channel_id,)).fetchone() is None
        for it in page["albums"] + page["singles"]:
            # first look: this year's releases count as new, older ones as already known
            seen = (now if (it.year or "") >= this_year else 0.0) if first_look else now
            cur = conn.execute(
                "INSERT OR IGNORE INTO artist_releases (channel_id, browse_id, title, artist, kind, year, thumbnail, "
                "explicit, first_seen) VALUES (?,?,?,?,?,?,?,?,?)",
                (channel_id, it.id, it.title, page["name"] or name, it.subtitle or "Album", it.year, it.thumbnail,
                 None if it.explicit is None else int(it.explicit), seen))
            if cur.rowcount and not first_look:
                fresh.append(it.id)
        conn.execute("UPDATE yt_artists SET page_at = ? WHERE channel_id = ?", (now, channel_id))
        _save_about_part(conn, artist_key(name), {"description": page["description"], "thumbnail": page["thumbnail"],
                                                  "channel_id": channel_id})
    return page, fresh


def _save_about_part(conn, key: str, part: dict) -> None:
    row = conn.execute("SELECT body FROM artist_about WHERE key = ?", (key,)).fetchone()
    body = json.loads(row["body"]) if row else {}
    body.update({k: v for k, v in part.items() if v})
    conn.execute("INSERT OR REPLACE INTO artist_about (key, body, fetched_at) VALUES (?,?,?)",
                 (key, json.dumps(body), time.time() if "links" in body else 0.0))


# Links worth showing, by MusicBrainz relation type (others are dropped).
LINK_LABELS = {
    "wikipedia": "Wikipedia", "official homepage": "Website", "bandcamp": "Bandcamp",
    "soundcloud": "SoundCloud", "last.fm": "Last.fm", "discogs": "Discogs", "allmusic": "AllMusic",
}
SOCIAL = {"instagram.com": "Instagram", "twitter.com": "X", "x.com": "X", "facebook.com": "Facebook",
          "tiktok.com": "TikTok", "youtube.com": "YouTube", "threads.net": "Threads", "bsky.app": "Bluesky"}


def _links(raw: list[dict]) -> list[dict]:
    out, seen = [], set()
    for r in raw:
        url, kind = r["url"], r["type"].casefold()
        label = LINK_LABELS.get(kind)
        if label is None:
            host = url.split("/")[2].removeprefix("www.").casefold() if url.count("/") >= 2 else ""
            label = SOCIAL.get(host)
        if label and label not in seen and url.startswith("https://"):
            seen.add(label)
            out.append({"label": label, "url": url})
    order = ["Website", "Wikipedia", "Instagram", "X", "TikTok", "Facebook", "YouTube", "Bandcamp", "SoundCloud"]
    return sorted(out, key=lambda l: order.index(l["label"]) if l["label"] in order else 99)


def cached_about(name: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT body FROM artist_about WHERE key = ?", (artist_key(name),)).fetchone()
    return json.loads(row["body"]) if row else None


def about(call: Call | None, name: str, refresh: bool = False) -> dict:
    """{"name", "description", "thumbnail", "channel_id", "links": [{"label", "url"}]}.
    Kept 30 days. call=None: no YouTube (offline); MusicBrainz links still come."""
    key = artist_key(name)
    with connect() as conn:
        row = conn.execute("SELECT body, fetched_at FROM artist_about WHERE key = ?", (key,)).fetchone()
    if row and not refresh and time.time() - row["fetched_at"] < ABOUT_KEEP_S:
        return {"name": name, **json.loads(row["body"])}
    body = json.loads(row["body"]) if row else {}
    if call is not None and not body.get("description"):
        try:
            channel = channel_for(call, name)
            if channel:
                page, _ = read_page(call, channel, name)
                body.update({"description": page["description"], "thumbnail": page["thumbnail"], "channel_id": channel})
        except Exception as e:  # noqa: BLE001  (YouTube trouble: MusicBrainz may still answer)
            log.info("No YouTube About for %r: %s", name, e)
    try:
        with connect() as conn:
            r = conn.execute("SELECT mbid FROM artist_tags WHERE name_key = ?", (tags.norm(name),)).fetchone()
        mbid = r["mbid"] if r else None
        if r is None:
            found = musicbrainz().artist(name)
            mbid = found[0] if found else None
        raw = musicbrainz().links(mbid) if mbid else []
        if raw is not None:
            body["links"] = _links(raw)
    except Exception as e:  # noqa: BLE001
        log.info("No MusicBrainz links for %r: %s", name, e)
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO artist_about (key, body, fetched_at) VALUES (?,?,?)",
                     (key, json.dumps(body), time.time() if "links" in body else 0.0))
    return {"name": name, **body}
