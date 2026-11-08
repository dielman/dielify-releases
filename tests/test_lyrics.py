"""Lyrics: LRC parsing, sources in order, kept for offline, the API."""

from dielify import lyrics, settings
from test_api import SONGS, FakeDownloader, login, make_client, setup, wait_done  # noqa: F401


def test_parse_lrc():
    text = "[ti:Song]\n[00:01.50] One\n[00:03.2]Two\n[01:00.123][02:00.00] Chorus\nnot a line"
    assert lyrics.parse_lrc(text) == [(1500, "One"), (3200, "Two"), (60123, "Chorus"), (120000, "Chorus")]


def test_youtube_first_lrclib_for_synced_and_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(lyrics, "from_lrclib", lambda *a, **k: calls.append(a) or
                        {"lines": [(1000, "la")], "text": "la", "source": "LRCLIB"})
    timed = {"lines": [(0, "hi")], "text": "hi", "source": "Musixmatch"}
    assert lyrics.find("v1", lambda: timed, "A", "T") == timed and not calls      # synced from YouTube: done
    plain = {"lines": None, "text": "hi", "source": "LyricFind"}
    assert lyrics.find("v2", lambda: plain, "A", "T")["source"] == "LRCLIB"       # synced beats unsynced
    assert lyrics.find("v2", lambda: 1 / 0, "A", "T")["source"] == "LRCLIB"       # cached: no new lookups
    assert len(calls) == 1
    monkeypatch.setattr(lyrics, "from_lrclib", lambda *a, **k: None)
    assert lyrics.find("v3", None, "A", "T") is None
    assert lyrics.cached("v3") == (True, None)                                    # "none" remembered


def test_api_and_downloads_keep_lyrics(monkeypatch):
    monkeypatch.setattr(lyrics, "from_lrclib", lambda artist, title, *a: {"lines": [(500, f"{title}!")],
                                                                          "text": f"{title}!", "source": "LRCLIB"})
    with make_client(FakeDownloader()) as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s1"}).json()["downloads"][0]
        done = wait_done(c, h, job["id"])
        assert lyrics.cached("s1")[1]["text"] == "Song One!"                      # kept with the download
        r = c.get(f"/api/lyrics?track_id={done['track_id']}", headers=h).json()
        assert r == {"synced": True, "lines": [{"ms": 500, "text": "Song One!"}], "text": "Song One!", "source": "LRCLIB"}
        settings.set_value("offline", True)
        assert c.get("/api/lyrics?video_id=s1", headers=h).status_code == 200    # offline: from the PC's copy
        assert c.get("/api/lyrics?video_id=zz&title=X&artist=Y", headers=h).status_code == 404
        assert c.get("/api/lyrics", headers=h).status_code == 400


def test_leveller_measures_and_api_gives_gain(tmp_path):
    import shutil
    import pytest
    from dielify import leveller
    from dielify.library import connect
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    assert leveller.gain_db(-8.0) == -6.0 and leveller.gain_db(-30) == 8.0 and leveller.gain_db(None) is None
    with make_client(FakeDownloader()) as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s1"}).json()["downloads"][0]
        tid = wait_done(c, h, job["id"])["track_id"]
        assert c.get(f"/api/library/tracks/{tid}", headers=h).json()["gain_db"] is None   # not measured yet
        assert leveller.Leveller().run_once()
        with connect() as conn:
            lufs = conn.execute("SELECT loudness FROM tracks WHERE id = ?", (tid,)).fetchone()[0]
        assert -40 < lufs < 0                                                             # a real measurement
        assert c.get(f"/api/library/tracks/{tid}", headers=h).json()["gain_db"] == leveller.gain_db(lufs)
        assert not leveller.Leveller().run_once()                                         # nothing left


def test_keep_on_phone_lists_liked_top_and_playlist_songs():
    import time
    from dielify import ratings
    from dielify.library import connect
    with make_client(FakeDownloader()) as c:
        h = login(c)
        ids = {}
        for vid in ("s1", "s2", "s3"):
            job = c.post("/api/downloads", headers=h, json={"type": "song", "id": vid}).json()["downloads"][0]
            ids[vid] = wait_done(c, h, job["id"])["track_id"]
        ratings.set_rating("josh", "song", "s1", "Song One", ratings.UP)
        now = time.time()
        with connect() as conn:
            for i in range(3):
                conn.execute("INSERT INTO plays (profile, track_id, video_id, title, counted, started_at) "
                             "VALUES ('josh', ?, 's2', 'Song Two', 1, ?)", (ids["s2"], now - i))
            pl = conn.execute("INSERT INTO playlists (profile, name, created_at, updated_at) VALUES ('josh','P',?,?)",
                              (now, now)).lastrowid
            conn.execute("INSERT INTO playlist_items (playlist_id, position, video_id, title, added_at) "
                         "VALUES (?, 0, 's3', 'Other Song', ?)", (pl, now))
            conn.execute("INSERT INTO playlist_items (playlist_id, position, video_id, title, added_at) "
                         "VALUES (?, 1, 'notdownloaded', 'X', ?)", (pl, now))
        get = lambda q: [t["id"] for t in c.get(f"/api/keep?{q}", headers=h).json()["tracks"]]  # noqa: E731
        assert get("liked=true") == [ids["s1"]]
        assert get("top=10") == [ids["s2"]]
        assert get(f"playlists={pl}") == [ids["s3"]]
        assert sorted(get(f"liked=true&top=10&playlists={pl}")) == sorted(ids.values())
        assert get("") == []
