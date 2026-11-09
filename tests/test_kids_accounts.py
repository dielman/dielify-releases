"""0.9.2: a second person. A kids account shares the parent's music folder and (behind the
scenes) YouTube sign-in, has its own library, and never sees the parent's YouTube."""

import pytest

from dielify import auth, credstore, kids, library, settings
from dielify.yt_adapter import YTItem
from test_api import FakeDownloader, login, make_client, setup, wait_done  # noqa: F401


@pytest.fixture(autouse=True)
def josh_is_the_pc_profile(setup):
    settings.set_value("active_profile", "josh")  # the PC's own profile: kids share its music


def desk(c) -> dict:
    return {"Authorization": f"Bearer {auth.enable_desktop_token()}"}


def add_kid(c, name="emma") -> dict:
    r = c.post("/api/desktop/people", headers=desk(c), json={"name": name})
    assert r.status_code == 200, r.text
    return login(c, name, r.json()["password"], device="emma's phone")


def test_add_a_kid_and_what_she_sees(monkeypatch):
    used = []
    real_load = credstore.load
    monkeypatch.setattr(credstore, "load", lambda p, store="credentials": (
        used.append(p) if store == "credentials" else None, real_load(p, store))[1])  # YouTube sign-ins only
    with make_client() as c:
        h = login(c)
        song = wait_done(c, h, c.post("/api/downloads", headers=h, json={"type": "song", "id": "s1"}).json()["downloads"][0]["id"])
        kid = add_kid(c)
        assert c.post("/api/desktop/people", headers=desk(c), json={"name": "Emma"}).status_code == 400  # taken
        assert c.post("/api/desktop/people", headers=h, json={"name": "zoe"}).status_code == 403          # PC only

        me = c.get("/api/me", headers=kid).json()
        assert me["role"] == "child" and me["household"] == ["josh", "emma"]
        people = c.get("/api/desktop/status", headers=desk(c)).json()["people"]
        assert [(p["name"], p["role"], p["tracks"], p["logins"]) for p in people] == [
            ("josh", "parent", 1, ["josh"]), ("emma", "child", 0, ["emma"])]

        # nothing from Josh's YouTube account
        # Kids discovery, not Josh's feed. It never waits on explicit checks: Josh's song isn't
        # checked yet, so it's left out and checked in the background, then shows
        assert c.get("/api/discover/home", headers=kid).json()["shelves"] == []
        from dielify import custom_api, kids_home
        custom_api.youtube._quiet_since = 0.0      # nobody busy: the background check may go
        assert c.app.state.kids_check.run_once() == 1
        kids_home.forget()
        shelves = c.get("/api/discover/home", headers=kid).json()["shelves"]
        assert [sh["title"] for sh in shelves] == ["On the PC: add to your library"]
        assert c.get("/api/discover/charts", headers=kid).json()["playlists"] == []
        assert c.get("/api/yt/my-playlists", headers=kid).json() == {"items": []}
        assert c.post("/api/playlists/import", headers=kid, json={"yt_id": "PLmine"}).status_code == 403
        made = c.post("/api/playlists", headers=kid, json={"name": "Mine", "on_youtube": True}).json()
        assert made["playlist"]["yt_id"] is None                      # her playlists stay in Dielify
        assert c.put("/api/settings", headers=kid, json={"quality": "standard"}).status_code == 403
        assert c.get("/api/discover/home", headers=h).json()["shelves"]  # Josh still has his

        # but she can search YouTube, using Josh's sign-in behind the scenes
        used.clear()
        from dielify import custom_api
        custom_api.youtube.reset()
        assert c.get("/api/yt/search?q=other", headers=kid).json()["items"]
        assert used == ["josh"]

        # her library starts empty; Josh's song is on the Household shelf (once checked)
        kids.remember([YTItem("song", "s1", "Song One", explicit=False)])
        assert c.get("/api/library/albums", headers=kid).json()["albums"] == []
        shelf = c.get("/api/library/household", headers=kid).json()["tracks"]
        assert [t["id"] for t in shelf] == [song["track_id"]]
        assert c.get(shelf[0]["stream_url"], headers=kid).status_code == 200   # preview before adding
        assert c.get("/api/library/household", headers=h).json()["tracks"] == []
        assert c.post("/api/library/add", headers=kid, json={"track_ids": [song["track_id"]]}).json() == {"added": 1}
        assert c.get("/api/library/household", headers=kid).json()["tracks"] == []
        assert len(c.get("/api/library/albums", headers=kid).json()["albums"]) == 1


