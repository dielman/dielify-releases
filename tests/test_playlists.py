"""Playlists synced two ways with a fake YouTube Music that remembers its playlists."""

import pytest

from dielify import custom_api
from dielify.yt_adapter import YouTubeError, YTItem
from test_api import FakeDownloader, FakeYT, item, login, make_client, setup, wait_done  # noqa: F401


class FakeYouTubePlaylists(FakeYT):
    remote: dict = {}          # yt_id -> {"title": str, "entries": [(video_id, set_video_id)]}
    offline = False
    calls: list = []
    _n = 0

    @classmethod
    def reset(cls):
        cls.remote, cls.offline, cls.calls, cls._n = {}, False, [], 0

    def _check(self, name):
        FakeYouTubePlaylists.calls.append(name)
        if FakeYouTubePlaylists.offline:
            raise YouTubeError("YouTube can not be reached")

    @classmethod
    def _set_id(cls):
        cls._n += 1
        return f"SET{cls._n}"

    def playlist_entries(self, yt_id, limit=5000):
        self._check("read")
        pl = self.remote[yt_id]
        return YTItem("playlist", yt_id, pl["title"]), [(item(v), s) for v, s in pl["entries"]]

    def create_playlist(self, title, description=""):
        self._check("create")
        yt_id = f"PLnew{len(self.remote)}"
        self.remote[yt_id] = {"title": title, "entries": []}
        return yt_id

    def add_to_playlist(self, yt_id, video_ids):
        self._check("add")
        self.remote[yt_id]["entries"] += [(v, self._set_id()) for v in video_ids]

    def remove_from_playlist(self, yt_id, entries):
        self._check("remove")
        gone = {s for _, s in entries}
        self.remote[yt_id]["entries"] = [e for e in self.remote[yt_id]["entries"] if e[1] not in gone]

    def rename_playlist(self, yt_id, title):
        self._check("rename")
        self.remote[yt_id]["title"] = title

    def delete_playlist(self, yt_id):
        self._check("delete")
        del self.remote[yt_id]


@pytest.fixture
def yt(monkeypatch):
    FakeYouTubePlaylists.reset()
    monkeypatch.setattr(custom_api, "YTMusicAdapter", FakeYouTubePlaylists)
    custom_api.youtube.reset()
    return FakeYouTubePlaylists


def song(vid):
    i = item(vid)
    return {"id": vid, "title": i.title, "artists": i.artists, "album": i.album}


def videos(detail):
    return [e["item"]["id"] for e in detail["entries"]]


def remote_videos(yt, yt_id):
    return [v for v, _ in yt.remote[yt_id]["entries"]]


def test_two_way_sync(yt):
    yt.remote["PLmine"] = {"title": "Road trip", "entries": [("s1", "A1"), ("s2", "A2")]}
    with make_client(FakeDownloader()) as c:
        h = login(c)
        d = c.post("/api/playlists/import", headers=h, json={"yt_id": "PLmine"}).json()
        pid = d["playlist"]["id"]
        assert (d["playlist"]["name"], videos(d)) == ("Road trip", ["s1", "s2"])
        jobs = c.get("/api/downloads", headers=h).json()["downloads"]
        assert {j["video_id"] for j in jobs} == {"s1", "s2"}          # new songs download
        for j in jobs:
            wait_done(c, h, j["id"])

        # changed in the YouTube Music app -> shows up here on the next sync
        yt.remote["PLmine"]["entries"].append(("s3", "A3"))
        yt.remote["PLmine"]["title"] = "Road trip 2026"
        d = c.post(f"/api/playlists/{pid}/sync", headers=h).json()
        assert (d["playlist"]["name"], videos(d)) == ("Road trip 2026", ["s1", "s2", "s3"])
        assert [e["item"]["library_track_id"] is not None for e in d["entries"]] == [True, True, False]
        assert any(j["video_id"] == "s3" for j in c.get("/api/downloads", headers=h).json()["downloads"])

        # removing from a synced playlist must be confirmed for YouTube too
        s2 = d["entries"][1]["entry_id"]
        assert c.delete(f"/api/playlists/{pid}/entries/{s2}", headers=h).status_code == 400
        d = c.delete(f"/api/playlists/{pid}/entries/{s2}", headers=h, params={"on_youtube": True}).json()
        assert videos(d) == ["s1", "s3"] and remote_videos(yt, "PLmine") == ["s1", "s3"]

        # rename and add in Dielify -> on YouTube
        c.patch(f"/api/playlists/{pid}", headers=h, json={"name": "Drive"})
        d = c.post(f"/api/playlists/{pid}/songs", headers=h, json={"songs": [song("s2")]}).json()
        assert yt.remote["PLmine"]["title"] == "Drive"
        assert remote_videos(yt, "PLmine") == ["s1", "s3", "s2"] and d["playlist"]["pending"] == 0

        # the just-added song can be removed again (its YouTube entry id is looked up)
        last = d["entries"][-1]["entry_id"]
        c.delete(f"/api/playlists/{pid}/entries/{last}", headers=h, params={"on_youtube": True})
        assert remote_videos(yt, "PLmine") == ["s1", "s3"]


