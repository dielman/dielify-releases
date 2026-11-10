"""0.9.1: one music store per household, a separate library per person."""

import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAdapter, needs_ffmpeg
from dielify import auth, kids, settings, subsonic_api
from dielify.downloader import download_track
from dielify.downloads import DownloadQueue
from dielify.library import connect, db_path, library_for, person, set_person
from dielify.server import create_app
from dielify.yt_adapter import TrackInfo, YTItem


def info(video_id, title, album="Hot Space", artist="Queen"):
    return TrackInfo(video_id=video_id, title=title, artists=[artist], album=album,
                     album_artist=artist, track_number=1, year="1982",
                     cover_url="https://lh3.googleusercontent.com/x=w120-h120")


@pytest.fixture
def household(tmp_path):
    """Josh (parent, owns the store) with one song; his daughter, a child sharing it."""
    settings.set_value("library_root", str(tmp_path / "Music"))
    s = settings.load()
    download_track(FakeAdapter(info("abc123", "Under Pressure")), "abc123", s, profile="josh")
    set_person("daughter", "child", store="josh")
    return library_for("josh"), library_for("daughter")


def test_old_database_moves_to_per_person_libraries():
    now = time.time()
    with connect() as conn:  # a database as 0.9.0 left it
        ar = conn.execute("INSERT INTO artists (profile, name, starred_at) VALUES ('Josh', 'Queen', ?)", (now,)).lastrowid
        al = conn.execute("INSERT INTO albums (profile, artist_id, name, created_at, starred_at) "
                          "VALUES ('Josh', ?, 'Hot Space', ?, ?)", (ar, now, now)).lastrowid
        tid = conn.execute(
            "INSERT INTO tracks (profile, relpath, album_id, artist_id, title, artist, suffix, size, mtime, "
            "video_id, created_at, play_count, last_played, starred_at, pinned) "
            "VALUES ('Josh', 'Queen/Hot Space/01.opus', ?, ?, 'Under Pressure', 'Queen', 'opus', 1, ?, 'v1', ?, 5, ?, ?, 1)",
            (al, ar, now, now - 100, now - 50, now)).lastrowid
        conn.execute("DELETE FROM library_items")
        conn.execute("DELETE FROM stars")
        conn.execute("DELETE FROM people")
        conn.execute("PRAGMA user_version = 0")
    copy = db_path().with_name("dielify-before-0.9.1.db")
    copy.unlink(missing_ok=True)

    lib = library_for("Josh")  # first connection after the update moves everything
    t = lib.track(tid)
    assert (t["play_count"], t["last_played"], t["starred_at"], t["pinned"]) == (5, now - 50, now, 1)
    assert lib.album(al)["starred_at"] == now and lib.artist(ar)["starred_at"] == now
    assert person("Josh") == {"profile": "Josh", "role": "parent", "store": "Josh"}
    assert person("josh")["profile"] == "Josh"  # same person whatever the case
    assert copy.exists()
    with connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


@needs_ffmpeg
def test_people_share_files_but_not_libraries(household, tmp_path):
    josh, kid = household
    song = josh.track_by_video("abc123")
    assert kid.root == josh.root and kid.store == "josh" and kid.role == "child"
    assert kid.stats()["tracks"] == 0 and kid.track(song["id"]) is None
    assert kid.search("")[2] == [] and kid.album(song["album_id"]) is None

    assert kid.add(song["id"]) and kid.stats()["tracks"] == 1  # no download, same file
    kid.record_play(song["id"])
    kid.set_starred("tracks", song["id"], True)
    kid.set_starred("albums", song["album_id"], True)
    assert josh.track(song["id"])["play_count"] == 0 and josh.track(song["id"])["starred_at"] is None
    assert josh.album(song["album_id"])["starred_at"] is None
    assert kid.track(song["id"])["play_count"] == 1 and kid.album(song["album_id"])["starred_at"]

    # her own new song lands in the shared store, in her library only
    res = download_track(FakeAdapter(info("def456", "Radio Ga Ga", album="The Works")), "def456",
                         settings.load(), profile="daughter")
    assert josh.root in res.path.parents
    assert kid.track_by_video("def456") and josh.track_by_video("def456") is None
    assert set(josh.store_video_ids()) == {"abc123", "def456"}


@needs_ffmpeg
def test_files_go_only_when_no_library_uses_them(household):
    josh, kid = household
    song = josh.track_by_video("abc123")
    path = josh.path_of(song)
    kid.add(song["id"])

    assert josh.remove_track(song["id"])  # she still has it: the file stays
    assert path.exists() and josh.track(song["id"]) is None and kid.track(song["id"])

    assert kid.remove_track(song["id"])  # a child never deletes files
    assert path.exists() and kid.track(song["id"]) is None

    josh.add(song["id"])
    assert josh.remove_track(song["id"]) and not path.exists()  # nobody else: deleted
    assert josh.store_video_ids() == {}


@needs_ffmpeg
def test_queue_reuses_the_store_and_people_take_turns(household):
    josh, kid = household
    q = DownloadQueue(adapter_factory=lambda p: pytest.fail("nothing should download"))
    kids.remember([YTItem("song", "abc123", "Under Pressure", explicit=False)])  # checked: not explicit
    [job] = q.enqueue("daughter", [YTItem("song", "abc123", "Under Pressure")], "song")
    assert job["status"] == "done" and kid.track_by_video("abc123")  # already on the PC

    q.enqueue("josh", [YTItem("song", f"j{i}", f"Josh {i}") for i in range(3)], "playlist")
    q.enqueue("daughter", [YTItem("song", "k0", "Hers")], "song")
    order = []
    for _ in range(4):
        job, _wait = q._next_job()
        order.append(job["video_id"])
        q._set(job["id"], status="done")
    assert order == ["j0", "k0", "j1", "j2"]


@needs_ffmpeg
def test_a_child_cannot_reach_the_parents_songs(household, monkeypatch):
    monkeypatch.setenv("DIELIFY_INSECURE_DEV_STORE", "1")
    subsonic_api.lockout = auth.Lockout()
    josh, kid = household
    auth.add_user("josh", "josh", password="pw1")
    auth.add_user("daughter", "daughter", password="pw2")
    client = TestClient(create_app(), client=("127.0.0.1", 50000))

    def call(user, pw, method, **params):
        token = hashlib.md5((pw + "z").encode()).hexdigest()
        return client.get(f"/rest/{method}", params={"u": user, "t": token, "s": "z", "f": "json", **params}
                          ).json()["subsonic-response"]

    song = call("josh", "pw1", "search3", query="")["searchResult3"]["song"][0]
    assert call("daughter", "pw2", "search3", query="")["searchResult3"].get("song", []) == []
    assert call("daughter", "pw2", "stream", id=song["id"])["error"]["code"] == 70
    assert call("daughter", "pw2", "getAlbum", id=song["albumId"])["error"]["code"] == 70

    kid.add(josh.track_by_video("abc123")["id"])
    assert len(call("daughter", "pw2", "search3", query="")["searchResult3"]["song"]) == 1
