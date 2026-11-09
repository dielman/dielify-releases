"""YouTube sometimes sends an empty answer (JSONDecodeError): retry once, and Discover shows
the last home feed that loaded instead of an error."""

import json

import pytest

from dielify import custom_api, settings, yt_adapter
from dielify.yt_adapter import YouTubeError
from test_api import FakeYT, login, make_client, setup  # noqa: F401


def test_empty_answer_is_retried_once(monkeypatch):
    monkeypatch.setattr(yt_adapter.time, "sleep", lambda s: None)
    a = yt_adapter.YTMusicAdapter.__new__(yt_adapter.YTMusicAdapter)
    a._pace = lambda: None
    answers = [json.JSONDecodeError("Expecting value", "", 0), "ok"]

    def fn():
        x = answers.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    assert a._call("Loading", fn) == "ok"

    def never():
        raise json.JSONDecodeError("Expecting value", "", 0)
    with pytest.raises(YouTubeError, match="empty answer"):
        a._call("Loading the home feed", never)


class FlakyHome(FakeYT):
    broken = False

    def home(self, shelves=6):
        if FlakyHome.broken:
            raise YouTubeError("Loading the home feed failed: YouTube sent an empty answer")
        return super().home(shelves)


def test_home_falls_back_to_the_last_feed(monkeypatch, setup):
    settings.set_value("active_profile", "josh")
    monkeypatch.setattr(custom_api, "YTMusicAdapter", FlakyHome)
    custom_api.youtube.reset()
    custom_api._last_home.clear()
    with make_client() as c:
        h = login(c)
        FlakyHome.broken = True
        assert c.get("/api/discover/home", headers=h).status_code == 502   # nothing loaded yet
        FlakyHome.broken = False
        good = c.get("/api/discover/home", headers=h).json()
        FlakyHome.broken = True
        r = c.get("/api/discover/home", headers=h)
        assert r.status_code == 200 and r.json() == good
    FlakyHome.broken = False
