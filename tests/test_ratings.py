"""Thumbs up / down / ban: storage, API, and their effect on discovery and mixes."""

import time

from dielify import mixes, ratings
from dielify.library import connect
from dielify.yt_adapter import YTItem
from test_api import FakeDownloader, login, make_client, setup  # noqa: F401  (setup: shared autouse fixture)


def test_keys_match_the_apps_rule():
    assert ratings.artist_key("  Florence  &  The Machine ") == "florence and the machine"
    assert ratings.artist_key("ＢＴＳ") == "bts"                 # NFKC: full-width letters
    assert ratings.artist_key("Beyoncé") == "beyoncé"            # accents kept (unlike tags.norm)
    assert ratings.song_key("abc") == "abc" and ratings.song_key(None, 7) == "tr-7"
    assert ratings.split_artists("Kendrick Lamar feat. SZA, Drake & Future") == ["Kendrick Lamar", "SZA", "Drake", "Future"]


def test_values_combine_ban_wins():
    ratings.set_rating("josh", "artist", ratings.artist_key("Drake"), "Drake", ratings.BAN)
    ratings.set_rating("josh", "artist", ratings.artist_key("SZA"), "SZA", ratings.UP)
    ratings.set_rating("josh", "song", "liked1", "Liked - SZA", ratings.UP)
    ratings.set_rating("josh", "song", "down1", "Meh - SZA", ratings.DOWN)
    r = ratings.Ratings("josh")
    assert r.value("x", "Kendrick Lamar, Drake") == ratings.BAN      # any banned artist
    assert r.value("liked1", "SZA") == ratings.UP
    assert r.value("down1", "SZA") == ratings.DOWN                  # the song's own rating beats the artist's
    assert r.value("other", ["SZA"]) == ratings.UP
    assert r.value("other", "Nobody") == 0
    items = [YTItem("song", "a", "A", ["Drake"]), YTItem("song", "down1", "Meh", ["SZA"]),
             YTItem("song", "b", "B", ["Someone"]), YTItem("album", "al", "Album", ["Drake"])]
    assert [i.id for i in r.arrange(items)] == ["b", "al", "down1"]   # ban out, thumbs-down to the back
    ratings.set_rating("josh", "artist", ratings.artist_key("Drake"), "Drake", 0)
    assert ratings.Ratings("josh").value("x", "Drake") == 0          # 0 clears it


def test_api_and_discovery_lists():
    with make_client(FakeDownloader()) as c:
        h = login(c)
        r = c.put("/api/ratings", headers=h, json={"kind": "artist", "name": "Banned Band", "value": -2})
        assert r.status_code == 200
        assert r.json()["ratings"][0] == {**r.json()["ratings"][0], "kind": "artist", "key": "banned band", "value": -2}
        r = c.put("/api/ratings", headers=h, json={"kind": "song", "name": "Song - X", "video_id": "vid1", "value": 1})
        assert {x["key"] for x in r.json()["ratings"]} == {"banned band", "vid1"}
        assert c.put("/api/ratings", headers=h, json={"kind": "song", "name": "?", "value": 1}).status_code == 400
        assert c.put("/api/ratings", headers=h, json={"kind": "song", "name": "x", "video_id": "v", "value": 5}).status_code == 422
        assert c.get("/api/ratings").status_code == 401
        # the fake YouTube's similar list (test_api.FakeYT) has artists we can ban
        before = c.get("/api/discover/similar/abc", headers=h).json()["items"]
        assert before
        if before:
            artist = before[0]["artists"][0]
            c.put("/api/ratings", headers=h, json={"kind": "artist", "name": artist, "value": -2})
            after = c.get("/api/discover/similar/abc", headers=h).json()["items"]
            assert all(artist not in i["artists"] for i in after)


def test_mixes_skip_banned_and_favour_liked():
    now = time.time()
    with connect() as conn:
        ar = conn.execute("INSERT INTO artists (profile, name) VALUES ('josh', 'Mixed')").lastrowid
        al = conn.execute("INSERT INTO albums (profile, artist_id, name, created_at) VALUES ('josh',?,'LP',?)",
                          (ar, now)).lastrowid
        for i, artist in enumerate(["Good", "Bad", "Liked"] * 20):
            conn.execute("INSERT INTO tracks (profile, relpath, album_id, artist_id, title, artist, suffix, size, mtime, "
                         "video_id, created_at, play_count) VALUES ('josh',?,?,?,?,?,'opus',1,?,?,?,0)",
                         (f"{i}.opus", al, ar, f"T{i}", artist, now, f"v{i}", now))
    ratings.set_rating("josh", "artist", "bad", "Bad", ratings.BAN)
    ratings.set_rating("josh", "artist", "liked", "Liked", ratings.UP)
    tracks = mixes._tracks("josh")
    assert len(tracks) == 40 and all(t["artist"] != "Bad" for t in tracks)
    picked = mixes._pick(tracks, "seed", size=15)
    liked = sum(t["artist"] == "Liked" for t in picked)
    assert liked > 15 - liked                                       # thumbs-up songs win most places
