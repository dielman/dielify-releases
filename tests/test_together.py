"""0.9.8 Together: shared household playlists, Blend, Jam (with a kids account in them)."""

import time

import pytest

from dielify import auth, jam, kids, settings
from dielify.library import connect
from dielify.yt_adapter import YTItem
from test_api import login, make_client, setup, wait_done  # noqa: F401


@pytest.fixture(autouse=True)
def pc_profile(setup):
    settings.set_value("active_profile", "josh")
    jam.reset()


def download(c, h, vid) -> dict:
    job = c.post("/api/downloads", headers=h, json={"type": "song", "id": vid}).json()["downloads"][0]
    return wait_done(c, h, job["id"])


def kid(c, controls=None) -> dict:
    desk = {"Authorization": f"Bearer {auth.enable_desktop_token()}"}
    pw = c.post("/api/desktop/people", headers=desk, json={"name": "emma"}).json()["password"]
    if controls:
        cur = c.get("/api/desktop/people/emma/controls", headers=desk).json()
        assert c.put("/api/desktop/people/emma/controls", headers=desk, json={**cur, **controls}).status_code == 200
    return login(c, "emma", pw)


def marks():  # s3 is explicit, s1/s2 are clean
    kids.remember([YTItem("song", "s1", "Song One", ["Band"], explicit=False),
                   YTItem("song", "s2", "Song Two", ["Band"], explicit=False),
                   YTItem("song", "s3", "Other Song", ["Someone"], explicit=True)])


def song(vid, title):
    return {"type": "song", "id": vid, "title": title, "artists": ["Band"]}


def test_shared_household_playlist():
    with make_client() as c:
        h = login(c)
        e = kid(c)
        marks()
        pid = c.post("/api/playlists", headers=h, json={"name": "Car", "on_youtube": False}).json()["playlist"]["id"]
        c.post(f"/api/playlists/{pid}/songs", headers=h, json={"songs": [{"id": "s1", "title": "Song One"},
                                                                         {"id": "s3", "title": "Other Song"}]})
        assert c.get(f"/api/playlists/{pid}", headers=e).status_code == 404            # not shared yet
        r = c.put(f"/api/playlists/{pid}/share", headers=h, json={"shared": True}).json()
        assert r["playlist"]["shared"] and r["playlist"]["mine"]

        # she sees it (only the songs her controls allow) and adds one
        mine = [p for p in c.get("/api/playlists", headers=e).json()["playlists"] if p["id"] == pid][0]
        assert mine["owner"] == "josh" and not mine["mine"]
        got = c.get(f"/api/playlists/{pid}", headers=e).json()
        assert [x["item"]["id"] for x in got["entries"]] == ["s1"] and got["playlist"]["count"] == 1
        c.post(f"/api/playlists/{pid}/songs", headers=e, json={"songs": [{"id": "s2", "title": "Song Two"}]})
        full = c.get(f"/api/playlists/{pid}", headers=h).json()["entries"]
        assert [(x["item"]["id"], x["added_by"]) for x in full] == [("s1", "josh"), ("s3", "josh"), ("s2", "emma")]

        # only the owner renames, unshares or deletes
        assert c.patch(f"/api/playlists/{pid}", headers=e, json={"name": "Mine now"}).status_code == 400
        assert c.delete(f"/api/playlists/{pid}", headers=e).status_code == 400
        assert c.put(f"/api/playlists/{pid}/share", headers=e, json={"shared": False}).status_code == 400

        # synced / smart / mix playlists can't be shared
        with connect() as conn:
            conn.execute("UPDATE playlists SET yt_id = 'PLx' WHERE id = ?", (pid,))
        assert c.put(f"/api/playlists/{pid}/share", headers=h, json={"shared": True}).status_code == 400


