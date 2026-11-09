"""0.9.5 Discovery: leave out of my taste, the time-of-day mix, new releases from your
artists (follows, auto-download, kids), artist About and Subsonic's getArtistInfo2."""

import time
from datetime import date, datetime

import pytest

from dielify import artists, auth, custom_api, history, library, nowmix, releases, settings, taste
from dielify.library import connect
from dielify.yt_adapter import YTItem
from test_api import SONGS, FakeYT, item, login, make_client, setup, wait_done  # noqa: F401

THIS_YEAR = str(date.today().year)


@pytest.fixture(autouse=True)
def pc_profile(setup):
    settings.set_value("active_profile", "josh")


def download(c, h, vid) -> dict:
    job = c.post("/api/downloads", headers=h, json={"type": "song", "id": vid}).json()["downloads"][0]
    return wait_done(c, h, job["id"])


def play(track_id, video_id, artist="Band", when=None, profile="josh", n=1):
    with connect() as conn:
        for i in range(n):
            conn.execute("INSERT INTO plays (profile, client_id, track_id, video_id, title, artist, counted, "
                         "started_at, device) VALUES (?,?,?,?,?,?,1,?,?)",
                         (profile, f"{video_id}-{when}-{i}-{time.monotonic_ns()}", track_id, video_id, "t", artist,
                          (when or time.time()) - i, "test"))


def test_leave_out_of_my_taste():
    with make_client() as c:
        h = login(c)
        one, two = download(c, h, "s1"), download(c, h, "s3")
        lib = library.library_for("josh")
        play(one["track_id"], "s1", n=5)
        play(two["track_id"], "s3", artist="Someone", n=3)
        assert history.seeds(lib, limit=2) == ["s1", "s3"]
        assert set(history.on_repeat(lib)) == {one["track_id"], two["track_id"]}

        r = c.put("/api/taste", headers=h, json={"kind": "song", "key": "s1", "name": "Song One - Band"})
        assert [i["key"] for i in r.json()["items"]] == ["s1"]
        assert history.seeds(lib, limit=2) == ["s3"]
        assert history.on_repeat(lib) == [two["track_id"]]
        assert history.top_artists(lib) == ["Someone"]

        # a playlist left out leaves out the songs in it
        pid = c.post("/api/playlists", headers=h, json={"name": "Kids party", "on_youtube": False}).json()["playlist"]["id"]
        c.post(f"/api/playlists/{pid}/songs", headers=h, json={"songs": [{"id": "s3", "title": "Other Song"}]})
        c.put("/api/taste", headers=h, json={"kind": "playlist", "key": str(pid), "name": "Kids party"})
        assert history.seeds(lib) == [] and history.top_artists(lib) == []
        assert taste.Taste("josh").out(track_id=two["track_id"])

        c.put("/api/taste", headers=h, json={"kind": "song", "key": "s1", "name": "x", "out": False})
        assert history.seeds(lib) == ["s1"]
        assert [i["kind"] for i in c.get("/api/taste", headers=h).json()["items"]] == ["playlist"]


def test_time_of_day_mix(monkeypatch):
    monkeypatch.setattr(nowmix, "MIN_SONGS", 2)
    with make_client() as c:
        h = login(c)
        one, two, three = download(c, h, "s1"), download(c, h, "s2"), download(c, h, "s3")
        lib = library.library_for("josh")
        evening = datetime(2026, 11, 10, 19, 30).timestamp()          # a Tuesday
        morning = datetime(2026, 11, 10, 8, 0).timestamp()
        play(one["track_id"], "s1", when=evening, n=4)
        play(two["track_id"], "s2", when=evening + 3600)
        play(three["track_id"], "s3", when=morning, n=6)
        m = nowmix.build(lib, datetime(2026, 11, 17, 19, 0))
        assert m.title == "Your Tuesday evening"
        assert set(m.track_ids) == {one["track_id"], two["track_id"]}   # nothing from the morning
        assert m.track_ids == nowmix.build(lib, datetime(2026, 11, 17, 20, 0)).track_ids  # same all evening
        assert nowmix.build(lib, datetime(2026, 11, 17, 13, 0)) is None  # too little at lunchtime
        assert nowmix.part_of_day(2) == "late night" and nowmix.part_of_day(23) == "late night"
        c.put("/api/taste", headers=h, json={"kind": "song", "key": "s2", "name": "x"})
        assert nowmix.build(lib, datetime(2026, 11, 17, 19, 0)) is None  # one song left: too few


class ArtistYT(FakeYT):
    pages: dict = {}

    def search_items(self, q, kind="song", limit=20):
        if kind == "artist":
            return [YTItem("artist", "UCwrong", "Band Tribute"), YTItem("artist", "UCband", "Band")]
        return super().search_items(q, kind, limit)

    def artist_page(self, channel_id):
        assert channel_id == "UCband"
        return {"name": "Band", "description": "Band are a band.", "thumbnail": "https://img/band.jpg",
                "albums": ArtistYT.pages.get("albums", []), "singles": ArtistYT.pages.get("singles", [])}

    def album(self, browse_id):
        if browse_id == "MPREb_new":
            return YTItem("album", browse_id, "Second", ["Band"], year=THIS_YEAR), [item("s2")]
        return super().album(browse_id)


