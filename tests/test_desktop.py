"""Phase 4: desktop key, PC-only endpoints, offline mode, library browsing, the UI page."""

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAdapter, needs_ffmpeg
from test_api import FakeDownloader, FakeYT, item, login, wait_done
from dielify import auth, custom_api, desktop_api, downloads, settings
from dielify.downloader import download_track
from dielify.downloads import DownloadQueue
from dielify.server import UI_CSP, create_app
from dielify.yt_adapter import Offline, YTMusicAdapter

pytestmark = needs_ffmpeg


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path, sample_info):
    monkeypatch.setenv("DIELIFY_INSECURE_DEV_STORE", "1")
    monkeypatch.setattr(custom_api, "YTMusicAdapter", FakeYT)
    monkeypatch.setattr(downloads, "SIGNIN_WAIT_S", 0.2)
    run_key = {}
    monkeypatch.setattr(desktop_api.winint, "start_with_windows", lambda: run_key.get("on", False))
    monkeypatch.setattr(desktop_api.winint, "set_start_with_windows", lambda on: run_key.__setitem__("on", on))
    custom_api.youtube.reset()
    custom_api.lockout = auth.Lockout()
    settings.set_value("library_root", str(tmp_path / "Music"))
    settings.set_value("active_profile", "josh")
    download_track(FakeAdapter(sample_info), "abc123", settings.load(), profile="josh")
    auth.add_user("josh", "josh", password="sesame")


@pytest.fixture
def client():
    queue = DownloadQueue(adapter_factory=lambda profile: FakeDownloader())
    with TestClient(create_app(queue), client=("127.0.0.1", 50000)) as c:
        c.desk = {"Authorization": f"Bearer {auth.enable_desktop_token()}"}
        yield c


def test_desktop_key_and_pc_only_endpoints(client):
    st = client.get("/api/desktop/status", headers=client.desk).json()
    assert st["active_profile"] == "josh" and st["profiles"][0]["tracks"] == 1
    phone = login(client)
    assert client.get("/api/desktop/status", headers=phone).status_code == 403   # phones can't
    assert client.get("/api/desktop/status").status_code == 401
    assert client.get("/api/desktop/status", headers={"Authorization": "Bearer dielify_desktop_guess"}).status_code == 401
    # the desktop key also works for the normal API, as the active profile
    assert client.get("/api/library/artists", headers=client.desk).json()["artists"][0]["name"] == "Queen"


def test_library_browsing_and_media_token(client):
    h = client.desk
    artist = client.get("/api/library/artists", headers=h).json()["artists"][0]
    detail = client.get(f"/api/library/artists/{artist['id']}", headers=h).json()
    album = client.get(f"/api/library/albums/{detail['albums'][0]['id']}", headers=h).json()
    t = album["tracks"][0]
    assert album["album"]["name"] == "Hot Space" and t["title"] == "Under: Pressure?"
    key = h["Authorization"].split()[1]
    assert client.get(t["stream_url"], params={"token": key}).status_code == 200          # <audio src>
    assert client.get(album["album"]["cover_url"], params={"token": key, "size": 64}).headers["content-type"] == "image/jpeg"
    assert client.get(t["stream_url"], params={"token": "nope"}).status_code == 401
    assert client.get("/api/library/search", params={"q": "pressure"}, headers=h).json()["tracks"][0]["id"] == t["id"]
    assert client.put(f"/api/library/tracks/{t['id']}/star", json={"starred": True}, headers=h).json()["starred"]
    assert client.post(f"/api/library/tracks/{t['id']}/played", headers=h).status_code == 204
    assert client.get("/api/library/albums", params={"sort": "recent"}, headers=h).json()["albums"][0]["play_count"] == 1


def test_settings_profiles_and_start_with_windows(client, tmp_path):
    h = client.desk
    new_root = tmp_path / "Elsewhere"
    st = client.put("/api/desktop/settings", headers=h,
                    json={"library_root": str(new_root), "quality": "standard", "start_with_windows": True}).json()
    assert st["library_root"] == str(new_root.resolve()) and st["quality"] == "standard"
    assert st["start_with_windows"] is True and new_root.exists()
    assert client.put("/api/desktop/settings", headers=h, json={"library_root": "relative\\path"}).status_code == 400
    st = client.post("/api/desktop/profiles", headers=h, json={"name": "emma"}).json()
    assert st["active_profile"] == "emma" and "emma" in [p["name"] for p in st["profiles"]]
    assert client.post("/api/desktop/profiles", headers=h, json={"name": "../x"}).status_code == 400


def test_phone_logins_from_desktop(client):
    h = client.desk
    new = client.post("/api/desktop/phone-users", headers=h, json={"name": "emma"}).json()
    assert new["profile"] == "josh" and len(new["password"]) == 20
    assert client.post("/api/auth/login", json={"username": "emma", "password": new["password"]}).status_code == 200
    again = client.post("/api/desktop/phone-users/emma/password", headers=h).json()
    assert again["password"] != new["password"]
    st = client.get("/api/desktop/status", headers=h).json()
    emma = next(u for u in st["phone_users"] if u["name"] == "emma")
    assert len(emma["devices"]) == 1
    assert client.delete(f"/api/desktop/devices/{emma['devices'][0]['id']}", headers=h).status_code == 204
    assert client.delete("/api/desktop/phone-users/emma", headers=h).status_code == 204


