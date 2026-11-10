"""0.9.11 security review: nobody reaches another person's songs, albums, playlists, downloads or
devices by guessing ids. Two households (josh; sam with their own music) and a kid in josh's."""

import pytest

from dielify import auth, kids, settings
from dielify.yt_adapter import YTItem
from test_api import login, make_client, setup, wait_done  # noqa: F401


def desk() -> dict:
    return {"Authorization": f"Bearer {auth.enable_desktop_token()}"}


@pytest.fixture
def world():
    settings.set_value("active_profile", "josh")
    kids.remember([YTItem("song", v, v, explicit=False) for v in ("s1", "s2", "s3")])
    with make_client() as c:
        josh = login(c)
        # sam: a second household with their own music folder
        assert c.post("/api/desktop/profiles", headers=desk(), json={"name": "sam"}).status_code == 200
        pw = c.post("/api/desktop/phone-users", headers=desk(), json={"name": "sam", "profile": "sam"}).json()["password"]
        settings.set_value("active_profile", "josh")
        sam = login(c, "sam", pw, device="sam's phone")
        # emma: a kid in josh's household
        kid_pw = c.post("/api/desktop/people", headers=desk(), json={"name": "emma"}).json()["password"]
        emma = login(c, "emma", kid_pw, device="emma's phone")

        job = c.post("/api/downloads", headers=josh, json={"type": "song", "id": "s1"}).json()["downloads"][0]
        done = wait_done(c, josh, job["id"])
        track = done["track_id"]
        t = c.get(f"/api/library/tracks/{track}", headers=josh).json()
        album = c.get("/api/library/albums", headers=josh).json()["albums"][0]["id"]
        artist = c.get("/api/library/artists", headers=josh).json()["artists"][0]["id"]
        pl = c.post("/api/playlists", headers=josh, json={"name": "Josh's private", "on_youtube": False}).json()["playlist"]["id"]
        devices = c.get("/api/auth/devices", headers=josh).json()["devices"]
        yield dict(c=c, josh=josh, sam=sam, emma=emma, track=track, album=album, artist=artist, playlist=pl,
                   job=job["id"], device=devices[0]["id"], t=t)


def test_another_household_gets_nothing(world):
    c, sam, w = world["c"], world["sam"], world
    tr, al, ar, pl, job, dev = w["track"], w["album"], w["artist"], w["playlist"], w["job"], w["device"]
    blocked = [
        ("get", f"/api/library/tracks/{tr}"), ("get", f"/api/library/tracks/{tr}/stream"),
        ("get", f"/api/library/tracks/{tr}/cover"), ("get", f"/api/library/albums/{al}"),
        ("get", f"/api/library/albums/{al}/cover"), ("get", f"/api/library/artists/{ar}"),
        ("get", f"/api/library/artists/{ar}/image"),
        ("delete", f"/api/library/tracks/{tr}"), ("delete", f"/api/library/albums/{al}"),
        ("put", f"/api/library/tracks/{tr}/star"), ("post", f"/api/library/tracks/{tr}/played"),
        ("get", f"/api/playlists/{pl}"), ("patch", f"/api/playlists/{pl}"), ("delete", f"/api/playlists/{pl}"),
        ("post", f"/api/playlists/{pl}/songs"), ("post", f"/api/playlists/{pl}/sync"),
        ("get", f"/api/playlists/{pl}/rules"), ("put", f"/api/playlists/{pl}/share"),
        ("get", f"/api/playlists/{pl}/cover"),
        ("get", f"/api/downloads/{job}"), ("delete", f"/api/downloads/{job}"), ("post", f"/api/downloads/{job}/next"),
        ("delete", f"/api/auth/device-token/{dev}"),
    ]
    bodies = {"patch": {"name": "x"}, "put": {"starred": True, "shared": True}, "post": {"songs": [{"type": "song", "id": "s9"}]}}
    leaks = []
    for method, path in blocked:
        r = getattr(c, method)(path, headers=sam, **({"json": bodies[method]} if method in bodies else {}))
        if r.status_code < 400:
            leaks.append(f"{method.upper()} {path} -> {r.status_code}")
    assert leaks == []
    # and nothing of josh's turns up in sam's lists
    assert c.get("/api/library/albums", headers=sam).json()["albums"] == []
    assert c.get("/api/library/search?q=s1", headers=sam).json()["tracks"] == []
    assert all(p["id"] != pl for p in c.get("/api/playlists", headers=sam).json()["playlists"])
    assert c.get(f"/api/library/household", headers=sam).json()["tracks"] == []
    # josh's song and playlist are still there
    assert c.get(f"/api/library/tracks/{tr}", headers=world["josh"]).status_code == 200
    assert c.get(f"/api/playlists/{pl}", headers=world["josh"]).status_code == 200
    assert len(c.get("/api/auth/devices", headers=world["josh"]).json()["devices"]) >= 1


