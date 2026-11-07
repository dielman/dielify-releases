"""Paths, settings, credential store and YouTube-adapter helpers (no network)."""

import json
import sys

import pytest

from dielify import credstore, settings
from dielify.paths import safe_name
from dielify.yt_adapter import (YouTubeError, _parse_duration, cookie_header_to_netscape,
                            parse_browser_headers, upscale_cover_url)

# --- paths ---


@pytest.mark.parametrize("raw,expected", [
    ("AC/DC", "AC_DC"),
    ('What? "Why" <now>', "What_ _Why_ _now_"),
    ("Trailing dots...", "Trailing dots"),
    ("CON", "_CON"),
    ("nul.txt", "_nul.txt"),
    ("   ", "Unknown"),
    ("Beyoncé", "Beyoncé"),
])
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


def test_safe_name_truncates():
    assert len(safe_name("x" * 500)) == 120

# --- settings ---


def test_settings_defaults_and_roundtrip(tmp_path):
    s = settings.load()
    assert s.quality == "auto" and s.library_root
    settings.set_value("library_root", str(tmp_path / "Music"))
    settings.set_value("quality", "standard")
    settings.set_value("cache_limit_gb", "50")
    s2 = settings.load()
    assert s2.library_root == str((tmp_path / "Music").resolve())
    assert s2.quality == "standard" and s2.cache_limit_gb == 50.0
    assert s2.profile_library("josh") == (tmp_path / "Music").resolve() / "josh"


def test_settings_rejects_bad_values():
    with pytest.raises(ValueError):
        settings.set_value("quality", "ultra")
    with pytest.raises(KeyError):
        settings.set_value("nope", "1")

# --- credential store ---


@pytest.fixture
def not_windows(monkeypatch):
    """Exercise the non-Windows code path even when the tests run on Windows."""
    monkeypatch.setattr(credstore, "_is_windows", lambda: False)


def test_credstore_refuses_plaintext_without_opt_in(not_windows):
    with pytest.raises(credstore.CredentialError):
        credstore.save("josh", {"cookie": "SAPISID=x"})


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_credstore_roundtrip_dpapi():
    auth = {"cookie": "SAPISID=secret; HSID=y", "x-goog-authuser": "0"}
    path = credstore.save("josh", auth)
    raw = path.read_bytes()
    assert raw.startswith(b"DPAPI1") and b"SAPISID" not in raw
    assert credstore.load("josh") == auth
    # Bound to the profile name: another profile's entropy cannot decrypt it.
    other = path.with_name("daughter.dpapi")
    other.write_bytes(raw)
    with pytest.raises(credstore.CredentialError):
        credstore.load("daughter")


def test_credstore_roundtrip_dev(monkeypatch, isolated_home, not_windows):
    monkeypatch.setenv("DIELIFY_INSECURE_DEV_STORE", "1")
    auth = {"cookie": "SAPISID=secret; HSID=y", "x-goog-authuser": "0"}
    path = credstore.save("josh", auth)
    assert b"SAPISID=secret" not in path.read_bytes()  # at least not raw text
    assert credstore.load("josh") == auth
    assert credstore.list_profiles() == ["josh"]
    assert credstore.load("daughter") is None
    assert credstore.delete("josh") and credstore.load("josh") is None


def test_credstore_dev_file_unusable_without_opt_in(monkeypatch, not_windows):
    monkeypatch.setenv("DIELIFY_INSECURE_DEV_STORE", "1")
    credstore.save("josh", {"cookie": "a=b"})
    monkeypatch.delenv("DIELIFY_INSECURE_DEV_STORE")
    with pytest.raises(credstore.CredentialError):
        credstore.load("josh")

# --- adapter helpers ---