def test_offline_mode_blocks_youtube_but_library_plays(client, monkeypatch):
    h = client.desk
    client.put("/api/desktop/settings", headers=h, json={"offline": True})
    # the real adapter refuses before any network call
    with pytest.raises(Offline):
        YTMusicAdapter(request_delay_s=0).search("anything")
    monkeypatch.setattr(custom_api, "YTMusicAdapter", YTMusicAdapter)
    custom_api.youtube.reset()
    r = client.get("/api/discover/home", headers=h)
    assert r.status_code == 503 and "Offline" in r.json()["detail"]
    job = client.post("/api/downloads", headers=h, json={"type": "song", "id": "s3"}).json()["downloads"][0]
    import time
    time.sleep(1)
    job = client.get(f"/api/downloads/{job['id']}", headers=h).json()
    assert job["status"] == "queued" and "offline" in job["error"].lower()
    t = client.get("/api/library/search", params={"q": ""}, headers=h).json()["tracks"][0]
    assert client.get(t["stream_url"], headers=h).status_code == 200  # library still plays
    client.put("/api/desktop/settings", headers=h, json={"offline": False})
    assert wait_done(client, h, job["id"])["status"] == "done"


def test_ui_is_served_with_strict_policy(client):
    r = client.get("/ui/")
    assert r.status_code == 200 and "<title>Dielify</title>" in r.text
    assert r.headers["content-security-policy"] == UI_CSP and "script-src 'self'" in UI_CSP
    assert client.get("/ui/app.js").status_code == 200


def test_request_crash_is_logged(client, caplog, monkeypatch):
    """Regression: in the installed app, a crash inside a request left no trace anywhere."""
    def boom():
        raise RuntimeError("kaboom")
    monkeypatch.setattr(desktop_api, "_status", boom)
    caplog.set_level("ERROR", logger="dielify.server")
    with pytest.raises(RuntimeError):
        client.get("/api/desktop/status", headers=client.desk)
    assert "/api/desktop/status failed" in caplog.text and "kaboom" in caplog.text


def test_unexpected_error_is_explained_to_the_desktop_only(monkeypatch):
    queue = DownloadQueue(adapter_factory=lambda profile: FakeDownloader())
    app = create_app(queue)
    monkeypatch.setattr(desktop_api, "_status", lambda: (_ for _ in ()).throw(RuntimeError("disk on fire")))
    with TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000)) as c:
        desk = {"Authorization": f"Bearer {auth.enable_desktop_token()}"}
        r = c.get("/api/desktop/status", headers=desk)
        assert r.status_code == 500
        assert "RuntimeError: disk on fire" in r.json()["detail"] and "server.log" in r.json()["detail"]
        monkeypatch.setattr(custom_api.Session, "__init__", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret")))
        phone = c.get("/api/settings", headers={"Authorization": "Bearer dielify_x"})
        assert "secret" not in phone.text


def test_unreadable_login_shows_signed_out_not_500(client, monkeypatch):
    from dielify import credstore

    def broken(*a, **k):
        raise credstore.CredentialError("DPAPI decrypt failed")
    monkeypatch.setattr(credstore, "load", broken)
    st = client.get("/api/desktop/status", headers=client.desk)
    assert st.status_code == 200 and st.json()["profiles"][0]["youtube_signed_in"] is False
    assert st.json()["data_folder"] and st.json()["log_file"].endswith("server.log")


def test_server_starts_without_a_console(monkeypatch):
    """Regression: the installed app has no console; uvicorn's logging setup crashed on it."""
    import sys

    from dielify import server
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    server._config(DownloadQueue(adapter_factory=lambda p: FakeDownloader()))


def test_late_address_is_picked_up(monkeypatch):
    """Tailscale often connects after Dielify starts: the watcher must start listening
    on the new address, without starting a second download queue."""
    import socket as socketlib

    import httpx

    from dielify import server
    with socketlib.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    s = settings.Settings(server_port=port)
    starts = []

    class CountingQueue(DownloadQueue):
        def start(self):
            starts.append(1)
            super().start()

    addrs = ["127.0.0.1"]
    monkeypatch.setattr(server, "bind_addresses", lambda st: list(addrs))
    monkeypatch.setattr(server, "_config", lambda queue=None: server.uvicorn.Config(
        create_app(CountingQueue(adapter_factory=lambda p: FakeDownloader())), log_config=None))
    srv = server.start_background(s, ["127.0.0.1"])
    try:
        assert srv.watcher.check() == []                  # nothing new yet
        addrs.append("127.0.0.2")                          # "Tailscale connected"
        assert srv.watcher.check() == ["127.0.0.2"]
        for _ in range(100):
            try:
                r = httpx.get(f"http://127.0.0.2:{port}/api/health", timeout=1)
                break
            except httpx.HTTPError:
                import time
                time.sleep(0.05)
        assert r.json()["status"] == "ok"
        assert srv.watcher.check() == [] and len(starts) == 1   # no second queue
    finally:
        srv.watcher.stop()
        srv.should_exit = True


def test_keep_awake_setting(client):
    st = client.put("/api/desktop/settings", headers=client.desk, json={"keep_awake": True}).json()
    assert st["keep_awake"] is True and settings.load().keep_awake is True


def test_profile_names_differing_only_in_case_are_one(tmp_path, monkeypatch):
    """Josh's sign-in is Josh.dpapi but his music folder is 'josh': checking 'josh' against
    Josh.dpapi failed every few minutes (the file is locked to its exact name)."""
    from dielify import credstore, desktop_api, settings
    monkeypatch.setattr(credstore, "list_profiles", lambda store="credentials": ["Josh"])
    root = tmp_path / "lib"
    (root / "josh").mkdir(parents=True)
    (root / "Kid").mkdir()
    s = settings.load()
    s.library_root, s.active_profile = str(root), "Josh"
    assert desktop_api._profiles(s) == ["Josh", "Kid"]
