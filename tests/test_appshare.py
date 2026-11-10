"""0.9.10: the PC hands out the phone / TV app it was installed with (updates without GitHub)."""

import json

from dielify import appshare
from test_api import login, make_client, setup  # noqa: F401


def put_app(tmp_path, data=b"PK fake apk", version="0.9.10", **override):
    d = tmp_path / "android"
    d.mkdir(exist_ok=True)
    (d / appshare.APK).write_bytes(data)
    meta = {**appshare.describe(d / appshare.APK, version), **override}
    (d / appshare.INFO).write_text(json.dumps(meta))
    return d


def test_version_code_matches_gradle():
    assert appshare.version_code("0.9.9") == 909 and appshare.version_code("0.9.10") == 910
    assert appshare.version_code("1.0.0") == 10000


def test_pc_hands_out_the_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DIELIFY_ANDROID_DIR", str(put_app(tmp_path)))
    with make_client() as c:
        assert c.get("/api/app/android").status_code == 401                # signed-in devices only
        h = login(c)
        info = c.get("/api/app/android", headers=h).json()
        assert info["version"] == "0.9.10" and info["version_code"] == 910 and info["size"] == 11
        r = c.get(info["url"], headers=h)
        assert r.status_code == 200 and r.content == b"PK fake apk"
        assert r.headers["content-type"] == "application/vnd.android.package-archive"


def test_nothing_to_hand_out(tmp_path, monkeypatch):
    monkeypatch.setenv("DIELIFY_ANDROID_DIR", str(tmp_path / "none"))
    with make_client() as c:
        h = login(c)
        assert c.get("/api/app/android", headers=h).status_code == 404
        assert c.get("/api/app/android/apk", headers=h).status_code == 404


def test_a_file_that_doesnt_match_isnt_handed_out(tmp_path, monkeypatch):
    monkeypatch.setenv("DIELIFY_ANDROID_DIR", str(put_app(tmp_path, sha256="0" * 64)))
    with make_client() as c:
        h = login(c)
        assert c.get("/api/app/android", headers=h).status_code == 404