def test_a_kid_cant_change_her_parents_things(world):
    c, emma, w = world["c"], world["emma"], world
    tr, al, pl, job, dev = w["track"], w["album"], w["playlist"], w["job"], w["device"]
    for method, path, body in [
        ("delete", f"/api/library/tracks/{tr}", None), ("delete", f"/api/library/albums/{al}", None),
        ("get", f"/api/playlists/{pl}", None), ("patch", f"/api/playlists/{pl}", {"name": "x"}),
        ("delete", f"/api/playlists/{pl}", None), ("delete", f"/api/downloads/{job}", None),
        ("post", f"/api/downloads/{job}/next", None), ("delete", f"/api/auth/device-token/{dev}", None),
        ("get", "/api/yt/my-playlists", None),
    ]:
        r = getattr(c, method)(path, headers=emma, **({"json": body} if body else {}))
        ok = r.status_code >= 400 or (path == "/api/yt/my-playlists" and r.json()["items"] == [])
        assert ok, f"{method.upper()} {path} -> {r.status_code}"
    assert c.get(f"/api/library/tracks/{tr}", headers=world["josh"]).status_code == 200


def test_a_kid_never_gets_her_parents_youtube_playlists(world):
    """Security review: a kids account asked for playlist "LM" and got the parent's Liked Music."""
    c, emma = world["c"], world["emma"]
    for pid in ("LM", "VLLM", "SE", "PLmine", "VLPLmine", "RDTMAK5uy_somebody"):
        assert c.get(f"/api/yt/playlist/{pid}", headers=emma).status_code == 403, pid
    assert c.get("/api/yt/playlist/PLpublic", headers=emma).status_code == 200      # public lists are fine
    assert c.get("/api/yt/playlist/LM", headers=world["josh"]).status_code == 200   # josh still gets his own


def test_the_pc_apps_key_only_works_on_this_pc():
    """Security review: the desktop window's key is only accepted from 127.0.0.1."""
    from fastapi.testclient import TestClient
    from dielify.server import create_app
    key = desk()
    with TestClient(create_app(), client=("192.168.1.60", 50000)) as lan:
        r = lan.get("/api/desktop/status", headers=key)
        assert r.status_code == 401
    with make_client() as here:
        assert here.get("/api/desktop/status", headers=key).status_code == 200


def test_subsonic_apps_stay_in_their_household(world):
    """Security review: Symfonium & co. (the Subsonic API) only see the signed-in person's library."""
    c, tr, al = world["c"], world["track"], world["album"]
    pw = c.post("/api/desktop/phone-users/sam/password", headers=desk()).json()["password"]
    base = {"u": "sam", "p": pw, "v": "1.16.1", "c": "test", "f": "json"}
    for method, extra in (("getSong", {"id": f"tr-{tr}"}), ("stream", {"id": f"tr-{tr}"}),
                          ("getAlbum", {"id": f"al-{al}"}), ("getCoverArt", {"id": f"al-{al}"}),
                          ("download", {"id": f"tr-{tr}"})):
        r = c.get(f"/rest/{method}", params={**base, **extra})
        body = r.json()["subsonic-response"] if r.headers["content-type"].startswith("application/json") else {"status": "ok"}
        assert body["status"] == "failed", f"{method} gave sam josh's song"
    found = c.get("/rest/search3", params={**base, "query": ""}).json()["subsonic-response"]["searchResult3"]
    assert not found.get("song") and not found.get("album")
