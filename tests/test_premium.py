"""YouTube Music Premium lapsing (Josh, 21 Nov 2026): downloads never stop (standard quality), a
notice says so, a better copy is never replaced by a worse one, and when Premium is back the
lower-quality songs are downloaded again at full quality and replace the old files."""

import pytest

from dielify import downloader, notices, premium, upgrades
from dielify.library import connect
from test_api import FakeDownloader, login, make_client, setup, wait_done  # noqa: F401
from test_kids_accounts import add_kid


@pytest.fixture(autouse=True)
def pc_profile(setup):
    from dielify import settings
    settings.set_value("active_profile", "josh")


def keys(profile):
    return [n["key"] for n in notices.for_person(profile)]


def test_formats_tell_premium_apart():
    assert premium.has_premium_formats([{"format_id": "251"}, {"format_id": "774"}])
    assert premium.has_premium_formats([{"format_id": "141-drc"}])
    assert not premium.has_premium_formats([{"format_id": "251"}, {"format_id": "140"}])


def test_lapse_is_rechecked_noticed_and_cleared_when_premium_is_back():
    with make_client(FakeDownloader()) as c:
        login(c)
        kid = add_kid(c)  # noqa: F841 - a kids account in the household
        assert premium.observe("josh", True, "good1") is None
        assert premium.is_premium("josh") is True
        # a couple of songs without Premium formats prove nothing
        assert premium.observe("josh", False, "odd1") is None
        assert premium.observe("josh", False, "odd2") is None
        # the third: re-check a song that had them
        assert premium.observe("josh", False, "odd3") == "good1"
        premium.confirm("josh", True)          # still there: just odd songs
        assert premium.is_premium("josh") is True and keys("josh") == []
        for v in ("a", "b"):
            premium.observe("josh", False, v)
        assert premium.observe("josh", False, "c") == "good1"
        premium.confirm("josh", False)         # gone: lapsed
        assert premium.is_premium("josh") is False
        assert keys("josh") == ["premium-lapsed:josh"]
        assert keys("emma") == []              # parents only
        n = notices.for_person("josh")[0]
        assert n["level"] == "warning" and not n["can_dismiss"] and "carry on" in n["body"]

        back = []
        premium._on_back.append(back.append)
        try:
            premium.observe("josh", True, "good2")
        finally:
            premium._on_back.remove(back.append)
        assert back == ["josh"] and premium.is_premium("josh") is True
        assert keys("josh") == ["premium-back:josh"]
        assert notices.dismiss("josh", "premium-back:josh") and keys("josh") == []


def test_no_song_to_recheck_decides_after_more_misses():
    with make_client(FakeDownloader()) as c:
        login(c)
        for n in range(premium.MISSES_TO_LAPSE - 1):
            premium.observe("josh", False, f"v{n}")
        assert premium.is_premium("josh") is None
        premium.observe("josh", False, "last")
        assert premium.is_premium("josh") is False and keys("josh") == ["premium-lapsed:josh"]


def test_notifications_api_read_and_dismiss():
    with make_client(FakeDownloader()) as c:
        h = login(c)
        notices.post("premium-lapsed:josh", "josh", "Lapsed", "Body")
        notices.post("premium-back:josh", "josh", "Back", "Body", level=notices.INFO)
        r = c.get("/api/notifications", headers=h).json()
        assert r["unread"] == 2 and {n["key"] for n in r["notifications"]} == {"premium-lapsed:josh", "premium-back:josh"}
        assert c.post("/api/notifications/read", headers=h).status_code == 204
        assert c.get("/api/notifications", headers=h).json()["unread"] == 0
        assert c.delete("/api/notifications/premium-lapsed:josh", headers=h).status_code == 404  # warnings stay
        assert c.delete("/api/notifications/premium-back:josh", headers=h).status_code == 204


def _song_in_library(c, h):
    job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s1"}).json()["downloads"][0]
    done = wait_done(c, h, job["id"])
    assert done["status"] == "done"
    with connect() as conn:
        return dict(conn.execute("SELECT id, relpath, bitrate_kbps, mtime FROM tracks WHERE video_id = 's1'").fetchone())


def _run_upgrades(c, h):
    n = upgrades.run_once(c.app.state.queue)
    jobs = [d for d in c.get("/api/downloads", headers=h).json()["downloads"] if d["request_type"] == "upgrade"]
    for d in jobs:
        assert wait_done(c, h, d["id"])["status"] == "done"
    return n


def test_premium_back_upgrades_low_songs_in_place(monkeypatch):
    with make_client(FakeDownloader()) as c:
        h = login(c)
        before = _song_in_library(c, h)
        assert before["bitrate_kbps"] < premium.LOW_KBPS       # the test file is 128 kbps
        assert _run_upgrades(c, h) == 0                       # Premium not known yet: nothing
        premium.observe("josh", True, "s1")
        vals = iter([128, 260])
        monkeypatch.setattr(downloader, "_kbps", lambda path: next(vals))  # old copy, new copy
        assert _run_upgrades(c, h) == 1
        with connect() as conn:
            after = dict(conn.execute("SELECT id, relpath, upgrade_tried_at FROM tracks WHERE video_id = 's1'").fetchone())
            in_lib = conn.execute("SELECT COUNT(*) FROM library_items WHERE track_id = ?", (before["id"],)).fetchone()[0]
        assert after["id"] == before["id"] and after["upgrade_tried_at"]   # same song: plays/playlists stay
        assert in_lib == 1
        assert _run_upgrades(c, h) == 0                       # tried this month already


def test_a_lower_quality_copy_never_replaces_a_better_one(monkeypatch):
    with make_client(FakeDownloader()) as c:
        h = login(c)
        before = _song_in_library(c, h)
        premium.observe("josh", True, "s1")
        vals = iter([260, 128])
        monkeypatch.setattr(downloader, "_kbps", lambda path: next(vals))  # old better than new
        assert _run_upgrades(c, h) == 1
        with connect() as conn:
            after = dict(conn.execute("SELECT id, relpath, mtime FROM tracks WHERE video_id = 's1'").fetchone())
        assert (after["id"], after["relpath"], after["mtime"]) == (before["id"], before["relpath"], before["mtime"])


def test_upgrades_wait_behind_normal_downloads():
    from dielify.downloads import NEXT_ORDER
    assert "priority < 0 THEN 2" in NEXT_ORDER


def test_clear_failed_downloads():
    with make_client(FakeDownloader(fail_times=99)) as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s1"}).json()["downloads"][0]
        assert wait_done(c, h, job["id"])["status"] == "failed"
        r = c.post("/api/downloads/clear-failed", headers=h).json()
        assert r["removed"] == 1
        assert not [d for d in c.get("/api/downloads?finished=true", headers=h).json()["downloads"]
                    if d["status"] == "failed"]


def test_downloads_report_what_youtube_offered():
    from dielify.yt_adapter import YTMusicAdapter
    with make_client(FakeDownloader()) as c:
        login(c)
        a = YTMusicAdapter.__new__(YTMusicAdapter)
        a.account = "josh"
        a._note_premium({"formats": [{"format_id": "251"}, {"format_id": "774"}]}, "v1", "cookies.txt")
        assert premium.is_premium("josh") is True
        a._note_premium({"formats": [{"format_id": "251"}]}, "v2", None)   # signed out: not counted
        assert premium.state("josh")["misses"] == 0
        a.account = None
        a._note_premium({"formats": [{"format_id": "251"}]}, "v3", "cookies.txt")  # CLI: not counted
        assert premium.state("josh")["misses"] == 0
