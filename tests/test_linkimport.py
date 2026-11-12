"""Playlists from a Spotify or YouTube link (12 Nov): a new Dielify playlist of those songs."""

import time

import pytest

from dielify import custom_api, linkimport, settings
from dielify.linkimport import ExtSong, Link, parse
from test_api import SONGS, FakeDownloader, FakeYT, item, login, make_client, setup  # noqa: F401
from test_kids_accounts import add_kid


class FakeSearchYT(FakeYT):
    """Search like YouTube: "<artist> <title>" finds the song with that title."""

    def search_items(self, q, kind="song", limit=20):
        return [item(v) for v in SONGS if SONGS[v].title.lower() in q.lower()][:limit]


@pytest.fixture
def yt(monkeypatch, setup):
    monkeypatch.setattr(custom_api, "YTMusicAdapter", FakeSearchYT)
    custom_api.youtube.reset()


@pytest.mark.parametrize("url, want", [
    ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc", ("spotify", "playlist", "37i9dQZF1DXcBWIGoYBM5M")),
    ("open.spotify.com/intl-de/album/4aawyAB9vmqN3uQ7FjRGTy", ("spotify", "album", "4aawyAB9vmqN3uQ7FjRGTy")),
    ("https://open.spotify.com/embed/playlist/abc123", ("spotify", "playlist", "abc123")),
    ("spotify:playlist:abc123", ("spotify", "playlist", "abc123")),
    ("https://music.youtube.com/playlist?list=PLabc_-1", ("youtube", "playlist", "PLabc_-1")),
    ("https://www.youtube.com/watch?v=xyz&list=PLabc", ("youtube", "playlist", "PLabc")),
    ("https://youtube.com/playlist?list=OLAK5uy_abc", ("youtube", "playlist", "OLAK5uy_abc")),
    ("https://music.youtube.com/browse/MPREb_abc", ("youtube", "album", "MPREb_abc")),
])
def test_links_it_understands(url, want):
    link = parse(url)
    assert (link.source, link.kind, link.id) == want


@pytest.mark.parametrize("url", [
    "https://open.spotify.com/track/abc",          # a song, not a list
    "https://www.youtube.com/watch?v=xyz",         # a video
    "https://www.youtube.com/watch?v=xyz&list=RDxyz",  # a mix: never ends
    "https://example.com/playlist?list=PLabc",     # someone else's site
    "hello",
])
def test_links_it_refuses_in_words(url):
    with pytest.raises(ValueError):
        parse(url)


class FakePage:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_reads_spotifys_embed_page():
    page = ('<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"state":{"data":'
            '{"entity":{"name":"Road trip","trackList":[{"title":"Song One","subtitle":"Band","duration":200000},'
            '{"title":"Other Song","subtitle":"Someone,\\u00a0Guest","duration":181500},{"title":"","subtitle":"x"}]}}}}}}'
            '</script></html>')

    class Http:
        def get(self, url, **kw):
            assert url == "https://open.spotify.com/embed/playlist/abc"
            return FakePage(page)
    name, songs = linkimport.spotify_list("playlist", "abc", http=Http())
    assert name == "Road trip"
    assert songs == [ExtSong("Band", "Song One", 200), ExtSong("Someone, Guest", "Other Song", 182)]


def wait(c, h, job_id, timeout=10) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/playlists/from-link/{job_id}", headers=h).json()
        if j["state"] != "working":
            return j
        time.sleep(0.05)
    raise AssertionError("import didn't finish")


def videos(c, h, pid):
    return [e["item"]["id"] for e in c.get(f"/api/playlists/{pid}", headers=h).json()["entries"]]