def test_cookie_header_to_netscape():
    text = cookie_header_to_netscape("SAPISID=abc/def; __Secure-3PAPISID=xyz; PREF=f6=40000000")
    lines = text.splitlines()
    assert lines[0] == "# Netscape HTTP Cookie File"
    rows = [l.split("\t") for l in lines[1:]]
    assert {r[5]: r[6] for r in rows} == {
        "SAPISID": "abc/def", "__Secure-3PAPISID": "xyz", "PREF": "f6=40000000"}
    assert all(r[0] == ".youtube.com" and len(r) == 7 for r in rows)


def test_cookie_header_empty_raises():
    with pytest.raises(YouTubeError):
        cookie_header_to_netscape("")


def test_upscale_cover_url():
    assert upscale_cover_url("https://lh3.googleusercontent.com/abc=w60-h60-l90-rj") \
        == "https://lh3.googleusercontent.com/abc=w1200-h1200-l90-rj"
    assert upscale_cover_url("https://i.ytimg.com/vi/ID/sddefault.jpg?sqp=1") \
        == "https://i.ytimg.com/vi/ID/maxresdefault.jpg"
    assert upscale_cover_url(None) is None


def test_parse_duration():
    assert _parse_duration("4:08") == 248
    assert _parse_duration("1:02:03") == 3723
    assert _parse_duration("bad") is None


RAW_HEADERS = """accept: */*
accept-language: en-AU,en;q=0.9
content-type: application/json
cookie: VISITOR_INFO1_LIVE=v; SAPISID=abc/def; __Secure-3PAPISID=abc/def; HSID=h
origin: https://music.youtube.com
user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)
x-goog-authuser: 0
x-origin: https://music.youtube.com"""


def test_parse_browser_headers_ok():
    auth = parse_browser_headers(RAW_HEADERS)
    assert "SAPISID=abc/def" in auth["cookie"]
    json.dumps(auth)  # must be storable


def test_parse_browser_headers_needs_signin_cookie():
    with pytest.raises(YouTubeError):
        parse_browser_headers(RAW_HEADERS.replace("SAPISID=abc/def; __Secure-3PAPISID=abc/def; ", ""))


# --- header parsing (all values fake) ---

_HEADERS = {"accept": "*/*", "authorization": "SAPISIDHASH 1_abc",
            "cookie": "SAPISID=fake/x; HSID=y", "x-goog-authuser": "0",
            "x-origin": "https://music.youtube.com"}


@pytest.mark.parametrize("fmt", ["raw", "chrome_colon", "chrome_bare", "tabs"])
def test_parse_browser_headers_formats(fmt):
    if fmt == "raw":
        text = ":authority: music.youtube.com\n" + "\n".join(f"{k}: {v}" for k, v in _HEADERS.items())
    elif fmt == "chrome_colon":
        text = ":authority:\nmusic.youtube.com\n" + "\n".join(f"{k}:\n{v}" for k, v in _HEADERS.items())
    elif fmt == "chrome_bare":
        text = "\n".join(f"{k}\n{v}" for k, v in _HEADERS.items())
    else:
        text = "\n".join(f"{k}:\t{v}" for k, v in _HEADERS.items())
    # Windows clipboard line endings plus Chrome's multi-line x-client-data block.
    text = text.replace("accept:", "x-client-data:\nCIa2yQE=\nDecoded:\nmessage X {\n  // ids\n}\naccept:", 1)
    auth = parse_browser_headers(text.replace("\n", "\r\n"))
    assert auth["cookie"] == _HEADERS["cookie"] and auth["x-goog-authuser"] == "0"


def test_parse_browser_headers_names_missing_without_values():
    with pytest.raises(YouTubeError) as e:
        parse_browser_headers("content-type: text/html\nset-cookie: SECRET=1")
    msg = str(e.value)
    assert "missing: cookie, x-goog-authuser" in msg and "set-cookie" in msg
    assert "SECRET" not in msg


