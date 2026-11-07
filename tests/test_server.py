"""Library index + Subsonic API, against real tagged files and a temp database."""

import hashlib
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAdapter, needs_ffmpeg
from ymp import auth, settings, subsonic_api
from ymp.downloader import download_track
from ymp.library import Library
from ymp.server import bind_addresses, create_app
from ymp.yt_adapter import TrackInfo

pytestmark = needs_ffmpeg


@pytest.fixture(autouse=True)
def dev_store(monkeypatch):
    # Server users go through the credential store; DPAPI on Windows, dev store elsewhere.
    monkeypatch.setenv("YMP_INSECURE_DEV_STORE", "1")
    subsonic_api.lockout = auth.Lockout()
    subsonic_api._cover_bytes.cache_clear()


@pytest.fixture
def library(tmp_path, sample_info):
    settings.set_value("library_root", str(tmp_path / "Music"))
    s = settings.load()
    download_track(FakeAdapter(sample_info, codec="aac"), "abc123", s, profile="josh")
    other = TrackInfo(video_id="def456", title="Radio Ga Ga", artists=["Queen"], album="The Works",
                      album_artist="Queen", track_number=1, year="1984",
                      cover_url="https://lh3.googleusercontent.com/y=w120-h120")
    download_track(FakeAdapter(other, codec="opus"), "def456", s, profile="josh")
    return Library("josh", s.profile_library("josh"))


@pytest.fixture
def client(library):
    user = auth.add_user("josh", "josh", password="sesame")
    c = TestClient(create_app())
    c.user = user
    return c


def call(client, method, f="json", password="sesame", **params):
    salt = "abc123salt"
    token = hashlib.md5((password + salt).encode()).hexdigest()
    r = client.get(f"/rest/{method}.view", params={"u": "josh", "t": token, "s": salt, "v": "1.16.1",
                                                   "c": "test", "f": f, **params})
    assert r.status_code == 200
    return r


def ok(client, method, **params) -> dict:
    body = call(client, method, **params).json()["subsonic-response"]
    assert body["status"] == "ok", body
    return body


def test_downloads_are_indexed_automatically(library):
    st = library.stats()
    assert (st["tracks"], st["albums"], st["artists"]) == (2, 2, 1)
    assert library.scan().unchanged == 2


def test_scan_follows_track_to_new_path(library, sample_info, tmp_path):
    t = next(t for t in library.search("pressure")[2])
    library.record_play(t["id"])
    old = library.path_of(t)
    new = old.parent.parent / "Hot Space (Remaster)" / old.name
    new.parent.mkdir()
    old.rename(new)  # same video id, new place (e.g. re-downloaded under a new name)
    res = library.scan()
    assert (res.added, res.updated, res.removed) == (0, 1, 0)
    moved = library.track(t["id"])
    assert "Remaster" in moved["relpath"] and moved["play_count"] == 1


def test_login_token_password_and_failures(client):
    assert ok(client, "ping")["openSubsonic"] is True
    r = client.get("/rest/ping", params={"u": "josh", "p": "enc:" + b"sesame".hex(), "f": "json"})
    assert r.json()["subsonic-response"]["status"] == "ok"
    bad = call(client, "ping", password="wrong").json()["subsonic-response"]
    assert bad["status"] == "failed" and bad["error"]["code"] == 40
    nobody = client.get("/rest/ping", params={"u": "eve", "p": "x", "f": "json"}).json()
    assert nobody["subsonic-response"]["error"]["code"] == 40


def test_lockout_after_repeated_failures(client):
    for _ in range(auth.MAX_FAILURES):
        call(client, "ping", password="wrong")
    locked = call(client, "ping").json()["subsonic-response"]  # right password, still locked
    assert locked["status"] == "failed" and "Too many" in locked["error"]["message"]


def test_extensions_are_public(client):
    r = client.get("/rest/getOpenSubsonicExtensions", params={"f": "json"}).json()
    assert r["subsonic-response"]["openSubsonicExtensions"][0]["name"] == "formPost"


def test_browse_artist_album_song(client):
    index = ok(client, "getArtists")["artists"]["index"]
    queen = index[0]["artist"][0]
    assert (index[0]["name"], queen["name"], queen["albumCount"]) == ("Q", "Queen", 2)
    albums = ok(client, "getArtist", id=queen["id"])["artist"]["album"]
    assert [a["name"] for a in albums] == ["Hot Space", "The Works"]  # by year
    hot = ok(client, "getAlbum", id=albums[0]["id"])["album"]
    s = hot["song"][0]
    assert (s["title"], s["track"], s["year"], s["suffix"], s["contentType"]) == \
        ("Under: Pressure?", 11, 1982, "m4a", "audio/mp4")
    assert ok(client, "getSong", id=s["id"])["song"]["albumId"] == albums[0]["id"]
    missing = call(client, "getAlbum", id="al-999").json()["subsonic-response"]
    assert missing["error"]["code"] == 70


def test_folder_browsing_for_older_clients(client):
    idx = ok(client, "getIndexes")["indexes"]["index"][0]["artist"][0]
    d = ok(client, "getMusicDirectory", id=idx["id"])["directory"]
    assert all(c["isDir"] for c in d["child"])
    songs = ok(client, "getMusicDirectory", id=d["child"][0]["id"])["directory"]["child"]
    assert songs and not songs[0]["isDir"]


