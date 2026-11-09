"""Artwork for the apps (0.9.9): cover colours, playlist covers, generated covers, artist photos.

- **Colours**: each cover's main colours, worked out once (Pillow) and kept in `art_colors`:
  bg (a dark shade for page backgrounds), accent (a lively colour that reads on dark) and
  fg (text colour on bg). Sent with songs, albums, artists and playlists.
- **Playlist covers**: a 2x2 grid of four different album covers from the playlist (one
  cover if there are fewer); mixes, Blends and smart playlists get a designed cover (a colour
  block with the name in big type); songs and albums with no art get a generated cover.
- **Artist photos**: YouTube Music's square artist picture, found with the artist search
  Dielify already does, downloaded once into <data>/artists/ (artists.channel_for).

Everything made here is kept in memory (a few hundred images at most) or on disk; nothing
is sent anywhere except the one picture download per artist.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
import logging
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from .library import connect
from .paths import app_data_dir

log = logging.getLogger(__name__)

FONT_DIR = Path(r"C:\Windows\Fonts")
VERSION = 1  # bump to redraw every generated image


# --- colours -----------------------------------------------------------------------------

def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _hls(rgb):
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def _rgb(h, l, s):
    return tuple(c * 255 for c in colorsys.hls_to_rgb(h, l, s))


def palette(image_bytes: bytes) -> dict:
    """{"bg", "accent", "fg"} from a picture: bg = the main colour, dark enough for white text;
    accent = its most lively colour, light enough to read on bg."""
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((64, 64))
    q = img.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:18]
    counts = sorted(q.getcolors(), reverse=True)  # [(count, index)]
    colours = [((pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]), n) for n, i in counts if i * 3 + 2 < len(pal)]
    total = sum(n for _, n in colours) or 1
    main = colours[0][0]
    # accent: the colour with the most colour in it (that isn't a speck)
    lively = max(colours, key=lambda c: (_hls(c[0])[2] * (0.4 + _hls(c[0])[1] * (1 - _hls(c[0])[1]) * 4))
                 * min(1.0, c[1] / total * 6))[0]
    h, l, s = _hls(main)
    bg = _rgb(h, min(l, 0.22) if l > 0.05 else 0.08, min(s, 0.55))
    ah, al, as_ = _hls(lively)
    if as_ < 0.12:  # a grey picture: a soft neutral accent
        accent = _rgb(ah, 0.75, 0.0)
    else:
        accent = _rgb(ah, max(0.55, min(al, 0.72)), max(as_, 0.45))
    return {"bg": _hex(bg), "accent": _hex(accent), "fg": "#ffffff"}


# hues that make good covers (no muddy olive / mustard)
_HUES = [350, 5, 18, 28, 155, 168, 185, 200, 212, 225, 245, 262, 278, 292, 310, 328]


def _seed_colours(seed: str) -> dict:
    """Pleasant colours from a name (for generated covers)."""
    n = int(hashlib.sha1(seed.casefold().encode()).hexdigest()[:8], 16)
    h = _HUES[n % len(_HUES)] / 360
    return {"bg": _hex(_rgb(h, 0.2, 0.5)), "accent": _hex(_rgb(h, 0.62, 0.65)), "fg": "#ffffff",
            "_top": _rgb(h, 0.5, 0.62), "_bottom": _rgb((h + 0.08) % 1, 0.24, 0.55)}


_cache: dict[str, dict] | None = None
_cache_lock = threading.Lock()


def _all() -> dict[str, dict]:
    global _cache
    with _cache_lock:
        if _cache is None:
            with connect() as conn:
                _cache = {r["key"]: {"bg": r["bg"], "accent": r["accent"], "fg": r["fg"]}
                          for r in conn.execute("SELECT key, bg, accent, fg FROM art_colors")}
        return _cache


def forget_cache() -> None:
    """Tests (a new database)."""
    global _cache
    with _cache_lock:
        _cache = None


def colours(key: str) -> dict | None:
    return _all().get(key)


def colours_many(keys: list[str]) -> dict[str, dict]:
    if not keys:
        return {}
    out = {}
    with connect() as conn:
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            for r in conn.execute(f"SELECT key, bg, accent, fg FROM art_colors WHERE key IN ({','.join('?' * len(part))})",
                                  part):
                out[r["key"]] = {"bg": r["bg"], "accent": r["accent"], "fg": r["fg"]}
    return out


def save_colours(key: str, c: dict) -> None:
    c = {k: c[k] for k in ("bg", "accent", "fg")}
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO art_colors (key, bg, accent, fg, computed_at) VALUES (?,?,?,?,?)",
                     (key, c["bg"], c["accent"], c["fg"], time.time()))
    _all()[key] = c


def album_key(album_id: int) -> str:
    return f"al:{album_id}"


def seed_colours(seed: str) -> dict:
    return {k: v for k, v in _seed_colours(seed).items() if not k.startswith("_")}


def artist_key_of(name: str) -> str:
    from .ratings import artist_key
    return f"a:{artist_key(name)}"


# --- drawing -----------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _font(bold: bool, size: int):
    from PIL import ImageFont
    for name in (["segoeuib.ttf", "seguisb.ttf"] if bold else ["segoeui.ttf"]):
        try:
            return ImageFont.truetype(str(FONT_DIR / name), size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw, text: str, font, width: int, lines: int) -> list[str]:
    words, out, line = text.split(), [], ""
    for w in words:
        test = f"{line} {w}".strip()
        if draw.textlength(test, font=font) <= width or not line:
            line = test
        else:
            out.append(line)
            line = w
            if len(out) == lines:
                break
    if line and len(out) < lines:
        out.append(line)
    if len(out) == lines and " ".join(out) != text.strip():
        last = out[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        out[-1] = last.rstrip() + "…"
    return out


def _jpeg(img, size: int) -> bytes:
    from PIL import Image
    if size and img.width != size:
        img = img.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=88)
    return out.getvalue()


_drawn: "OrderedDict[tuple, bytes]" = OrderedDict()
_drawn_lock = threading.Lock()


def _remember(key: tuple, make) -> bytes:
    with _drawn_lock:
        if key in _drawn:
            _drawn.move_to_end(key)
            return _drawn[key]
    data = make()
    with _drawn_lock:
        _drawn[key] = data
        while len(_drawn) > 300:
            _drawn.popitem(last=False)
    return data


def designed(title: str, label: str | None = None, subtitle: str | None = None, seed: str | None = None,
             size: int = 600) -> bytes:
    """A cover: a colour gradient (from the name) with the title in big type. For mixes,
    Blends, smart playlists and anything without art."""
    def make():
        from PIL import Image, ImageDraw
        S = 900
        c = _seed_colours(seed or title)
        top, bottom = c["_top"], c["_bottom"]
        # a diagonal gradient (top colour to bottom colour), with two soft circles for character
        down = Image.linear_gradient("L").resize((S, S))
        mask = Image.blend(down, down.rotate(90), 0.35)
        img = Image.composite(Image.new("RGB", (S, S), tuple(int(c) for c in bottom)),
                              Image.new("RGB", (S, S), tuple(int(c) for c in top)), mask)
        glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        n = int(hashlib.sha1((seed or title).encode()).hexdigest()[8:12], 16)
        r1 = 260 + n % 160
        g.ellipse((S - r1 - 40 - n % 120, -r1 // 2, S + r1 // 2, r1 + 60), fill=(255, 255, 255, 34))
        r2 = 180 + n % 90
        g.ellipse((-r2 // 2, S // 2 - r2 // 3, r2, S // 2 + r2), fill=(0, 0, 0, 40))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
        d = ImageDraw.Draw(img)
        pad = 70
        if label:
            d.text((pad, pad), label.upper(), font=_font(True, 46), fill=(255, 255, 255, 220))
        big = _font(True, 112)
        lines = _wrap(d, title, big, S - 2 * pad, 4)
        if len(lines) > 2:
            big = _font(True, 88)
            lines = _wrap(d, title, big, S - 2 * pad, 4)
        line_h = big.size + 14
        y0 = S - pad - line_h * len(lines) - (70 if subtitle else 0)
        for i, line in enumerate(lines):
            d.text((pad, y0 + i * line_h), line, font=big, fill=(255, 255, 255))
        if subtitle:
            small = _font(False, 48)
            d.text((pad, S - pad - 56), _wrap(d, subtitle, small, S - 2 * pad, 1)[0], font=small,
                   fill=(255, 255, 255, 200))
        return _jpeg(img, 0)

    from PIL import Image
    full = _remember(("designed", VERSION, title, label, subtitle, seed), make)
    if size and size != 900:
        return _jpeg(Image.open(io.BytesIO(full)), size)
    return full


def grid(covers: list[bytes], size: int = 600) -> bytes:
    """Four covers in a 2x2 grid (or the first one, if there are fewer than four)."""
    from PIL import Image
    S = max(size or 600, 200)
    if len(covers) < 4:
        img = Image.open(io.BytesIO(covers[0])).convert("RGB")
        return _jpeg(img.resize((S, S), Image.LANCZOS), 0)
    img = Image.new("RGB", (S, S))
    half = S // 2
    for n, data in enumerate(covers[:4]):
        tile = Image.open(io.BytesIO(data)).convert("RGB").resize((half, half), Image.LANCZOS)
        img.paste(tile, ((n % 2) * half, (n // 2) * half))
    return _jpeg(img, 0)


# --- covers from the library -------------------------------------------------------------

def track_cover(lib, track_id: int) -> bytes | None:
    """A library song's embedded cover (None: it has none)."""
    from .subsonic_api import _cover_bytes
    t = lib.track(track_id)
    if t is None:
        with connect() as conn:  # someone else's in the household store
            t = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if t is None or not t["has_cover"]:
        return None
    path = lib.path_of(t)
    return _cover_bytes(str(path), path.stat().st_mtime, 600) if path.exists() else None


