"""Outside discovery: radio charts and ListenBrainz, matched on YouTube Music (no network)."""

import json
import time

from dielify import discovery, tags
from dielify.library import connect
from dielify.yt_adapter import YTItem
from test_api import FakeDownloader, login, make_client, setup  # noqa: F401  (setup: shared autouse fixture)


class Resp:
    def __init__(self, data):
        self.data, self.status_code = data, 200

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


def play(artist, title):
    return {"recording": {"title": title, "artists": [{"name": artist}]}}


class FakeWeb:
    """The ABC plays API (two pages), ListenBrainz trending and similar artists."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url == discovery.ABC_PLAYS:
            plays = ([play("Old Mervs", "Adeline")] * 5 + [play("Troye Sivan", "FF")] * 3
                     + [play("Dream Boat", "Real!")] * 4 + [play("Nobody", "Unknown song")] * 2)
            page = plays[params["offset"]:params["offset"] + 10]
            return Resp({"total": len(plays), "items": page})
        if url == discovery.LB_TRENDING:
            return Resp({"payload": {"recordings": [
                {"artist_name": "BTS", "track_name": f"Song {i}", "listen_count": 100 - i} for i in range(4)
            ] + [{"artist_name": "Other", "track_name": "Hit", "listen_count": 50}]}})
        if url == discovery.LB_SIMILAR:
            return Resp([{"name": "Arctic Monkeys", "score": 9}, {"name": "MGMT", "score": 8},
                         {"name": "The Strokes", "score": 7}])
        raise AssertionError(url)


class FakeYouTube:
    def __init__(self):
        self.searches = []

    def __call__(self, profile, fn, query, kind, limit):
        assert fn == "search_items" and kind == "song"
        self.searches.append(query)
        if "Nobody" in query:
            return []
        if query in ("MGMT", "The Strokes"):
            return [YTItem("song", f"{query[:3]}{i}", f"{query} hit {i}", [query]) for i in range(3)]
        artist, title = {"Old Mervs Adeline": ("Old Mervs", "Adeline"), "Troye Sivan FF": ("Troye Sivan", "FF"),
                         "Dream Boat Real!": ("Dream Boat", "Real!")}.get(query, (query.split(" ")[0], query))
        return [YTItem("song", "x" + str(abs(hash(query)) % 10**8), title, [artist])]


def add_library():
    now = time.time()
    with connect() as conn:
        for name, plays in (("Tame Impala", 50), ("Arctic Monkeys", 3)):
            ar = conn.execute("INSERT INTO artists (profile, name) VALUES ('josh', ?)", (name,)).lastrowid
            al = conn.execute("INSERT INTO albums (profile, artist_id, name, created_at) VALUES ('josh',?,?,?)",
                              (ar, name + " LP", now)).lastrowid
            conn.execute("INSERT INTO tracks (profile, relpath, album_id, artist_id, title, artist, suffix, size, "
                         "mtime, video_id, created_at, play_count) VALUES ('josh',?,?,?,?,?,'opus',1,?,?,?,?)",
                         (name + ".opus", al, ar, name + " song", name, now, "v" + name[:5], now, plays))
            conn.execute("INSERT INTO artist_tags (name_key, name, mbid, tags, fetched_at) VALUES (?,?,?,?,?)",
                         (tags.norm(name), name, "mbid-" + name, json.dumps([["rock", 1]]), now))
        conn.execute("INSERT OR IGNORE INTO library_items (profile, track_id, added_at, play_count) "
                     "SELECT profile, id, created_at, play_count FROM tracks")  # each song in its owner's library


def test_radio_chart_counts_a_week_of_plays():
    web = FakeWeb()
    chart = discovery.station_chart("triplej", web, size=3)
    assert chart == [("Old Mervs", "Adeline", 5), ("Dream Boat", "Real!", 4), ("Troye Sivan", "FF", 3)]
    offsets = [c[1]["offset"] for c in web.calls]
    assert offsets == [0, 10]                      # read every page of the week
    assert web.calls[0][1]["station"] == "triplej" and "from" in web.calls[0][1]


def test_trending_keeps_variety():
    assert [a for a, _, _ in discovery.lb_trending(FakeWeb())] == ["BTS", "BTS", "Other"]


def test_lists_are_built_and_matches_remembered():
    add_library()
    web, yt = FakeWeb(), FakeYouTube()
    saved = discovery.rebuild("josh", yt, web)
    lists = {l["key"]: l for l in discovery.lists("josh")}
    assert saved == len(lists) == 6   # 3 stations + trending + "because you like" x2
    assert "lb:like:arctic monkeys" in lists
    tj = lists["radio:triplej"]
    assert tj["title"] == "triple j: most played this week"
    assert [i.title for i in tj["items"]] == ["Adeline", "Real!", "FF"]   # "Nobody" had no match: left out
    like = lists["lb:like:tame impala"]
    assert like["title"] == "Because you like Tame Impala"
    assert {i.artists[0] for i in like["items"]} == {"MGMT", "The Strokes"}  # Arctic Monkeys: already yours
    assert len(like["items"]) == 4                                           # 2 songs each

    # tomorrow: same songs are not searched for again
    before = len(yt.searches)
    discovery.rebuild("josh", yt, web)
    assert len(yt.searches) == before


def test_api_serves_the_lists():
    add_library()
    discovery.rebuild("josh", FakeYouTube(), FakeWeb())
    with make_client(FakeDownloader()) as c:
        h = login(c)
        shelves = c.get("/api/discover/outside", headers=h).json()["shelves"]
        assert shelves[0]["title"] == "triple j: most played this week"
        assert shelves[0]["items"][0]["title"] == "Adeline" and shelves[0]["items"][0]["type"] == "song"
        assert c.post("/api/discover/outside/refresh", headers=h).status_code == 202
        assert c.get("/api/discover/outside").status_code == 401