def test_blend():
    with make_client() as c:
        h = login(c)
        one, two, three = download(c, h, "s1"), download(c, h, "s2"), download(c, h, "s3")
        e = kid(c)
        marks()
        c.post("/api/library/add", headers=e, json={"track_ids": [one["track_id"], three["track_id"]]})
        with connect() as conn:
            conn.execute("UPDATE library_items SET play_count = 5 WHERE profile = 'josh'")
            conn.execute("UPDATE library_items SET play_count = 3 WHERE profile = 'emma'")
        assert c.put("/api/blend", headers=e, json={"on": True}).status_code == 403   # parent hasn't allowed it
        assert c.put("/api/blend", headers=h, json={"on": True}).json()["waiting_for"] == ["emma"]

        desk = {"Authorization": f"Bearer {auth.enable_desktop_token()}"}
        cur = c.get("/api/desktop/people/emma/controls", headers=desk).json()
        c.put("/api/desktop/people/emma/controls", headers=desk, json={**cur, "blend": True})
        r = c.put("/api/blend", headers=e, json={"on": True}).json()
        assert r["partners"] == ["josh"] and len(r["playlists"]) == 1
        pl = c.get(f"/api/playlists/{r['playlists'][0]['id']}", headers=e).json()
        ids = [x["item"]["id"] for x in pl["entries"]]
        assert ids[0] == "s1"              # a song they both play comes first
        assert "s3" not in ids             # explicit: never in a Blend with her in it
        assert pl["playlist"]["kind"] == "blend" and pl["playlist"]["read_only"]
        assert c.get("/api/blend", headers=h).json()["playlists"][0]["name"] == "Blend: josh + emma"

        c.put("/api/blend", headers=h, json={"on": False})
        assert c.get("/api/blend", headers=e).json()["playlists"] == []


def test_jam_with_a_kid():
    with make_client() as c:
        h = login(c)
        e = kid(c)
        marks()
        assert c.get("/api/jam", headers=e).json() is None
        j = c.post("/api/jam", headers=h, json={"device": "Car phone", "songs": [song("s1", "Song One"),
                                                                                  song("s3", "Other Song")]}).json()
        assert j["you_host"] and [s["item"]["id"] for s in j["songs"]] == ["s1", "s3"]

        # she joins: the explicit song still to come is taken out
        r = c.post("/api/jam/join", headers=e).json()
        assert [s["item"]["id"] for s in r["songs"]] == ["s1"] and r["left_out"] and not r["you_host"]
        # now nobody can add it
        r = c.post("/api/jam/songs", headers=h, json={"songs": [song("s3", "Other Song"), song("s2", "Song Two")]}).json()
        assert [s["item"]["id"] for s in r["songs"]] == ["s1", "s2"] and "Other Song" in r["left_out"][0]
        r = c.post("/api/jam/songs", headers=e, json={"songs": [song("s1", "Song One")]}).json()
        assert [s["added_by"] for s in r["songs"]] == ["josh", "josh", "emma"]

        # only the host reports what's playing; only who added a song (or the host) takes it out
        assert c.post("/api/jam/playing", headers=e, json={"index": 1}).status_code == 403
        v = r["version"]
        r = c.post("/api/jam/playing", headers=h, json={"index": 1}).json()
        assert r["index"] == 1 and r["version"] > v
        theirs = r["songs"][2]["id"]
        assert c.delete(f"/api/jam/songs/{r['songs'][1]['id']}", headers=e).status_code == 403  # not hers
        assert c.delete(f"/api/jam/songs/{r['songs'][0]['id']}", headers=h).status_code == 400  # already played
        assert c.delete(f"/api/jam/songs/{theirs}", headers=h).status_code == 200

        # someone else can't start a second one; a child can't end it; the host can
        assert c.post("/api/jam", headers=e, json={"device": "x"}).status_code == 409
        assert c.delete("/api/jam", headers=e).status_code == 403
        assert c.delete("/api/jam", headers=h).status_code == 204
        assert c.get("/api/jam", headers=h).json() is None


def test_kid_without_jam_permission():
    with make_client() as c:
        h = login(c)
        e = kid(c, {"jam": False})
        c.post("/api/jam", headers=h, json={"device": "PC"})
        assert c.post("/api/jam/join", headers=e).status_code == 403