def rel(bid, title, year, kind="Album", explicit=False):
    return YTItem("album", bid, title, ["Band"], year=year, subtitle=kind, explicit=explicit)


def test_new_releases(monkeypatch):
    monkeypatch.setattr(custom_api, "YTMusicAdapter", ArtistYT)
    custom_api.youtube.reset()
    ArtistYT.pages = {"albums": [rel("MPREb_old", "Old One", "2001"), rel("MPREb_1", "Debut", THIS_YEAR)],
                      "singles": [rel("MPREb_s", "Fresh Single", THIS_YEAR, "Single")]}
    with make_client() as c:
        h = login(c)
        one = download(c, h, "s1")                    # Band's "Debut" is in the library
        play(one["track_id"], "s1", n=3)
        call = lambda fn, *a: custom_api.youtube.call("josh", fn, *a)  # noqa: E731
        assert releases.watched("josh") == [("Band", None)]
        assert releases.check("josh", call) == 1
        # first look: this year's releases count as new, older ones don't; Debut is already yours
        new = c.get("/api/discover/new", headers=h).json()
        assert [i["title"] for i in new["items"]] == ["Fresh Single"] and new["watching"] == 1
        assert releases.check("josh", call) == 0      # read today already
        assert artists.cached_about("Band")["description"] == "Band are a band."

        # turn on auto-download; a new album turns up on the next look and downloads
        assert c.put("/api/discover/new/settings", headers=h, json={"auto_download": True}).json()["auto_download"]
        ArtistYT.pages["albums"].insert(0, rel("MPREb_new", "Second", THIS_YEAR))
        queue = c.app.state.queue
        assert releases.check("josh", call, queue, force=True) == 1
        jobs = c.get("/api/downloads", headers=h).json()["downloads"]
        assert any(j["video_id"] == "s2" for j in jobs)
        titles = [i["title"] for i in c.get("/api/discover/new", headers=h).json()["items"]]
        assert titles[0] == "Second" and "Old One" not in titles


def test_follows_and_kids(monkeypatch):
    monkeypatch.setattr(custom_api, "YTMusicAdapter", ArtistYT)
    custom_api.youtube.reset()
    ArtistYT.pages = {"albums": [rel("MPREb_e", "Rude", THIS_YEAR, explicit=True),
                                 rel("MPREb_c", "Clean", THIS_YEAR)],
                      "singles": [rel("MPREb_u", "Unmarked", THIS_YEAR, "Single", explicit=None)]}
    with make_client() as c:
        h = login(c)
        r = c.put("/api/follows", headers=h, json={"name": "Band", "channel_id": "UCband"})
        assert r.json()["follows"] == [{"name": "Band", "channel_id": "UCband"}]
        releases.check("josh", lambda fn, *a: custom_api.youtube.call("josh", fn, *a))
        assert len(c.get("/api/discover/new", headers=h).json()["items"]) == 3

        desk = {"Authorization": f"Bearer {auth.enable_desktop_token()}"}
        pw = c.post("/api/desktop/people", headers=desk, json={"name": "emma"}).json()["password"]
        kid = login(c, "emma", pw)
        c.put("/api/follows", headers=kid, json={"name": "Band", "channel_id": "UCband"})
        new = c.get("/api/discover/new", headers=kid).json()
        assert [i["title"] for i in new["items"]] == ["Clean"] and new["auto_download"] is False
        assert c.put("/api/discover/new/settings", headers=kid, json={"auto_download": True}).status_code == 403

        c.put("/api/follows", headers=h, json={"name": "band", "follow": False})
        assert c.get("/api/follows", headers=h).json()["follows"] == []


class FakeMB:
    def artist(self, name):
        return ("mbid-band", [])

    def links(self, mbid):
        assert mbid == "mbid-band"
        return [{"type": "wikipedia", "url": "https://en.wikipedia.org/wiki/Band"},
                {"type": "social network", "url": "https://www.instagram.com/band"},
                {"type": "official homepage", "url": "https://band.example"},
                {"type": "purchase for download", "url": "https://shop.example"},
                {"type": "social network", "url": "http://insecure.example"}]


def test_artist_about_and_subsonic(monkeypatch):
    monkeypatch.setattr(custom_api, "YTMusicAdapter", ArtistYT)
    monkeypatch.setattr(artists, "musicbrainz", lambda: FakeMB())
    custom_api.youtube.reset()
    ArtistYT.pages = {}
    with make_client() as c:
        h = login(c)
        download(c, h, "s1")
        a = c.get("/api/artists/about", headers=h, params={"name": "Band"}).json()
        assert a["description"] == "Band are a band." and a["channel_id"] == "UCband" and not a["followed"]
        assert [l["label"] for l in a["links"]] == ["Website", "Wikipedia", "Instagram"]

        aid = library.library_for("josh").artists()[0]["id"]
        r = c.get("/rest/getArtistInfo2", params={"u": "josh", "p": "sesame", "v": "1.16.1", "c": "t",
                                                  "f": "json", "id": f"ar-{aid}"}).json()["subsonic-response"]
        assert r["status"] == "ok" and r["artistInfo2"]["biography"] == "Band are a band."
