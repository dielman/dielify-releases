"""0.9.4: remove songs from your library; song radio and artist radio; the background
check never makes people wait."""

import time

import pytest

from dielify import auth, custom_api, kids, library, settings
from dielify.yt_adapter import YTItem
from test_api import SONGS, FakeYT, item, login, make_client, setup, wait_done  # noqa: F401


@pytest.fixture(autouse=True)
def pc_profile(setup):
    settings.set_value("active_profile", "josh")


def download(c, h, vid) -> dict:
    job = c.post("/api/downloads", headers=h, json={"type": "song", "id": vid}).json()["downloads"][0]
    return wait_done(c, h, job["id"])


def test_remove_a_song_and_an_album():
    with make_client() as c:
        h = login(c)
        one, two = download(c, h, "s1"), download(c, h, "s2")
        lib = library.library_for("josh")
        path = lib.path_of(lib.track(one["track_id"]))

        # a kids account has song one too: removing it keeps the file
        r = c.post("/api/desktop/people", headers={"Authorization": f"Bearer {auth.enable_desktop_token()}"},
                   json={"name": "emma"})
        kid = login(c, "emma", r.json()["password"])
        library.library_for("emma").add(one["track_id"])
        assert c.delete(f"/api/library/tracks/{one['track_id']}", headers=h).json() == {"removed": 1, "deleted": 0}
        assert path.exists() and c.get(f"/api/library/tracks/{one['track_id']}", headers=h).status_code == 404

        # she removes it: a child never deletes files
        assert c.delete(f"/api/library/tracks/{one['track_id']}", headers=kid).json() == {"removed": 1, "deleted": 0}
        assert path.exists()

        # Josh removes the album (song two, only his): its file goes
        album = c.get(f"/api/library/tracks/{two['track_id']}", headers=h).json()
        albums = c.get("/api/library/albums", headers=h).json()["albums"]
        r = c.delete(f"/api/library/albums/{albums[0]['id']}", headers=h).json()
        assert r == {"removed": 1, "deleted": 1} and album["title"] == "Song Two"
        assert c.get("/api/library/albums", headers=h).json()["albums"] == []
        assert c.delete(f"/api/library/tracks/{two['track_id']}", headers=h).status_code == 404


class RadioYT(FakeYT):
    def artist_radio(self, channel_id, limit=50):
        assert channel_id == "UCband"
        return [item("s2"), item("s1")]

    def search_items(self, q, kind="song", limit=20):
        if kind == "artist":
            return [YTItem("artist", "UCband", "Band")]
        return super().search_items(q, kind, limit)


def test_song_and_artist_radio(monkeypatch):
    monkeypatch.setattr(custom_api, "YTMusicAdapter", RadioYT)
    custom_api.youtube.reset()
    with make_client() as c:
        h = login(c)
        song = c.post("/api/radio", headers=h, json={"video_id": "s1"}).json()["items"]
        assert [i["id"] for i in song] == ["s2", "s3"]                       # like s1, without s1
        more = c.post("/api/radio", headers=h, json={"seeds": ["s1", "s2"], "exclude": ["s1", "s2"]}).json()["items"]
        assert [i["id"] for i in more] == ["s3"]
        assert [i["id"] for i in c.post("/api/radio", headers=h, json={"artist_id": "UCband"}).json()["items"]] == ["s2", "s1"]
        assert [i["id"] for i in c.post("/api/radio", headers=h, json={"artist": "band"}).json()["items"]] == ["s2", "s1"]
        assert c.post("/api/radio", headers=h, json={}).status_code == 400
        # nothing was queued for download (radio songs download only when played)
        assert c.get("/api/downloads", headers=h).json()["downloads"] == []


def test_background_check_waits_for_people(monkeypatch):
    calls = []
    yt = custom_api._YouTube()
    monkeypatch.setattr(custom_api, "YTMusicAdapter", lambda **k: type("A", (), {
        "search_items": lambda self, q, *a: calls.append(q) or []})())
    yt.call("josh", "search_items", "x", "song", 1)            # someone just used the app
    started = time.monotonic()
    yt.background("josh", "search_items", "y", "song", 1)      # waits ~3 s for a quiet moment
    assert time.monotonic() - started >= 2.5
    assert [q for q in calls if q in ("x", "y", "z")] == ["x", "y"]  # (other tests' background jobs may search too)
    yt._last_person = 0.0
    started = time.monotonic()
    yt.background("josh", "search_items", "z", "song", 1)      # nobody busy: straight away
    assert time.monotonic() - started < 1
