"""0.9.10: a TV signs in with a QR code that a parent's phone (or the PC app) approves."""

import pytest

from dielify import pairing, settings
from test_api import login, make_client, setup  # noqa: F401
from test_kids_accounts import add_kid, desk


@pytest.fixture(autouse=True)
def clean(setup):
    settings.set_value("active_profile", "josh")
    pairing.forget_all()
    yield
    pairing.forget_all()


def start(c, name="Shed TV"):
    r = c.post("/api/pair/start", json={"device_name": name})
    assert r.status_code == 200, r.text
    return r.json()


def poll(c, secret):
    return c.post("/api/pair/poll", json={"secret": secret}).json()


def test_tv_pairs_with_a_parents_phone():
    with make_client() as c:
        josh = login(c)
        tv = start(c)
        assert tv["link"] == f"dielify://pair/{tv['code']}" and len(tv["code"]) == 9
        assert poll(c, tv["secret"])["status"] == "waiting"

        # the phone scans the QR (any form of the code works) and sees what it's approving
        info = c.get(f"/api/pair/{tv['code'].lower().replace('-', '')}", headers=josh).json()
        assert info["device_name"] == "Shed TV" and info["address"]
        assert info["suggested"] == "josh" and [p["name"] for p in info["people"]] == ["josh"]

        r = c.post(f"/api/pair/{tv['code']}/approve", headers=josh, json={"person": "josh"})
        assert r.status_code == 200 and r.json() == {"device_name": "Shed TV", "person": "josh"}

        got = poll(c, tv["secret"])
        assert got["status"] == "approved" and got["token"].startswith("dielify_") and got["profile"] == "josh"
        assert poll(c, tv["secret"])["status"] == "expired"           # the key is handed over once
        tv_auth = {"Authorization": f"Bearer {got['token']}"}
        assert c.get("/api/me", headers=tv_auth).json()["profile"] == "josh"
        names = [d["device_name"] for d in c.get("/api/auth/devices", headers=josh).json()["devices"]]
        assert "Shed TV" in names                                      # listed, and can be signed out
        # a used code can't be approved again
        assert c.post(f"/api/pair/{tv['code']}/approve", headers=josh, json={"person": "josh"}).status_code == 404


def test_parent_picks_the_kid_and_kids_cant_approve():
    with make_client() as c:
        josh = login(c)
        emma = add_kid(c)
        tv = start(c, "Emma's TV")
        assert c.get(f"/api/pair/{tv['code']}", headers=emma).status_code == 403     # ask a parent
        assert c.post(f"/api/pair/{tv['code']}/approve", headers=emma, json={"person": "emma"}).status_code == 403
        people = {p["name"]: p for p in c.get(f"/api/pair/{tv['code']}", headers=josh).json()["people"]}
        assert people["emma"]["role"] == "child" and people["emma"]["can_sign_in"]
        assert c.post(f"/api/pair/{tv['code']}/approve", headers=josh, json={"person": "zoe"}).status_code == 404
        assert c.post(f"/api/pair/{tv['code']}/approve", headers=josh, json={"person": "Emma"}).status_code == 200
        got = poll(c, tv["secret"])
        assert got["profile"] == "emma"
        me = c.get("/api/me", headers={"Authorization": f"Bearer {got['token']}"}).json()
        assert me["role"] == "child"                                   # her filters apply on the TV


def test_pc_app_approves_a_typed_code():
    with make_client() as c:
        login(c)
        tv = start(c)
        r = c.post(f"/api/pair/{tv['code']}/approve", headers=desk(c), json={"person": "josh"})
        assert r.status_code == 200
        assert poll(c, tv["secret"])["status"] == "approved"


def test_refused_wrong_secret_expiry_and_limits(monkeypatch):
    with make_client() as c:
        josh = login(c)
        tv = start(c)
        assert poll(c, "not-the-secret")["status"] == "expired"        # guessing gets nothing
        assert c.post(f"/api/pair/{tv['code']}/refuse", headers=josh).status_code == 204
        assert poll(c, tv["secret"])["status"] == "refused"
        assert c.post("/api/pair/start", json={}).status_code == 200   # name is optional
        assert c.get("/api/pair/ABCD-EFGH", headers=josh).status_code == 404
        assert c.post("/api/pair/start", json={"device_name": "x"}).status_code == 200
        # ten minutes later the code is gone
        old = start(c)
        monkeypatch.setattr(pairing.time, "time", lambda real=pairing.time.time: real() + pairing.PAIR_TTL_S + 1)
        assert poll(c, old["secret"])["status"] == "expired"
        assert c.get(f"/api/pair/{old['code']}", headers=josh).status_code == 404
        monkeypatch.undo()
        # starting needs no sign-in, so it's capped
        pairing.forget_all()
        for _ in range(pairing.MAX_PENDING):
            start(c)
        assert c.post("/api/pair/start", json={"device_name": "x"}).status_code == 429
        pairing.forget_all()
        pairing._state.starts["testclient"] = [pairing.time.time()] * pairing.STARTS_PER_ADDRESS
        assert c.post("/api/pair/start", json={"device_name": "x"}).status_code == 429


def test_needs_sign_in_to_look_up_or_approve():
    with make_client() as c:
        tv = start(c)
        assert c.get(f"/api/pair/{tv['code']}").status_code == 401
        assert c.post(f"/api/pair/{tv['code']}/approve", json={"person": "josh"}).status_code == 401


def test_only_home_addresses_are_announced():
    from dielify.announce import home_addresses
    assert home_addresses(["127.0.0.1", "100.73.103.100", "192.168.1.249", "10.0.0.5", "8.8.8.8", "::1"]) == \
        ["10.0.0.5", "192.168.1.249"]
