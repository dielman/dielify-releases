"""0.9.11: the first-start wizard (setup state, naming the first person, restore summary)."""

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAdapter, needs_ffmpeg
from dielify import auth, backup, credstore, library, settings
from dielify.downloader import download_track
from dielify.server import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DIELIFY_INSECURE_DEV_STORE", "1")
    settings.set_value("library_root", str(tmp_path / "Music"))
    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        c.desk = {"Authorization": f"Bearer {auth.enable_desktop_token()}"}
        yield c


def test_a_new_install_gets_the_wizard_and_names_its_first_person(client, tmp_path):
    st = client.get("/api/desktop/status", headers=client.desk).json()
    assert st["setup_needed"] and st["active_profile"] == "default"
    library.person("default")  # something touched the first profile already
    (tmp_path / "Music" / "default").mkdir(parents=True, exist_ok=True)
    assert client.post("/api/desktop/setup/name", json={"name": "no spaces"}, headers=client.desk).status_code == 400
    st = client.post("/api/desktop/setup/name", json={"name": "Sam"}, headers=client.desk).json()
    assert st["active_profile"] == "Sam"
    assert [p["profile"] for p in library.people()] == ["Sam"]
    assert not (tmp_path / "Music" / "default").exists() and (tmp_path / "Music" / "Sam").is_dir()
    st = client.post("/api/desktop/setup/done", headers=client.desk).json()
    assert not st["setup_needed"]
    # once set up, the wizard can't rename anyone
    assert client.post("/api/desktop/setup/name", json={"name": "Alex"}, headers=client.desk).status_code == 409


def test_installs_from_before_the_wizard_never_see_it(client):
    credstore.save("josh", {"cookie": "x"})
    assert not client.get("/api/desktop/status", headers=client.desk).json()["setup_needed"]


def test_phones_cant_use_the_wizard(client):
    auth.add_user("pixel", "default", password="sesame")
    tok = client.post("/api/auth/login", json={"username": "pixel", "password": "sesame", "device_name": "p"}).json()["token"]
    phone = {"Authorization": f"Bearer {tok}"}
    assert client.post("/api/desktop/setup/name", json={"name": "x"}, headers=phone).status_code == 403
    assert client.get("/api/desktop/setup/restored", headers=phone).status_code == 403


@needs_ffmpeg
def test_restore_summary(client, sample_info, tmp_path):
    settings.set_value("active_profile", "josh")
    download_track(FakeAdapter(sample_info), "abc123", settings.load(), profile="josh")
    credstore.save("josh", {"cookie": "x"})
    auth.add_user("pixel", "josh", password="sesame")
    r = client.get("/api/desktop/setup/restored", headers=client.desk).json()
    assert (r["songs"], r["files_found"], r["phone_logins"], r["phone_logins_readable"]) == (1, 1, 1, 1)
    assert r["people"] == [{"name": "josh", "role": "parent", "songs": 1, "youtube": True}]
    settings.set_value("library_root", str(tmp_path / "elsewhere"))  # the music isn't where the backup says
    assert client.get("/api/desktop/setup/restored", headers=client.desk).json()["files_found"] == 0


def test_backup_check(tmp_path):
    with library.connect():
        pass
    good = backup.make_backup(tmp_path / "b")
    assert backup.check(good) is None
    (tmp_path / "x.zip").write_bytes(b"not a zip")
    assert backup.check(tmp_path / "x.zip") == "That file isn't a Dielify backup."
    assert backup.check(tmp_path / "missing.zip") == "That file can't be found."
