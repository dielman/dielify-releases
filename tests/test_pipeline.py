"""End-to-end download pipeline with real audio files and a fake YouTube."""

from pathlib import Path

import pytest

from conftest import FakeAdapter, needs_ffmpeg
from ymp import cli
from ymp.downloader import download_track, library_relpath
from ymp.settings import Settings
from ymp.tagging import prepare_cover, read_tags
from ymp.yt_adapter import TrackInfo


def test_library_relpath(sample_info):
    assert library_relpath(sample_info) == Path("Queen/Hot Space/11 Under_ Pressure_")
    single = TrackInfo(video_id="v1", title="Live at Wembley", artists=["Queen"])
    assert library_relpath(single) == Path("Queen/Singles/Live at Wembley")


def test_prepare_cover_crops_video_frames_square():
    from io import BytesIO

    from PIL import Image
    from conftest import make_image
    out = prepare_cover(make_image(1280, 720))
    assert Image.open(BytesIO(out)).size == (720, 720)
    assert Image.open(BytesIO(prepare_cover(make_image(2000, 2000)))).size == (1200, 1200)
    assert prepare_cover(b"not an image") is None


@needs_ffmpeg
@pytest.mark.parametrize("codec,ext,fmt", [("aac", ".m4a", "MP4"), ("opus", ".opus", "OggOpus")])
def test_download_track_tags_and_files(tmp_path, sample_info, codec, ext, fmt):
    s = Settings(library_root=str(tmp_path / "Music"))
    fake = FakeAdapter(sample_info, codec=codec)
    res = download_track(fake, "abc123", s, profile="josh")

    expected = tmp_path / "Music/josh/Queen/Hot Space" / f"11 Under_ Pressure_{ext}"
    assert res.path == expected and expected.exists()
    tags = read_tags(res.path)
    assert tags["format"] == fmt
    assert tags["title"] == "Under: Pressure?"
    assert tags["artist"] in ("Queen, David Bowie", "Queen")  # vorbis keeps a list
    assert tags["album"] == "Hot Space" and tags["album_artist"] == "Queen"
    assert tags["year"] == "1982" and tags["track"] == 11
    assert tags["video_id"] == "abc123"
    assert tags["cover_bytes"] > 1000
    # no leftovers from the temp download folder
    assert not any(p.name.startswith(".ymp-dl-") for p in (tmp_path / "Music/josh").iterdir())

    again = download_track(fake, "abc123", s, profile="josh")
    assert again.already_existed and fake.fetches == 1


@needs_ffmpeg
def test_download_without_album_or_cover(tmp_path):
    info = TrackInfo(video_id="vid9", title="Some Video", artists=["Someone"], is_video=True)
    s = Settings(library_root=str(tmp_path))
    res = download_track(FakeAdapter(info, cover=None), "vid9", s, profile="josh")
    assert res.path == tmp_path / "josh/Someone/Singles/Some Video.m4a"
    assert read_tags(res.path)["cover_bytes"] == 0


def test_cli_config_and_help(tmp_path, capsys):
    assert cli.main(["config", "set", "library_root", str(tmp_path / "Lib")]) == 0
    assert cli.main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert str((tmp_path / "Lib").resolve()) in out
    assert cli.main(["config", "set", "quality", "ultra"]) == 2
    with pytest.raises(SystemExit):
        cli.main(["--help"])


def test_cli_download_needs_login(capsys):
    assert cli.main(["download", "abc123"]) == 2
    assert "not signed in" in capsys.readouterr().out