def playlist_cover(lib, playlist: dict, size: int = 600) -> tuple[bytes, dict]:
    """(jpeg, colours) for a playlist: designed for mixes / Blends / smart lists, else a grid of
    its album covers, else designed from its name."""
    kind = playlist.get("kind") or "user"
    label = {"mix": "Dielify mix", "blend": "Blend", "smart": "Smart playlist"}.get(kind)
    if label:
        name = playlist["name"].removeprefix("Blend: ")
        return designed(name, label, seed=playlist["name"], size=size), seed_colours(playlist["name"])
    vids = [i["video_id"] for i in playlist.get("items") or []]
    with connect() as conn:
        rows = []
        for i in range(0, len(vids), 500):
            part = vids[i:i + 500]
            rows += conn.execute(
                f"SELECT id, album_id, video_id FROM tracks WHERE has_cover = 1 AND video_id IN ({','.join('?' * len(part))})",
                part).fetchall()
    by_vid = {r["video_id"]: r for r in rows}
    seen, pick = set(), []
    for v in vids:
        r = by_vid.get(v)
        if r and r["album_id"] not in seen:
            seen.add(r["album_id"])
            pick.append(r["id"])
            if len(pick) == 4:
                break
    def make():
        covers = [c for c in (track_cover(lib, t) for t in pick) if c]
        if not covers:
            return None
        return grid(covers, size)
    data = _remember(("grid", VERSION, tuple(pick), size), make) if pick else None
    if data:
        return data, palette(data)
    return designed(playlist["name"], "Playlist", seed=playlist["name"], size=size), seed_colours(playlist["name"])