def test_find_account_name_anywhere_in_menu():
    from dielify.yt_adapter import _find_account_name
    signed_in = {"actions": [{"popup": {"x": [{"activeAccountHeaderRenderer": {
        "accountName": {"runs": [{"text": "Josh"}]}}}]}}]}
    signed_out = {"actions": [{"openPopupAction": {"popup": {"multiPageMenuRenderer": {
        "sections": [{"multiPageMenuSectionRenderer": {"items": []}}]}}}}]}
    assert _find_account_name(signed_in) == "Josh"
    assert _find_account_name(signed_out) is None


def test_cookie_report_lists_names_not_values():
    from dielify.yt_adapter import _cookie_report
    report = _cookie_report({"Cookie": "SAPISID=topsecret; SID=alsosecret; weird=a\"b", "x-goog-authuser": "1"})
    assert "3 cookies copied" in report and "x-goog-authuser=1" in report
    assert "HSID" in report and "SAPISID," not in report.split("missing:")[1]
    assert "secret" not in report


def test_parse_browser_headers_rejects_plain_youtube():
    text = "\n".join(f"{k}: {v}" for k, v in {**_HEADERS, "x-origin": "https://www.youtube.com"}.items())
    with pytest.raises(YouTubeError, match="www.youtube.com"):
        parse_browser_headers(text)


def test_sapisid_hash_matches_browser_format():
    from dielify.yt_adapter import sapisid_hash
    import hashlib
    expected = hashlib.sha1(b"1700000000 abc/def https://music.youtube.com").hexdigest()
    assert sapisid_hash("abc/def", now=1700000000) == f"SAPISIDHASH 1700000000_{expected}"


def test_headers_from_window_cookies():
    from dielify.yt_adapter import NotSignedIn, headers_from_cookies
    auth = headers_from_cookies({"SAPISID": "a/b", "__Secure-3PAPISID": "a/b", "SID": "x"},
                                authuser="1", pageid="1234")
    assert auth["authorization"].startswith("SAPISIDHASH ") and "SAPISID=a/b" in auth["cookie"]
    assert auth["x-goog-authuser"] == "1" and auth["x-goog-pageid"] == "1234"
    with pytest.raises(NotSignedIn):
        headers_from_cookies({"YSC": "x"})


# --- carry-over from the old name (ymp) ---

def test_legacy_data_folder_is_moved(monkeypatch, tmp_path):
    from dielify import paths
    monkeypatch.delenv("DIELIFY_HOME")
    monkeypatch.setattr(paths, "user_data_dir", lambda name, appauthor=False: str(tmp_path / name))
    (tmp_path / "ymp" / "credentials").mkdir(parents=True)
    (tmp_path / "ymp" / "settings.json").write_text("{}")
    d = paths.app_data_dir()
    assert d == tmp_path / "Dielify" and (d / "settings.json").exists() and (d / "credentials").is_dir()
    assert not (tmp_path / "ymp").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_legacy_encrypted_login_opens_and_is_resaved():
    legacy = credstore._entropy("josh", "credentials", credstore._LEGACY_ENTROPY_PREFIX)
    path = credstore._cred_path("josh")
    path.write_bytes(b"DPAPI1" + credstore._dpapi(json.dumps({"cookie": "a=b"}).encode(), legacy, True))
    old_blob = path.read_bytes()
    assert credstore.load("josh") == {"cookie": "a=b"}
    assert path.read_bytes() != old_blob                   # re-saved with the new name
    assert credstore.load("josh") == {"cookie": "a=b"}     # and opens the new way


def test_legacy_database_is_renamed(isolated_home):
    import sqlite3
    from dielify.library import connect, db_path
    isolated_home.mkdir(parents=True, exist_ok=True)
    old = isolated_home / "ymp.db"
    c = sqlite3.connect(old)
    c.execute("CREATE TABLE marker (x)")
    c.commit()
    c.close()
    assert db_path() == isolated_home / "dielify.db" and not old.exists()
    with connect() as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'marker'").fetchone()
