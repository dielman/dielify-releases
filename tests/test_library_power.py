"""0.9.6 Library power: smart playlists, search by lyrics, the recap (year in review)."""

import json
import time
from datetime import date, datetime

import pytest

from dielify import library, lyrics, recap, settings, smart
from dielify.library import connect
from test_api import login, make_client, setup, wait_done  # noqa: F401


@pytest.fixture(autouse=True)
def pc_profile(setup):
    settings.set_value("active_profile", "josh")


def download(c, h, vid) -> dict:
    job = c.post("/api/downloads", headers=h, json={"type": "song", "id": vid}).json()["downloads"][0]
    return wait_done(c, h, job["id"])


def play(track_id, video_id, artist, when, n=1, profile="josh"):
    with connect() as conn:
        for i in range(n):
            conn.execute("INSERT INTO plays (profile, client_id, track_id, video_id, title, artist, album, counted, "
                         "played_s, started_at, device) VALUES (?,?,?,?,?,?,?,1,?,?,?)",
                         (profile, f"{video_id}-{when}-{i}-{time.monotonic_ns()}", track_id, video_id, f"T {video_id}",
                          artist, "Debut", 180, when + i * 60, "test"))


def test_smart_playlists():
    with make_client() as c:
        h = login(c)
        one, two, three = download(c, h, "s1"), download(c, h, "s2"), download(c, h, "s3")
        with connect() as conn:  # Band = rock, Someone = pop; song one played 5 times, last week
            conn.execute("INSERT INTO artist_tags (name_key, name, mbid, tags, fetched_at) VALUES "
                         "('band','Band','m1',?,?), ('someone','Someone','m2',?,?)",
                         (json.dumps([["rock", 5]]), time.time(), json.dumps([["pop", 5]]), time.time()))
            conn.execute("UPDATE library_items SET play_count = 5, last_played = ? WHERE track_id = ?",
                         (time.time() - 3 * 86400, one["track_id"]))
        body = {"name": "Rock I play", "rules": {"match": "all", "sort": "most_played", "limit": 10, "rules": [
            {"field": "genre", "op": "contains", "value": "rock"}]}}
        r = c.post("/api/playlists/smart", headers=h, json=body)
        assert r.status_code == 201, r.text
        p = r.json()
        assert p["playlist"]["kind"] == "smart" and p["playlist"]["read_only"]
        assert [e["item"]["id"] for e in p["entries"]] == ["s1", "s2"]          # most played first
        assert p["playlist"]["description"] == "Genre contains rock"
        pid = p["playlist"]["id"]

        # change the rules: played in the last week, or by Someone
        body["rules"] = {"match": "any", "sort": "title", "limit": 10, "rules": [
            {"field": "last_played", "op": "within", "value": 7},
            {"field": "artist", "op": "is", "value": "someone"}]}
        p = c.put(f"/api/playlists/{pid}/rules", headers=h, json=body).json()
        assert [e["item"]["title"] for e in p["entries"]] == ["Other Song", "Song One"]
        assert c.get(f"/api/playlists/{pid}/rules", headers=h).json()["rules"]["match"] == "any"

        # it keeps itself up to date: song two gets a thumbs up, a "thumbs up" list sees it
        c.put("/api/ratings", headers=h, json={"kind": "song", "name": "Song Two", "video_id": "s2", "value": 1})
        liked = c.post("/api/playlists/smart", headers=h, json={"name": "Liked", "rules": {"rules": [
            {"field": "rating", "op": "is", "value": "up"}]}}).json()
        assert [e["item"]["id"] for e in liked["entries"]] == ["s2"]
        c.put("/api/ratings", headers=h, json={"kind": "song", "name": "Song Three", "video_id": "s3", "value": 1})
        with connect() as conn:  # pretend the list is old
            conn.execute("UPDATE playlists SET synced_at = 0 WHERE id = ?", (liked["playlist"]["id"],))
        got = c.get(f"/api/playlists/{liked['playlist']['id']}", headers=h).json()
        assert {e["item"]["id"] for e in got["entries"]} == {"s2", "s3"}

        # not editable song by song; bad rules are refused with a reason
        assert c.post(f"/api/playlists/{pid}/songs", headers=h, json={"songs": [{"id": "s2", "title": "x"}]}).status_code >= 400
        bad = c.post("/api/playlists/smart", headers=h, json={"name": "x", "rules": {"rules": [
            {"field": "plays", "op": "contains", "value": "a"}]}})
        assert bad.status_code == 400 and "plays can't use contains" in bad.json()["detail"]
        assert len([p for p in c.get("/api/playlists", headers=h).json()["playlists"] if p["kind"] == "smart"]) == 2


def test_smart_rules_numbers_and_days():
    rules = smart.validate({"rules": [{"field": "plays", "op": "gt", "value": "3"},
                                      {"field": "added", "op": "not_within", "value": 30}]})
    assert rules["rules"][0]["value"] == 3.0 and rules["sort"] == "random" and rules["limit"] == 100
    assert smart.describe(rules) == "Plays more than 3 and Added not in the last 30 days"
    with pytest.raises(ValueError):
        smart.validate({"rules": []})