# --- artist photos -------------------------------------------------------------------------

def _photo_dir() -> Path:
    d = app_data_dir() / "artists"
    d.mkdir(parents=True, exist_ok=True)
    return d


def photo_path(name: str) -> Path:
    from .ratings import artist_key
    return _photo_dir() / (hashlib.sha1(artist_key(name).encode()).hexdigest()[:20] + ".jpg")


def save_photo(name: str, url: str, http=None) -> bool:
    """Download an artist's picture once (YouTube Music's square photo) and keep its colours."""
    from .yt_adapter import upscale_cover_url
    if not url or not url.startswith("https://"):
        return False
    if http is None:
        from .httpclient import retrying_session
        http = retrying_session()
    r = http.get(upscale_cover_url(url, 600), timeout=20)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        return False
    from PIL import Image
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    side = min(img.size)
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2, (img.width + side) // 2,
                    (img.height + side) // 2)).resize((600, 600), Image.LANCZOS)
    data = _jpeg(img, 0)
    photo_path(name).write_bytes(data)
    save_colours(artist_key_of(name), palette(data))
    return True


class Worker:
    """Background: colours for covers that don't have them yet (fast, on this PC), then
    artist photos (one YouTube search per artist, at quiet moments)."""

    def __init__(self, call=None):
        self.call = call  # (profile, fn, *args) at quiet moments: the API's youtube.background
        self._stop = threading.Event()

    def colours_once(self, limit: int = 200) -> int:
        """Work out colours for albums that have none yet (from the cover, or from the album
        name when it has none). Returns how many."""
        from .library import library_for
        with connect() as conn:
            rows = conn.execute(
                "SELECT al.id AS album_id, al.name, al.profile, (SELECT MIN(c.id) FROM tracks c WHERE c.album_id = al.id "
                "AND c.has_cover = 1) AS cover_track FROM albums al WHERE ('al:' || al.id) NOT IN "
                "(SELECT key FROM art_colors) LIMIT ?", (limit,)).fetchall()
        done = 0
        for r in rows:
            if self._stop.is_set():
                break
            c = None
            try:
                data = track_cover(library_for(r["profile"]), r["cover_track"]) if r["cover_track"] else None
                c = palette(data) if data else None
            except Exception as e:  # noqa: BLE001  (a damaged file: name colours instead)
                log.info("No colours for album %s: %s", r["album_id"], e)
            save_colours(album_key(r["album_id"]), c or seed_colours(r["name"] or str(r["album_id"])))
            done += 1
        return done

    def photos_once(self, limit: int = 20) -> int:
        """Look up photos for artists that don't have one (each tried at most monthly)."""
        if self.call is None:
            return 0
        from . import artists
        from .library import library_profiles_of_artists
        done = 0
        for name, profile in library_profiles_of_artists():
            if self._stop.is_set() or done >= limit:
                break
            if photo_path(name).exists() or not artists.photo_due(name):
                continue
            try:
                url = artists.photo_url(lambda fn, *a: self.call(profile, fn, *a), name)
                if url:
                    save_photo(name, url)
            except Exception as e:  # noqa: BLE001  (offline / YouTube trouble: next round)
                log.info("No photo for %r: %s", name, e)
                return done
            artists.photo_tried(name)
            done += 1
        return done

    def _loop(self) -> None:
        from . import settings as settings_mod
        self._stop.wait(60)
        while not self._stop.is_set():
            busy = False
            try:
                busy = self.colours_once() > 0
                if not busy and not settings_mod.load().offline:
                    busy = self.photos_once() > 0
            except Exception:  # noqa: BLE001
                log.exception("Artwork worker failed")
            self._stop.wait(2 if busy else 1800)

    def start(self) -> None:
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True, name="dielify-artwork").start()

    def stop(self) -> None:
        self._stop.set()
