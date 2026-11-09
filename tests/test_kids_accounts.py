"""0.9.2: a second person. A kids account shares the parent's music folder and (behind the
scenes) YouTube sign-in, has its own library, and never sees the parent's YouTube."""

import pytest

from dielify import auth, credstore, library, settings
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
        assert c.get("/api/discover/home", headers=kid).json() == {"shelves": []}
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

        # her library starts empty; Josh's song is on the Household shelf
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
