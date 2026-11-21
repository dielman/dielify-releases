"""YouTube Music artist pages (Josh, 21 Nov 2026: tapping an artist only searched their name)."""

from dielify import custom_api
from dielify.yt_adapter import YTItem
from test_api import FakeDownloader, FakeYT, item, login, make_client, setup  # noqa: F401


class ArtistYT(FakeYT):
    def artist_page(self, channel_id):
        return {"name": "Band", "description": "A band.", "thumbnail": "https://x/y.jpg",
                "songs": [item("s1"), item("s2")], "songs_playlist": "VLOLAKtop",
                "albums": [YTItem("album", "MPREb_1", "Debut", ["Band"])], "singles": [],
                "related": [YTItem("artist", "UCother", "Other Band")], "has_radio": True}


def test_artist_page(monkeypatch):
    monkeypatch.setattr(custom_api, "YTMusicAdapter", ArtistYT)
    custom_api.youtube.reset()
    with make_client(FakeDownloader()) as c:
        h = login(c)
        a = c.get("/api/yt/artist/UCband", headers=h).json()
        assert (a["name"], a["has_radio"], a["all_songs_playlist"]) == ("Band", True, "VLOLAKtop")
        assert [s["id"] for s in a["top_songs"]] == ["s1", "s2"]
        assert [x["id"] for x in a["albums"]] == ["MPREb_1"] and a["related"][0]["type"] == "artist"
        assert a["rating"] == 0 and a["followed"] is False and a["library_artist_id"] is None
        c.put("/api/ratings", headers=h, json={"kind": "artist", "name": "Band", "value": -2})
        assert c.get("/api/yt/artist/UCband", headers=h).json()["rating"] == -2
        assert c.get("/api/yt/artist/bad id!", headers=h).status_code in (400, 404)
