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
    with make_client() as c:
        h = login(c)
        FlakyHome.broken = True
        assert c.get("/api/discover/home", headers=h).status_code == 502   # nothing loaded yet
        FlakyHome.broken = False
        good = c.get("/api/discover/home", headers=h).json()
        FlakyHome.broken = True
        custom_api._feeds.update({k: (0.0, v) for k, (_, v) in custom_api._feeds.items()})  # hours old
        r = c.get("/api/discover/home", headers=h)
        assert r.status_code == 200 and r.json() == good
    FlakyHome.broken = False


class CountingHome(FakeYT):
    calls = 0

    def home(self, shelves=6):
        CountingHome.calls += 1
        return super().home(shelves)


def test_home_is_kept_for_ten_minutes(monkeypatch, setup):
    """Josh: Discover doesn't need fresh data from YouTube every load."""
    settings.set_value("active_profile", "josh")
    monkeypatch.setattr(custom_api, "YTMusicAdapter", CountingHome)
    custom_api.youtube.reset()
    CountingHome.calls = 0
    with make_client() as c:
        h = login(c)
        first = c.get("/api/discover/home", headers=h).json()
        assert c.get("/api/discover/home", headers=h).json() == first
        assert CountingHome.calls == 1                       # the second load came from the cache
        # 20 minutes later: shown at once, a fresh copy loads in the background
        custom_api._feeds.update({k: (v[0] - 1200, v[1]) for k, v in custom_api._feeds.items()})
        assert c.get("/api/discover/home", headers=h).json() == first
        for _ in range(50):
            if CountingHome.calls == 2 and not custom_api._refreshing:
                break
            import time
            time.sleep(0.05)
        assert CountingHome.calls == 2
        assert c.get("/api/discover/home", headers=h).json() == first
        assert CountingHome.calls == 2                       # fresh again


def test_background_jobs_wait_for_people(monkeypatch):
    """A background lookup never starts while someone's YouTube call is running, nor until
    QUIET_S after it ends (10 Nov 2026: lyrics lookups slipped in between Discover's calls)."""
    import threading
    import time
    yt = custom_api._YouTube()
    monkeypatch.setattr(yt, "QUIET_S", 0.3)
    order, release = [], threading.Event()

    def fake_call(profile, fn_name, *a, **k):
        order.append(("start", fn_name, time.monotonic()))
        if fn_name == "person":
            release.wait(2)
        order.append(("end", fn_name, time.monotonic()))
    monkeypatch.setattr(yt, "_call", fake_call)
    person = threading.Thread(target=lambda: yt.call("josh", "person"))
    person.start()
    time.sleep(0.1)
    bg = threading.Thread(target=lambda: yt.background("josh", "background"))
    bg.start()
    time.sleep(0.8)
    assert [x[:2] for x in order] == [("start", "person")]   # still waiting for the person
    release.set()
    person.join(); bg.join()
    person_end = next(t for kind, fn, t in order if (kind, fn) == ("end", "person"))
    bg_start = next(t for kind, fn, t in order if (kind, fn) == ("start", "background"))
    assert bg_start - person_end >= 0.3
