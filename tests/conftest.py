import io
import shutil
import subprocess
from pathlib import Path

import pytest

from dielify.yt_adapter import TrackInfo


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own app-data folder; never touches the real one."""
    monkeypatch.setenv("DIELIFY_HOME", str(tmp_path / "appdata"))
    monkeypatch.delenv("DIELIFY_INSECURE_DEV_STORE", raising=False)
    from dielify import lyrics
    monkeypatch.setattr(lyrics, "from_lrclib", lambda *a, **k: None)  # tests never call lrclib.net
    from dielify import kids, kids_home
    kids._pending.clear()  # in-memory state from other tests
    kids_home.forget()
    return tmp_path / "appdata"


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")


def make_audio(dest: Path, codec: str, seconds: int = 3) -> Path:
    """Generate a real audio file shaped like YouTube's (AAC .m4a or Opus .webm)."""
    if codec == "aac":
        out, args = dest / "abc123.m4a", ["-c:a", "aac", "-b:a", "128k"]
    else:
        out, args = dest / "abc123.opus", ["-c:a", "libopus", "-b:a", "96k"]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", *args, str(out)], check=True)
    return out


def make_image(w: int, h: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 40, 60)).save(buf, format="PNG")
    return buf.getvalue()


class FakeAdapter:
    """Stands in for YTMusicAdapter: same interface, no network."""

    def __init__(self, info: TrackInfo, codec: str = "aac", cover=(1200, 1200)):
        self.info, self.codec, self.cover = info, codec, cover
        self.fetches = 0

    def get_track(self, video_id):
        return self.info

    def fetch_cover(self, url):
        return make_image(*self.cover) if self.cover else None

    def fetch_audio(self, video_id, dest_dir, quality, preferred_format, progress=None):
        self.fetches += 1
        if progress:
            progress({"status": "finished"})
        return make_audio(Path(dest_dir), self.codec)


@pytest.fixture
def sample_info():
    return TrackInfo(video_id="abc123", title="Under: Pressure?", artists=["Queen", "David Bowie"],
                     album="Hot Space", album_artist="Queen", track_number=11,
                     track_total=11, year="1982", duration_s=248,
                     cover_url="https://lh3.googleusercontent.com/x=w120-h120-l90-rj")
