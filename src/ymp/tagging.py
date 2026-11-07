"""Embed tags and cover art so every file stands on its own in any player."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from mutagen.flac import Picture

from .yt_adapter import TrackInfo

VIDEOID_TAG = "YMP_VIDEOID"
MP4_VIDEOID_KEY = "----:com.ymp:videoId"


def prepare_cover(data: bytes | None, max_size: int = 1200) -> bytes | None:
    """Return square JPEG cover art. Video thumbnails (16:9) are centre-cropped."""
    if not data:
        return None
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    img = img.convert("RGB")
    w, h = img.size
    if w != h:
        side = min(w, h)
        left, top = (w - side) // 2, (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
    if img.width > max_size:
        img = img.resize((max_size, max_size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _year(info: TrackInfo) -> str | None:
    return info.year if info.year and info.year[:4].isdigit() else None


def tag_file(path: Path, info: TrackInfo, cover_jpeg: bytes | None) -> None:
    ext = path.suffix.lower()
    if ext == ".m4a":
        _tag_mp4(path, info, cover_jpeg)
    elif ext in (".opus", ".ogg"):
        _tag_ogg(path, info, cover_jpeg)
    elif ext == ".mp3":
        _tag_mp3(path, info, cover_jpeg)
    elif ext == ".flac":
        _tag_flac(path, info, cover_jpeg)
    else:
        raise ValueError(f"Don't know how to tag {ext} files")


def _tag_mp4(path: Path, info: TrackInfo, cover: bytes | None) -> None:
    from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
    f = MP4(path)
    if f.tags is None:
        f.add_tags()
    t = f.tags
    t["\xa9nam"] = [info.title]
    t["\xa9ART"] = [info.artist]
    if info.album:
        t["\xa9alb"] = [info.album]
    if info.album_artist:
        t["aART"] = [info.album_artist]
    if _year(info):
        t["\xa9day"] = [_year(info)]
    if info.track_number:
        t["trkn"] = [(info.track_number, info.track_total or 0)]
    t[MP4_VIDEOID_KEY] = [MP4FreeForm(info.video_id.encode())]
    if cover:
        t["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    f.save()


def _picture(cover: bytes) -> Picture:
    from PIL import Image
    pic = Picture()
    pic.type = 3  # front cover
    pic.mime = "image/jpeg"
    pic.desc = "Cover"
    pic.data = cover
    w, h = Image.open(io.BytesIO(cover)).size
    pic.width, pic.height, pic.depth = w, h, 24
    return pic


def _vorbis_fields(info: TrackInfo) -> dict[str, list[str]]:
    d = {"title": [info.title], "artist": info.artists or ["Unknown Artist"],
         VIDEOID_TAG: [info.video_id]}
    if info.album:
        d["album"] = [info.album]
    if info.album_artist:
        d["albumartist"] = [info.album_artist]
    if _year(info):
        d["date"] = [_year(info)]
    if info.track_number:
        d["tracknumber"] = [str(info.track_number)]
    if info.track_total:
        d["tracktotal"] = [str(info.track_total)]
    return d


def _tag_ogg(path: Path, info: TrackInfo, cover: bytes | None) -> None:
    import mutagen
    f = mutagen.File(path)
    if f is None:
        raise ValueError(f"Not a readable Ogg file: {path}")
    if f.tags is None:
        f.add_tags()
    for k, v in _vorbis_fields(info).items():
        f.tags[k] = v
    if cover:
        f.tags["metadata_block_picture"] = [
            base64.b64encode(_picture(cover).write()).decode("ascii")]
    f.save()


def _tag_flac(path: Path, info: TrackInfo, cover: bytes | None) -> None:
    from mutagen.flac import FLAC
    f = FLAC(path)
    for k, v in _vorbis_fields(info).items():
        f[k] = v
    if cover:
        f.clear_pictures()
        f.add_picture(_picture(cover))
    f.save()


def _tag_mp3(path: Path, info: TrackInfo, cover: bytes | None) -> None:
    from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK, TXXX, ID3NoHeaderError
    try:
        t = ID3(path)
    except ID3NoHeaderError:
        t = ID3()
    t.add(TIT2(encoding=3, text=info.title))
    t.add(TPE1(encoding=3, text=info.artist))
    if info.album:
        t.add(TALB(encoding=3, text=info.album))
    if info.album_artist:
        t.add(TPE2(encoding=3, text=info.album_artist))
    if _year(info):
        t.add(TDRC(encoding=3, text=_year(info)))
    if info.track_number:
        trk = f"{info.track_number}/{info.track_total}" if info.track_total else str(info.track_number)
        t.add(TRCK(encoding=3, text=trk))
    t.add(TXXX(encoding=3, desc=VIDEOID_TAG, text=info.video_id))
    if cover:
        t.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    t.save(path)


def read_tags(path: Path) -> dict:
    """Small normalised view of a file's tags (used by tests and `ymp inspect`)."""
    import mutagen
    f = mutagen.File(path)
    if f is None:
        raise ValueError(f"Unreadable audio file: {path}")
    ext = path.suffix.lower()
    out: dict = {"format": type(f).__name__, "length_s": round(f.info.length, 1),
                 "bitrate_kbps": round(getattr(f.info, "bitrate", 0) / 1000) or None}
    if ext == ".m4a":
        t = f.tags or {}
        g = lambda k: (t.get(k) or [None])[0]
        out.update(title=g("\xa9nam"), artist=g("\xa9ART"), album=g("\xa9alb"),
                   album_artist=g("aART"), year=g("\xa9day"),
                   track=(g("trkn") or (None,))[0],
                   video_id=bytes(g(MP4_VIDEOID_KEY)).decode() if g(MP4_VIDEOID_KEY) else None,
                   cover_bytes=len(g("covr")) if g("covr") else 0)
    elif ext in (".opus", ".ogg", ".flac"):
        t = f.tags
        g = lambda k: (t.get(k) or [None])[0]
        pics = len(f.pictures[0].data) if ext == ".flac" and f.pictures else 0
        if not pics and g("metadata_block_picture"):
            pics = len(Picture(base64.b64decode(g("metadata_block_picture"))).data)
        out.update(title=g("title"), artist=g("artist"), album=g("album"),
                   album_artist=g("albumartist"), year=g("date"),
                   track=int(g("tracknumber")) if g("tracknumber") else None,
                   video_id=g(VIDEOID_TAG.lower()) or g(VIDEOID_TAG), cover_bytes=pics)
    elif ext == ".mp3":
        t = f.tags
        txt = lambda k: str(t[k].text[0]) if k in t else None
        apic = next((fr for k, fr in t.items() if k.startswith("APIC")), None)
        out.update(title=txt("TIT2"), artist=txt("TPE1"), album=txt("TALB"),
                   album_artist=txt("TPE2"), year=txt("TDRC"),
                   track=int(txt("TRCK").split("/")[0]) if txt("TRCK") else None,
                   video_id=txt(f"TXXX:{VIDEOID_TAG}"),
                   cover_bytes=len(apic.data) if apic else 0)
    return out


def read_cover(path: Path) -> bytes | None:
    """The embedded front cover's image bytes, or None."""
    import mutagen
    f = mutagen.File(path)
    if f is None or f.tags is None:
        return None
    ext = path.suffix.lower()
    if ext == ".m4a":
        covers = f.tags.get("covr")
        return bytes(covers[0]) if covers else None
    if ext == ".flac":
        return f.pictures[0].data if f.pictures else None
    if ext in (".opus", ".ogg"):
        blocks = f.tags.get("metadata_block_picture")
        return Picture(base64.b64decode(blocks[0])).data if blocks else None
    if ext == ".mp3":
        apic = next((fr for k, fr in f.tags.items() if k.startswith("APIC")), None)
        return apic.data if apic else None
    return None