def test_search_by_lyrics():
    with make_client() as c:
        h = login(c)
        one, two = download(c, h, "s1"), download(c, h, "s2")
        lyrics.store("s1", {"lines": [(0, "Pressure pushing down on me"), (4000, "Pressing down on you")],
                            "text": "", "source": "test"})
        lyrics.store("s2", {"lines": None, "text": "I want to break free\nGod knows I want to break free",
                            "source": "test"})
        lyrics.store("zzzz", {"lines": None, "text": "pressure everywhere", "source": "test"})  # not in your library
        r = c.get("/api/library/lyrics-search", headers=h, params={"q": "pressure down"}).json()["results"]
        assert [(x["track"]["id"], x["line"]) for x in r] == [(one["track_id"], "Pressure pushing down on me")]
        r = c.get("/api/library/lyrics-search", headers=h, params={"q": '"break free"'}).json()["results"]
        assert [x["track"]["id"] for x in r] == [two["track_id"]]
        assert c.get("/api/library/lyrics-search", headers=h, params={"q": "nothing like it"}).json()["results"] == []

        # lyrics kept before 0.9.6 aren't indexed yet: the first search indexes them
        with connect() as conn:
            conn.execute("DELETE FROM lyrics_fts")
        r = c.get("/api/library/lyrics-search", headers=h, params={"q": "pushing"}).json()["results"]
        assert [x["track"]["id"] for x in r] == [one["track_id"]]


def test_recap():
    with make_client() as c:
        h = login(c)
        one, three = download(c, h, "s1"), download(c, h, "s3")
        oct_ = datetime(2025, 10, 5, 20).timestamp()
        play(one["track_id"], "s1", "Band", oct_)                       # Band first heard in October
        nov = [datetime(2025, 11, d, 8).timestamp() for d in (3, 4, 5, 9)]
        for d in nov:
            play(one["track_id"], "s1", "Band", d, n=2)
        play(three["track_id"], "s3", "Someone", nov[0] + 3600, n=3)    # Someone new in November
        lib = library.library_for("josh")
        r = c.get("/api/recap", headers=h, params={"period": "2025-11"}).json()
        assert r["title"] == "November 2025" and r["plays"] == 11 and r["songs"] == 2
        assert [s["title"] for s in r["top_songs"]] == ["Song One", "Other Song"]  # library titles
        assert r["days_listened"] == 4 and r["longest_streak_days"] == 3 and r["favourite_hour"] == 8
        assert r["new_artists"] == 1 and r["top_new_artists"][0]["name"] == "Someone"
        assert r["first_song"]["title"] == "T s1"
        year = c.get("/api/recap", headers=h, params={"period": "2025"}).json()
        assert year["title"] == "Your 2025" and year["plays"] == 12 and year["new_artists"] == 2
        assert c.get("/api/recap", headers=h, params={"period": "2025-13"}).status_code in (400, 422)

        # a year's recap shows from 1 December (or once the year is over); months as they happen
        assert [p["period"] for p in recap.periods(lib, date(2025, 11, 20))] == ["2025-11", "2025-10"]
        assert [p["period"] for p in recap.periods(lib, date(2025, 12, 1))][0] == "2025"
        assert [p["period"] for p in c.get("/api/recap/periods", headers=h).json()["periods"]][0] == "2025"


def test_cast_links_play_only_and_run_out(monkeypatch):
    from dielify import auth
    with make_client() as c:
        h = login(c)
        one = download(c, h, "s1")
        cast = c.post("/api/cast/token", headers=h).json()
        tok = cast["token"]
        assert tok.startswith("dielify_cast_") and cast["expires_at"] > time.time() + 11 * 3600
        assert c.get(f"/api/library/tracks/{one['track_id']}/stream", params={"token": tok}).status_code == 200
        # play only: nothing else accepts it
        assert c.get("/api/library/albums", headers={"Authorization": f"Bearer {tok}"}).status_code == 401
        assert c.get("/api/library/albums", params={"token": tok}).status_code == 401
        # it runs out
        with monkeypatch.context() as m:
            m.setattr(auth.time, "time", lambda: cast["expires_at"] + 1)
            assert c.get(f"/api/library/tracks/{one['track_id']}/stream", params={"token": tok}).status_code == 401
        # signing the phone out ends its cast links
        tok2 = c.post("/api/cast/token", headers=h).json()["token"]
        dev = c.get("/api/auth/devices", headers=h).json()
        did = (dev["devices"] if isinstance(dev, dict) else dev)[0]["id"]
        c.delete(f"/api/auth/device-token/{did}", headers=h)
        assert c.get(f"/api/library/tracks/{one['track_id']}/stream", params={"token": tok2}).status_code == 401
