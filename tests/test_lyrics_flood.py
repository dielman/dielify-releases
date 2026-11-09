"""9 Nov 2026: a phone asked for 165 songs' lyrics at once and the PC stopped answering
(every server thread waited for YouTube). Lyrics lookups now take turns (2 at a time),
others get 503 quickly, and /api/health always answers."""

import threading
import time

from dielify import lyrics
from test_api import login, make_client, setup  # noqa: F401


def test_lookups_take_turns_and_the_rest_are_told_to_wait(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(lyrics, "from_lrclib", lambda *a, **k: (gate.wait(5), None)[1])
    monkeypatch.setattr(lyrics, "WAIT_S", 0.3)
    results = []

    def ask(i):
        try:
            lyrics.find(f"k{i}", None, "Band", f"Song {i}", wait_s=0.3)
            results.append("ok")
        except lyrics.Busy:
            results.append("busy")

    threads = [threading.Thread(target=ask, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    end = time.monotonic() + 5
    while results.count("busy") < 4 and time.monotonic() < end:
        time.sleep(0.05)
    assert results.count("busy") == 4 and "ok" not in results          # only two looked up at once
    gate.set()
    for t in threads:
        t.join()
    assert results.count("ok") == 2


def test_health_answers_while_lyrics_are_busy(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(lyrics, "from_lrclib", lambda *a, **k: (gate.wait(10), None)[1])
    with make_client() as c:
        h = login(c)
        slow = [threading.Thread(target=c.get, args=("/api/lyrics",),
                                 kwargs={"headers": h, "params": {"video_id": f"v{i}", "title": "t", "artist": "a"}})
                for i in range(8)]
        for t in slow:
            t.start()
        time.sleep(0.3)
        started = time.monotonic()
        assert c.get("/api/health").status_code == 200
        assert time.monotonic() - started < 2
        r = c.get("/api/lyrics", headers=h, params={"video_id": "vx", "title": "t", "artist": "a"})
        assert r.status_code == 503 and r.headers["retry-after"] == "60"
        gate.set()
        for t in slow:
            t.join()
