"""0.9.11: songs saved as plain videos during YouTube's empty answers get their album back."""
import dataclasses

from conftest import FakeAdapter, needs_ffmpeg
from dielify import details, library, settings
from dielify.downloader import download_track
from dielify.library import connect, library_for

pytestmark = needs_ffmpeg


def _call(adapter):
    return lambda profile, fn, *a: getattr(adapter, fn)(*a)


def test_a_song_saved_without_its_album_moves_to_its_album(tmp_path, sample_info):
    settings.set_value("library_root", str(tmp_path / "Music"))
    settings.set_value("active_profile", "josh")
    as_video = dataclasses.replace(sample_info, album=None, album_artist=None, track_number=None,
                                   track_total=None, year=None, is_video=True)
    old = download_track(FakeAdapter(as_video), "abc123", settings.load(), profile="josh").path
    assert old.parent.name == "Singles"
    lib = library_for("josh")
    track_id = lib.index_file(old)
    with connect() as conn:
        conn.execute("UPDATE tracks SET play_count = 7 WHERE id = ?", (track_id,))

    assert [t["id"] for t in details.candidates()] == [track_id]
    assert details.fix(details.candidates()[0], _call(FakeAdapter(sample_info))) == "fixed"

    with connect() as conn:
        t = conn.execute("SELECT t.*, al.name AS album FROM tracks t JOIN albums al ON al.id = t.album_id "
                         "WHERE t.id = ?", (track_id,)).fetchone()
    assert (t["album"], t["year"], t["track_no"], t["play_count"]) == ("Hot Space", 1982, 11, 7)
    assert t["relpath"].startswith("Queen/Hot Space/11 ")
    assert lib.path_of(t).exists() and not old.exists() and not old.parent.exists()  # empty Singles gone
    assert details.candidates() == []  # checked once


def test_a_real_music_video_stays_and_is_checked_once(tmp_path, sample_info):
    settings.set_value("library_root", str(tmp_path / "Music"))
    settings.set_value("active_profile", "josh")
    as_video = dataclasses.replace(sample_info, album=None, album_artist=None, track_number=None,
                                   track_total=None, year=None, is_video=True)
    path = download_track(FakeAdapter(as_video), "abc123", settings.load(), profile="josh").path
    library_for("josh").index_file(path)
    assert details.fix(details.candidates()[0], _call(FakeAdapter(as_video))) == "no album"
    assert path.exists() and details.candidates() == []