def test_edits_wait_while_youtube_is_unreachable(yt):
    yt.remote["PLmine"] = {"title": "Mix", "entries": [("s1", "A1")]}
    with make_client(FakeDownloader()) as c:
        h = login(c)
        pid = c.post("/api/playlists/import", headers=h, json={"yt_id": "PLmine"}).json()["playlist"]["id"]
        yt.offline = True
        d = c.post(f"/api/playlists/{pid}/songs", headers=h, json={"songs": [song("s2")]}).json()
        assert videos(d) == ["s1", "s2"] and d["playlist"]["pending"] == 1      # shown here, waiting
        assert d["playlist"]["sync_error"] and remote_videos(yt, "PLmine") == ["s1"]
        d = c.post(f"/api/playlists/{pid}/sync", headers=h).json()
        assert videos(d) == ["s1", "s2"]                                         # a failed sync keeps it
        yt.offline = False
        d = c.post(f"/api/playlists/{pid}/sync", headers=h).json()
        assert d["playlist"]["pending"] == 0 and d["playlist"]["sync_error"] is None
        assert remote_videos(yt, "PLmine") == ["s1", "s2"] and videos(d) == ["s1", "s2"]


def test_create_delete_and_local_only(yt):
    with make_client(FakeDownloader()) as c:
        h = login(c)
        d = c.post("/api/playlists", headers=h, json={"name": "New one"}).json()
        yt_id = d["playlist"]["yt_id"]
        assert yt.remote[yt_id]["title"] == "New one"
        local = c.post("/api/playlists", headers=h, json={"name": "Just here", "on_youtube": False}).json()
        assert local["playlist"]["yt_id"] is None
        lid = local["playlist"]["id"]
        d2 = c.post(f"/api/playlists/{lid}/songs", headers=h, json={"songs": [song("s1"), song("s3")]}).json()
        e = d2["entries"][0]["entry_id"]
        assert videos(c.delete(f"/api/playlists/{lid}/entries/{e}", headers=h).json()) == ["s3"]
        assert "add" not in yt.calls                                    # local-only: YouTube untouched

        names = [p["name"] for p in c.get("/api/playlists", headers=h).json()["playlists"]]
        assert names == ["Just here", "New one"]
        c.delete(f"/api/playlists/{d['playlist']['id']}", headers=h)    # only here: YouTube keeps it
        assert yt_id in yt.remote
        again = c.post("/api/playlists/import", headers=h, json={"yt_id": yt_id}).json()["playlist"]["id"]
        assert c.delete(f"/api/playlists/{again}", headers=h, params={"on_youtube": True}).status_code == 204
        assert yt_id not in yt.remote


def test_liked_music_is_one_way_and_subsonic_sees_playlists(yt):
    yt.remote["LM"] = {"title": "Liked Music", "entries": [("s1", "L1")]}
    with make_client(FakeDownloader()) as c:
        h = login(c)
        d = c.post("/api/playlists/import", headers=h, json={"yt_id": "LM"}).json()
        pid = d["playlist"]["id"]
        assert d["playlist"]["read_only"] is True
        assert c.post(f"/api/playlists/{pid}/songs", headers=h, json={"songs": [song("s2")]}).status_code == 400
        for j in c.get("/api/downloads", headers=h).json()["downloads"]:
            wait_done(c, h, j["id"])
        r = c.get("/rest/getPlaylists", params={"u": "josh", "p": "sesame", "f": "json"}).json()["subsonic-response"]
        lists = r["playlists"]["playlist"]
        assert [(p["name"], p["songCount"]) for p in lists] == [("Liked Music", 1)]
        r = c.get("/rest/getPlaylist", params={"u": "josh", "p": "sesame", "f": "json", "id": lists[0]["id"]}
                  ).json()["subsonic-response"]
        assert [s["title"] for s in r["playlist"]["entry"]] == ["Song One"]
