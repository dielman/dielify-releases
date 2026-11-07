"""Paths, settings, credential store and YouTube-adapter helpers (no network)."""

import json

import pytest

from ymp import credstore, settings
from ymp.paths import safe_name
from ymp.yt_adapter import (YouTubeError, _parse_duration, cookie_header_to_netscape,
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


def test_credstore_refuses_plaintext_without_opt_in():
    with pytest.raises(credstore.CredentialError):
        credstore.save("josh", {"cookie": "SAPISID=x"})


def test_credstore_roundtrip_dev(monkeypatch, isolated_home):
    monkeypatch.setenv("YMP_INSECURE_DEV_STORE", "1")
    auth = {"cookie": "SAPISID=secret; HSID=y", "x-goog-authuser": "0"}
    path = credstore.save("josh", auth)
    assert b"SAPISID=secret" not in path.read_bytes()  # at least not raw text
    assert credstore.load("josh") == auth
    assert credstore.list_profiles() == ["josh"]
    assert credstore.load("daughter") is None
    assert credstore.delete("josh") and credstore.load("josh") is None


def test_credstore_dev_file_unusable_without_opt_in(monkeypatch):
    monkeypatch.setenv("YMP_INSECURE_DEV_STORE", "1")
    credstore.save("josh", {"cookie": "a=b"})
    monkeypatch.delenv("YMP_INSECURE_DEV_STORE")
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