def test_search_and_full_sync(client):
    r = ok(client, "search3", query="radio")["searchResult3"]
    assert [s["title"] for s in r["song"]] == ["Radio Ga Ga"]
    everything = ok(client, "search3", query='""', songCount=500)["searchResult3"]
    assert len(everything["song"]) == 2 and len(everything["album"]) == 2
    page2 = ok(client, "search3", query="", songCount=1, songOffset=1)["searchResult3"]
    assert len(page2["song"]) == 1


def test_album_lists(client):
    assert len(ok(client, "getAlbumList2", type="newest")["albumList2"]["album"]) == 2
    years = ok(client, "getAlbumList2", type="byYear", fromYear=1983, toYear=1990)
    assert [a["name"] for a in years["albumList2"]["album"]] == ["The Works"]
    assert ok(client, "getAlbumList", type="byGenre", genre="Rock")["albumList"]["album"] == []


def test_stream_whole_and_range(client, library):
    s = ok(client, "search3", query="pressure")["searchResult3"]["song"][0]
    full = call(client, "stream", id=s["id"])
    assert full.headers["content-type"] == "audio/mp4" and len(full.content) == s["size"]
    salt, token = "x1", hashlib.md5(b"sesamex1").hexdigest()
    part = client.get("/rest/stream", params={"u": "josh", "t": token, "s": salt, "id": s["id"]},
                      headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == full.content[100:200]


def test_cover_art_and_resize(client):
    al = ok(client, "getAlbumList2", type="newest")["albumList2"]["album"][0]
    big = call(client, "getCoverArt", id=al["coverArt"])
    small = call(client, "getCoverArt", id=al["coverArt"], size=100)
    assert big.headers["content-type"] == "image/jpeg" and len(small.content) < len(big.content)
    from io import BytesIO

    from PIL import Image
    assert Image.open(BytesIO(small.content)).size == (100, 100)
    artist_id = al["artistId"]
    assert call(client, "getCoverArt", id=artist_id).headers["content-type"] == "image/jpeg"


def test_star_and_scrobble(client):
    s = ok(client, "search3", query="radio")["searchResult3"]["song"][0]
    ok(client, "star", id=s["id"], albumId=s["albumId"])
    starred = ok(client, "getStarred2")["starred2"]
    assert [x["id"] for x in starred["song"]] == [s["id"]] and len(starred["album"]) == 1
    ok(client, "unstar", id=s["id"])
    assert ok(client, "getStarred2")["starred2"]["song"] == []
    ok(client, "scrobble", id=s["id"], submission="false")
    ok(client, "scrobble", id=s["id"])
    assert ok(client, "getSong", id=s["id"])["song"]["playCount"] == 1
    assert [a["name"] for a in ok(client, "getAlbumList2", type="frequent")["albumList2"]["album"]] \
        == ["The Works"]


def test_xml_format_and_form_post(client):
    root = ET.fromstring(call(client, "getAlbumList2", f="xml", type="newest").content)
    ns = {"s": subsonic_api.XMLNS}
    assert root.get("status") == "ok" and root.get("openSubsonic") == "true"
    assert len(root.findall("s:albumList2/s:album", ns)) == 2
    user = ET.fromstring(call(client, "getUser", f="xml").content).find("s:user", ns)
    assert user.get("streamRole") == "true" and user.find("s:folder", ns).text == "1"
    salt, token = "y2", hashlib.md5(b"sesamey2").hexdigest()
    r = client.post("/rest/ping.view", data={"u": "josh", "t": token, "s": salt, "f": "json"})
    assert r.json()["subsonic-response"]["status"] == "ok"


def test_unknown_method_and_logs_without_secrets(client, caplog):
    caplog.set_level("INFO", logger="ymp.server")
    caplog.set_level("INFO", logger="ymp.subsonic_api")
    r = call(client, "createPlaylist", name="x").json()["subsonic-response"]
    assert r["status"] == "failed" and "Not implemented" in r["error"]["message"]
    assert "/rest/createPlaylist.view" in caplog.text and "name='x'" in caplog.text
    assert "u='josh'" in caplog.text
    assert "t=" not in caplog.text and "s=" not in caplog.text and "sesame" not in caplog.text


def test_profiles_are_isolated(client, library):
    auth.add_user("daughter", "daughter", password="pw2")
    salt, token = "z", hashlib.md5(b"pw2z").hexdigest()
    r = client.get("/rest/search3", params={"u": "daughter", "t": token, "s": salt, "f": "json",
                                            "query": ""}).json()["subsonic-response"]
    assert r["searchResult3"]["song"] == []
    s = ok(client, "search3", query="radio")["searchResult3"]["song"][0]
    r = client.get("/rest/stream", params={"u": "daughter", "t": token, "s": salt, "f": "json",
                                           "id": s["id"]}).json()["subsonic-response"]
    assert r["error"]["code"] == 70


def test_bind_addresses_never_public_or_all_interfaces():
    s = settings.Settings()
    assert bind_addresses(s)[0] == "127.0.0.1"
    for bad in ("0.0.0.0", "::", "8.8.8.8", "192.168.1.5,0.0.0.0"):
        with pytest.raises(ValueError):
            settings.Settings(server_bind=bad).validate()
    settings.Settings(server_bind="192.168.1.5,100.101.102.103,127.0.0.1").validate()


def test_user_management():
    u = auth.add_user("josh", "josh")
    assert len(u.password) == 20 and auth.get_user("josh").password == u.password
    with pytest.raises(ValueError):
        auth.add_user("josh", "josh")
    with pytest.raises(ValueError):
        auth.add_user("../evil", "x")
    assert auth.set_password("josh").password != u.password
    assert [x.name for x in auth.list_users()] == ["josh"]
    assert auth.remove_user("josh") and auth.get_user("josh") is None
