"""Genre / decade / vibe mixes and MusicBrainz genre lookups (no network)."""

import json
import time

from dielify import mixes, playlists, tags
from dielify.library import connect
from dielify.yt_adapter import YTItem


def add_library(profile="josh"):
    """40 indie rock songs (2010s), 32 hip hop songs (2000s; 20 gangsta rap), by four artists."""
    now = time.time()
    with connect() as conn:
        n = 0
        for artist, genre_tags, count, year in [("Arctic Monkeys", [["indie rock", 19], ["british", 5]], 20, 2013),
                                                 ("Tame Impala", [["indie rock", 3], ["psychedelic rock", 14]], 20, 2015),
                                                 ("Ye", [["hip hop", 32], ["pop rap", 15]], 12, 2007),
                                                 ("The Game", [["hip hop", 6], ["gangsta rap", 3]], 20, 2005)]:
            ar = conn.execute("INSERT INTO artists (profile, name) VALUES (?,?)", (profile, artist)).lastrowid
            al = conn.execute("INSERT INTO albums (profile, artist_id, name, created_at) VALUES (?,?,?,?)",
                              (profile, ar, f"{artist} album", now)).lastrowid
            conn.execute("INSERT INTO artist_tags (name_key, name, mbid, tags, fetched_at) VALUES (?,?,?,?,?)",
                         (tags.norm(artist), artist, "mbid", json.dumps(genre_tags), now))
            for i in range(count):
                n += 1
                conn.execute(
                    "INSERT INTO tracks (profile, relpath, album_id, artist_id, title, artist, year, track_no, "
                    "duration_s, suffix, size, mtime, video_id, created_at, play_count) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (profile, f"{artist}/{i}.opus", al, ar, f"{artist} song {i}", artist, year, i + 1, 200,
                     "opus", 1000, now, f"vid{n:08d}", now, i % 4))


def test_mixes_are_built_from_genres_decades_and_vibes():
    add_library()
    built = mixes.rebuild("josh", similar=lambda vid: [YTItem("song", f"new{vid[-4:]}{k}", f"New {k}") for k in range(8)])
    lists = {p["mix_key"]: p for p in playlists.all_playlists("josh") if p["kind"] == "mix"}
    assert built == len(lists)
    assert {"genre:indie rock", "genre:hip hop", "decade:2010", "decade:2000", "vibe:high energy"} <= set(lists)
    assert "genre:psychedelic rock" not in lists   # same songs as indie rock: not repeated
    assert "genre:british" not in lists             # nationality, not a genre
    indie = playlists.get("josh", lists["genre:indie rock"]["id"])
    assert indie["read_only"] and indie["name"] == "Indie Rock mix"
    assert len(indie["items"]) == 40 + mixes.NEW_FINDS            # all 40 indie songs + new finds
    assert sum(1 for i in indie["items"] if i["video_id"].startswith("new")) == mixes.NEW_FINDS
    assert "10 new finds" in indie["description"]
    assert len(playlists.get("josh", lists["decade:2010"]["id"])["items"]) == 40

    # a rebuild keeps ids (open screens keep working) and mixes can't be edited
    again = mixes.rebuild("josh")
    lists2 = {p["mix_key"]: p["id"] for p in playlists.all_playlists("josh") if p["kind"] == "mix"}
    assert again == built and lists2 == {k: v["id"] for k, v in lists.items()}
    eng = playlists.Playlists(call=lambda *a: None)
    try:
        eng.add("josh", lists2["genre:hip hop"], [YTItem("song", "x", "x")])
        raise AssertionError("mixes must be read-only")
    except ValueError as e:
        assert "rebuilt every week" in str(e)


class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, answers):
        self.answers, self.headers, self.calls = list(answers), {}, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return self.answers.pop(0)


def test_musicbrainz_needs_an_exact_match_and_retries_when_busy(monkeypatch):
    monkeypatch.setattr(tags, "MIN_GAP_S", 0)
    monkeypatch.setattr(tags.time, "sleep", lambda s: None)
    answers = [FakeResponse(503), FakeResponse(200, {"artists": [
        {"id": "tribute", "name": "Kanye West Tribute Band", "tags": []},
        {"id": "ye", "name": "Ye", "aliases": [{"name": "Kanye West"}],
         "tags": [{"name": "hip hop", "count": 32}, {"name": "producer", "count": 3}]}]})]
    mb = tags.MusicBrainz(FakeSession(answers))
    assert mb.artist("Kanye West") == ("ye", [("hip hop", 32), ("producer", 3)])
    assert mb.http.headers["User-Agent"].startswith("Dielify/")
    mb.http.answers = [FakeResponse(200, {"artists": [{"id": "x", "name": "Somebody Else"}]})]
    assert mb.artist("Nobody") == (None, [])
    assert tags.genre_tags([("producer", 3), ("hip hop", 32), ("1990s", 9), ("Hip-Hop", 1)]) == ["hip hop"]
    assert tags.split_artists("Justice, Tame Impala & Djo feat. Someone") == ["Justice", "Tame Impala", "Djo", "Someone"]


def test_genre_lookup_does_the_whole_library_in_one_go(monkeypatch):
    """0.8.2 stopped after 300 artists and waited 30 minutes for the next 300."""
    import threading
    add_library()
    with connect() as conn:
        conn.execute("DELETE FROM artist_tags")
        for i in range(450):
            conn.execute("INSERT INTO artists (profile, name) VALUES (?, ?)", ("josh", f"Extra artist {i}"))

    class CountingMB:
        calls = 0

        def artist(self, name):
            CountingMB.calls += 1
            return ("id", [("rock", 1)])

    done = tags.tag_some(CountingMB(), threading.Event())
    assert done == CountingMB.calls == len(tags.library_artists()) > 450
    st = tags.status()
    assert st["looked_up"] == st["artists"]