def test_spotify_link_makes_a_dielify_playlist(yt, monkeypatch):
    songs = [ExtSong("Band", "Song One"), ExtSong("Nobody", "Not On YouTube"), ExtSong("Someone", "Other Song"),
             ExtSong("Band", "Song One")]  # twice on Spotify: once here
    monkeypatch.setattr(linkimport, "spotify_list", lambda kind, sid: ("Gym", songs))
    with make_client(FakeDownloader()) as c:
        h = login(c)
        r = c.post("/api/playlists/from-link", headers=h, json={"url": "https://open.spotify.com/playlist/abc"})
        assert r.status_code == 202, r.text
        j = wait(c, h, r.json()["id"])
        assert (j["state"], j["name"], j["total"], j["added"]) == ("done", "Gym", 4, 2)
        assert j["missing"] == ["Nobody – Not On YouTube"]
        assert videos(c, h, j["playlist_id"]) == ["s1", "s3"]
        pl = c.get(f"/api/playlists/{j['playlist_id']}", headers=h).json()["playlist"]
        assert pl["yt_id"] is None and not pl["read_only"]  # Dielify's own, editable
        assert {d["video_id"] for d in c.get("/api/downloads", headers=h).json()["downloads"]} == {"s1", "s3"}


def test_youtube_link_copies_the_playlist(yt):
    with make_client(FakeDownloader()) as c:
        h = login(c)
        r = c.post("/api/playlists/from-link", headers=h,
                   json={"url": "https://music.youtube.com/playlist?list=PLsomeone"})
        j = wait(c, h, r.json()["id"])
        assert (j["state"], j["name"], j["added"]) == ("done", "Mix", 2)
        assert videos(c, h, j["playlist_id"]) == ["s3", "s1"]


def test_bad_links_and_other_peoples_imports(yt):
    with make_client(FakeDownloader()) as c:
        h = login(c)
        r = c.post("/api/playlists/from-link", headers=h, json={"url": "https://open.spotify.com/track/abc"})
        assert r.status_code == 400 and "playlist or an album" in r.json()["detail"]
        assert c.get("/api/playlists/from-link/nope", headers=h).status_code == 404


def test_a_kid_cant_import_the_parents_own_youtube_playlists(yt):
    settings.set_value("active_profile", "josh")
    with make_client(FakeDownloader()) as c:
        login(c)
        kid = add_kid(c)
        for lst in ("LM", "PLmine"):  # his Liked Music, a playlist in his library
            r = c.post("/api/playlists/from-link", headers=kid,
                       json={"url": f"https://music.youtube.com/playlist?list={lst}"})
            assert r.status_code == 403, lst


def test_youtube_not_answering_stops_the_import_instead_of_calling_every_song_missing(yt, monkeypatch):
    songs = [ExtSong("Band", "Song One")] + [ExtSong("Someone", f"Song {n}") for n in range(10)]
    monkeypatch.setattr(linkimport, "spotify_list", lambda kind, sid: ("Gym", songs))
    real = FakeSearchYT.search_items

    def flaky(self, q, kind="song", limit=20):
        if "Song One" not in q:
            raise custom_api.YouTubeError("YouTube can not be reached")
        return real(self, q, kind, limit)
    monkeypatch.setattr(FakeSearchYT, "search_items", flaky)
    with make_client(FakeDownloader()) as c:
        h = login(c)
        j = wait(c, h, c.post("/api/playlists/from-link", headers=h,
                              json={"url": "https://open.spotify.com/playlist/abc"}).json()["id"])
        assert j["state"] == "failed" and "isn't answering" in j["error"] and "4 of 11" in j["error"]
        assert j["added"] == 1 and videos(c, h, j["playlist_id"]) == ["s1"]   # what it found stays


def test_a_failed_import_leaves_no_empty_playlist(yt, monkeypatch):
    monkeypatch.setattr(linkimport, "spotify_list", lambda kind, sid: ("Gym", [ExtSong("A", f"x{n}") for n in range(5)]))
    monkeypatch.setattr(FakeSearchYT, "search_items", lambda self, q, kind="song", limit=20: (_ for _ in ()).throw(
        custom_api.YouTubeError("YouTube can not be reached")))
    with make_client(FakeDownloader()) as c:
        h = login(c)
        j = wait(c, h, c.post("/api/playlists/from-link", headers=h,
                              json={"url": "https://open.spotify.com/playlist/abc"}).json()["id"])
        assert j["state"] == "failed" and j["playlist_id"] is None
        assert not [p for p in c.get("/api/playlists", headers=h).json()["playlists"] if p["name"] == "Gym"]
