"""0.9.9 stage 1: cover colours, covers that always exist, playlist covers, artist photos."""

import io

import pytest
from PIL import Image

from dielify import artwork, settings
from dielify.library import connect
from dielify.yt_adapter import YTItem
from test_api import login, make_client, setup, wait_done  # noqa: F401


@pytest.fixture(autouse=True)
def pc_profile(setup):
    settings.set_value("active_profile", "josh")


def download(c, h, vid) -> dict:
    job = c.post("/api/downloads", headers=h, json={"type": "song", "id": vid}).json()["downloads"][0]
    return wait_done(c, h, job["id"])


def jpeg(colour, size=(300, 300)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="JPEG")
    return out.getvalue()


def is_jpeg(data: bytes, side: int | None = None) -> bool:
    img = Image.open(io.BytesIO(data))
    return img.format == "JPEG" and (side is None or img.size == (side, side))


def test_palette():
    red = artwork.palette(jpeg((220, 30, 40)))
    r, g, b = (int(red["accent"][i:i + 2], 16) for i in (1, 3, 5))
    assert r > g and r > b                         # the accent is red
    br = sum(int(red["bg"][i:i + 2], 16) for i in (1, 3, 5))
    assert br < 3 * 90 and red["fg"] == "#ffffff"   # the background is dark enough for white text
    grey = artwork.palette(jpeg((128, 128, 128)))
    assert grey["accent"].startswith("#")


def test_covers_always_exist_and_carry_colours():
    with make_client() as c:
        h = login(c)
        one = download(c, h, "s1")
        album = c.get("/api/library/albums", headers=h).json()["albums"][0]
        assert album["cover_url"] and album["colors"] is None    # not worked out yet
        r = c.get(album["cover_url"], headers=h, params={"size": 200})
        assert r.status_code == 200 and is_jpeg(r.content)

        # an album with no art: a cover is drawn for it
        with connect() as conn:
            conn.execute("UPDATE tracks SET has_cover = 0")
        r = c.get(album["cover_url"], headers=h, params={"size": 300})
        assert r.status_code == 200 and is_jpeg(r.content, 300)
        r = c.get(f"/api/library/tracks/{one['track_id']}/cover", headers=h)
        assert r.status_code == 200 and is_jpeg(r.content)

        # the background worker works the colours out; then albums and songs carry them
        assert artwork.Worker().colours_once() == 1
        album = c.get("/api/library/albums", headers=h).json()["albums"][0]
        assert set(album["colors"]) == {"bg", "accent", "fg"}
        assert c.get(f"/api/library/tracks/{one['track_id']}", headers=h).json()["colors"] == album["colors"]


def test_playlist_covers():
    with make_client() as c:
        h = login(c)
        download(c, h, "s1")
        download(c, h, "s3")
        pid = c.post("/api/playlists", headers=h, json={"name": "Car", "on_youtube": False}).json()["playlist"]["id"]
        c.post(f"/api/playlists/{pid}/songs", headers=h, json={"songs": [{"id": "s1", "title": "Song One"},
                                                                         {"id": "s3", "title": "Other Song"}]})
        p = [x for x in c.get("/api/playlists", headers=h).json()["playlists"] if x["id"] == pid][0]
        assert p["cover_url"] == f"/api/playlists/{pid}/cover"
        r = c.get(p["cover_url"], headers=h, params={"size": 400})
        assert r.status_code == 200 and is_jpeg(r.content, 400)
        p = [x for x in c.get("/api/playlists", headers=h).json()["playlists"] if x["id"] == pid][0]
        assert p["colors"] and p["colors"]["bg"].startswith("#")  # known once the cover was drawn

        # a smart playlist gets a designed cover (with its colours straight away)
        sp = c.post("/api/playlists/smart", headers=h, json={"name": "All Band", "rules": {"rules": [
            {"field": "artist", "op": "is", "value": "Band"}]}}).json()["playlist"]
        assert sp["colors"] and is_jpeg(c.get(sp["cover_url"], headers=h).content)


class FakeHttp:
    def get(self, url, timeout=0):
        assert url.startswith("https://lh3.googleusercontent.com/band=w600-h600")
        return type("R", (), {"status_code": 200, "headers": {"content-type": "image/jpeg"},
                              "content": jpeg((30, 90, 200), (400, 300))})()


def test_artist_photos(monkeypatch):
    with make_client() as c:
        h = login(c)
        download(c, h, "s1")
        artist = c.get("/api/library/artists", headers=h).json()["artists"][0]
        before = c.get(artist["image_url"], headers=h)
        assert before.status_code == 200                       # the album cover until there's a photo

        calls = []

        def call(profile, fn, *a):
            calls.append((fn, a[0]))
            return [YTItem("artist", "UCband", "Band", thumbnail="https://lh3.googleusercontent.com/band=w120-h120-l90-rj")]

        monkeypatch.setattr(artwork, "save_photo", lambda name, url, http=None: _save(name, url))

        def _save(name, url):
            return SAVE(name, url, FakeHttp())

        assert artwork.Worker(call).photos_once() == 1
        assert calls == [("search_items", "Band")]
        assert artwork.Worker(call).photos_once() == 0           # tried already: not again this month
        after = c.get(artist["image_url"], headers=h, params={"size": 200})
        assert is_jpeg(after.content, 200) and after.content != before.content
        assert c.get("/api/library/artists", headers=h).json()["artists"][0]["colors"]["accent"]


SAVE = artwork.save_photo