def test_her_downloads_land_in_the_shared_folder_and_only_her_library():
    fake = FakeDownloader()
    profiles = []
    with make_client(factory=lambda p: (profiles.append(p), fake)[1]) as c:
        h = login(c)
        kid = add_kid(c)
        job = c.post("/api/downloads", headers=kid, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        done = wait_done(c, kid, job["id"])
        assert done["status"] == "done"
        assert library.library_for("emma").track(done["track_id"])
        assert library.library_for("josh").track(done["track_id"]) is None
        assert library.library_for("emma").root == library.library_for("josh").root
        # Josh sees it on his Household shelf (and her downloads aren't on his list)
        assert [t["title"] for t in c.get("/api/library/household", headers=h).json()["tracks"]] == ["Other Song"]
        assert c.get("/api/downloads", headers=h).json()["downloads"] == []
    assert library.signin_of("emma") == "josh"


def test_removing_a_kid_keeps_the_music():
    with make_client() as c:
        h = login(c)
        kid = add_kid(c)
        job = c.post("/api/downloads", headers=kid, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        done = wait_done(c, kid, job["id"])
        path = library.library_for("emma").path_of(library.library_for("emma").track(done["track_id"]))
        assert c.delete("/api/desktop/people/josh", headers=desk(c)).status_code == 404   # parents can't be removed here
        assert c.delete("/api/desktop/people/emma", headers=desk(c)).status_code == 204
        assert c.get("/api/me", headers=kid).status_code == 401          # her phone is signed out
        assert auth.get_user("emma") is None and path.exists()
        assert [t["title"] for t in c.get("/api/library/household", headers=h).json()["tracks"]] == ["Other Song"]
        assert [p["name"] for p in c.get("/api/desktop/status", headers=desk(c)).json()["people"]] == ["josh"]


def controls(c, name="emma", **changes) -> dict:
    cur = c.get(f"/api/desktop/people/{name}/controls", headers=desk(c)).json()
    r = c.put(f"/api/desktop/people/{name}/controls", headers=desk(c), json={**cur, **changes})
    assert r.status_code == 200, r.text
    return r.json()


def test_controls_approvals_limit_quiet_hours_and_stats(monkeypatch):
    kids.remember([YTItem("song", v, v, explicit=False) for v in ("s1", "s2", "s3")])
    with make_client() as c:
        h = login(c)
        kid = add_kid(c)
        assert c.get("/api/desktop/people/emma/controls", headers=h).status_code == 403   # PC only
        assert controls(c)["explicit"] == "block"                                         # defaults

        # approval: her request waits until Josh says yes
        controls(c, downloads="approve")
        job = c.post("/api/downloads", headers=kid, json={"type": "song", "id": "s1"}).json()["downloads"][0]
        assert job["status"] == "approval"
        waiting = c.get("/api/desktop/approvals", headers=desk(c)).json()["approvals"]
        assert [(a["person"], a["video_id"]) for a in waiting] == [("emma", "s1")]
        assert c.get("/api/desktop/status", headers=desk(c)).json()["people"][1]["waiting"] == 1
        c.post("/api/desktop/approvals", headers=desk(c), json={"ids": [job["id"]], "allow": True})
        assert wait_done(c, kid, job["id"])["status"] == "done"

        # straight away again: downloads with no OK
        controls(c, downloads="auto")
        job = c.post("/api/downloads", headers=kid, json={"type": "song", "id": "s2"}).json()["downloads"][0]
        assert wait_done(c, kid, job["id"])["status"] == "done"

        # daily limit
        controls(c, daily_limit=2)
        job = c.post("/api/downloads", headers=kid, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        assert job["status"] == "failed" and "limit" in job["error"]

        # quiet hours: no music, and the phone is told why
        controls(c, quiet_hours=True, quiet_from="00:00", quiet_to="23:59")
        track = library.library_for("emma").track_by_video("s1")["id"]
        r = c.get(f"/api/library/tracks/{track}/stream", headers=kid)
        assert r.status_code == 403 and "Music is off until 23:59" in r.json()["detail"]
        assert c.get("/api/me", headers=kid).json()["notice"].startswith("Music is off")

        # her stats are private unless the controls say otherwise
        assert c.get("/api/desktop/people/emma/stats", headers=desk(c)).status_code == 403
        controls(c, parent_sees_stats=True, youtube_search=False, discovery_play=False)
        assert c.get("/api/desktop/people/emma/stats", headers=desk(c)).json()["period"] == "month"
        assert c.get("/api/yt/search?q=song", headers=kid).json()["items"] == []
        assert c.post("/api/discover/endless", headers=kid, json={"seeds": [], "exclude": [], "count": 5}).status_code == 403
