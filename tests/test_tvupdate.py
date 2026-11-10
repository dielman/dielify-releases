"""0.9.10: the PC installs app updates on TVs that can't install them themselves (Josh's TV:
a Family Link kids profile blocks "install unknown apps")."""

import pytest

from dielify import tvupdate
from test_api import login, make_client, setup  # noqa: F401
from test_appshare import put_app
from test_kids_accounts import desk


class FakeAdb:
    def __init__(self, installed=909, connect="connected to 192.168.1.26:5555"):
        self.installed, self.connect, self.calls = installed, connect, []

    def __call__(self, adb, *args, timeout=60):
        self.calls.append(args)
        if args[0] == "connect":
            return 0, self.connect
        if "dumpsys" in args:
            return 0, f"    versionCode={self.installed} minSdk=29"
        if "install" in args:
            self.installed = 910
            return 0, "Performing Streamed Install\nSuccess"
        return 0, ""


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("DIELIFY_ANDROID_DIR", str(put_app(tmp_path)))       # the PC carries 0.9.10
    monkeypatch.setattr(tvupdate, "find_adb", lambda: "adb.exe")
    f = FakeAdb()
    monkeypatch.setattr(tvupdate, "_run", f)
    return f


def test_only_home_network_tvs_are_remembered():
    for ip in ("127.0.0.1", "100.73.103.100", "8.8.8.8", "nonsense", None):
        tvupdate.remember(ip, "x")
    tvupdate.remember("192.168.1.26", "Shed TV")
    assert list(tvupdate.known()) == ["192.168.1.26"]


def test_an_older_tv_gets_the_update(fake):
    tvupdate.remember("192.168.1.26", "Shed TV")
    assert tvupdate.update_all() == {"192.168.1.26": "Updated to 0.9.10"}
    assert any("install" in c for c in fake.calls)
    assert tvupdate.known()["192.168.1.26"]["version_code"] == 910
    fake.calls.clear()
    assert tvupdate.update_all() == {"192.168.1.26": "Up to date (0.9.10)"}   # nothing installed twice
    assert not any("install" in c for c in fake.calls)


def test_a_playing_tv_is_left_alone(fake):
    tvupdate.remember("192.168.1.26", "Shed TV")
    r = tvupdate.update_all(playing=lambda ip: True)
    assert r["192.168.1.26"].startswith("Playing") and not any("install" in c for c in fake.calls)


def test_tv_not_allowed_or_off(fake):
    tvupdate.remember("192.168.1.26", "Shed TV")
    fake.connect = "failed to authenticate to 192.168.1.26:5555"
    assert "Allow" in tvupdate.update_all()["192.168.1.26"]
    fake.connect = "failed to connect to '192.168.1.26:5555': Connection refused"
    assert "USB debugging" in tvupdate.update_all()["192.168.1.26"]


def test_pc_settings_and_pairing_remember_the_tv(fake):
    from dielify import pairing
    pairing.forget_all()
    with make_client() as c:
        h = login(c)
        assert c.get("/api/desktop/tvs", headers=h).status_code == 403            # PC only
        tv = c.post("/api/pair/start", json={"device_name": "Shed TV"}).json()
        tvupdate.remember("192.168.1.26", "Shed TV")  # the test client's address isn't a home one
        c.post(f"/api/pair/{tv['code']}/approve", headers=h, json={"person": "josh"})
        listing = c.get("/api/desktop/tvs", headers=desk(c)).json()
        assert listing["adb"] and listing["app_version"] == "0.9.10"
        assert [t["name"] for t in listing["tvs"]] == ["Shed TV"]
        after = c.post("/api/desktop/tvs/update", headers=desk(c)).json()
        assert after["tvs"][0]["result"] == "Updated to 0.9.10"
        assert c.delete("/api/desktop/tvs/192.168.1.26", headers=desk(c)).status_code == 204
        assert c.get("/api/desktop/tvs", headers=desk(c)).json()["tvs"] == []
