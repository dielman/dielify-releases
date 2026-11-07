"""Phase 3: our own API — login/devices, discovery, download queue, library playback."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_audio, make_image, needs_ffmpeg
from dielify import auth, custom_api, downloads, settings
from dielify.downloads import DownloadQueue
from dielify.server import create_app
from dielify.yt_adapter import NotSignedIn, Shelf, TrackInfo, YouTubeError, YTItem

pytestmark = needs_ffmpeg

SONGS = {
    "s1": TrackInfo(video_id="s1", title="Song One", artists=["Band"], album="Debut", album_id="MPREb_1",
                    album_artist="Band", track_number=1, track_total=2, year="2001"),
    "s2": TrackInfo(video_id="s2", title="Song Two", artists=["Band"], album="Debut", album_id="MPREb_1",
                    album_artist="Band", track_number=2, track_total=2, year="2001"),
    "s3": TrackInfo(video_id="s3", title="Other Song", artists=["Someone"], album="Single", year="2020"),
}


def item(vid: str) -> YTItem:
    t = SONGS[vid]
    return YTItem("song", vid, t.title, t.artists, t.album, t.album_id, t.year, 200)


class FakeYT:
    """Discovery side of the adapter, no network."""

    def __init__(self, **kwargs):
        pass

    def home(self, shelves=6):
        return [Shelf("Mixed for you", [item("s1"), item("s3")]),
                Shelf("New releases", [YTItem("album", "MPREb_1", "Debut", ["Band"], year="2001")])]

    def similar(self, video_id, limit=25):
        return [item(v) for v in SONGS if v != video_id][:limit]

    def charts(self, country="ZZ"):
        return {"country": "Global", "countries": ["ZZ", "GB"],
                "playlists": [YTItem("playlist", "PLtop", "Top 100")],
                "artists": [YTItem("artist", "UCband", "Band", subtitle="1M")]}

    def search_items(self, q, kind="song", limit=20):
        if kind not in ("song", "video", "album", "playlist", "artist"):
            raise ValueError("bad type")
        return [item(v) for v in SONGS if q.lower() in SONGS[v].title.lower()][:limit]

    def album(self, browse_id):
        if browse_id != "MPREb_1":
            raise YouTubeError("Loading the album failed: not found")
        return YTItem("album", browse_id, "Debut", ["Band"], year="2001"), [item("s1"), item("s2")]

    def playlist(self, playlist_id, limit=200):
        return YTItem("playlist", playlist_id, "Mix"), [item("s3"), item("s1")]


class FakeDownloader:
    """Download side of the adapter: real audio files, optional slowness/failures."""

    def __init__(self, slow=False, fail_times=0):
        self.slow, self.fail_times, self.calls = slow, fail_times, 0

    def get_track(self, video_id):
        return SONGS[video_id]

    def fetch_cover(self, url):
        return make_image(600, 600)

    def fetch_audio(self, video_id, dest_dir, quality, preferred_format, progress=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise YouTubeError("Download failed: HTTP 403")
        steps = 40 if self.slow else 2
        for i in range(1, steps + 1):
            if progress:
                progress({"status": "downloading", "downloaded_bytes": i, "total_bytes": steps})
            if self.slow:
                time.sleep(0.05)
        if progress:
            progress({"status": "finished"})
        return make_audio(Path(dest_dir), "aac", seconds=1)


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("DIELIFY_INSECURE_DEV_STORE", "1")
    monkeypatch.setattr(custom_api, "YTMusicAdapter", FakeYT)
    monkeypatch.setattr(downloads, "RETRY_DELAYS_S", (0, 0))
    custom_api.youtube.reset()
    custom_api.lockout = auth.Lockout()
    settings.set_value("library_root", str(tmp_path / "Music"))
    auth.add_user("josh", "josh", password="sesame")


def make_client(fake=None, factory=None):
    fake = fake or FakeDownloader()
    queue = DownloadQueue(adapter_factory=factory or (lambda profile: fake))
    return TestClient(create_app(queue))


def login(c, user="josh", password="sesame", device="test") -> dict:
    r = c.post("/api/auth/login", json={"username": user, "password": password, "device_name": device})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def wait_done(c, h, job_id, timeout=20) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = c.get(f"/api/downloads/{job_id}", headers=h).json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still {job['status']}")


# --- auth -------------------------------------------------------------------------

def test_login_tokens_and_devices():
    with make_client() as c:
        assert c.get("/api/discover/home").status_code == 401
        bad = c.post("/api/auth/login", json={"username": "josh", "password": "nope"})
        assert bad.status_code == 401
        h = login(c, device="Pixel")
        devices = c.get("/api/auth/devices", headers=h).json()["devices"]
        assert [(d["device_name"], d["current"]) for d in devices] == [("Pixel", True)]
        h2 = login(c, device="Laptop")
        other = next(d for d in c.get("/api/auth/devices", headers=h).json()["devices"] if not d["current"])
        assert c.delete(f"/api/auth/device-token/{other['id']}", headers=h).status_code == 204
        assert c.get("/api/settings", headers=h2).status_code == 401  # revoked
        assert c.get("/api/settings", headers=h).status_code == 200
        assert c.get("/api/settings", headers={"Authorization": "Bearer dielify_forged"}).status_code == 401


def test_tokens_stored_hashed_and_die_with_user():
    from dielify.library import connect
    with make_client() as c:
        h = login(c)
        token = h["Authorization"].split()[1]
        with connect() as conn:
            stored = [r[0] for r in conn.execute("SELECT token_hash FROM device_tokens")]
        assert token not in stored and len(stored[0]) == 64
        auth.remove_user("josh")
        assert c.get("/api/settings", headers=h).status_code == 401


def test_login_lockout():
    with make_client() as c:
        for _ in range(auth.MAX_FAILURES):
            c.post("/api/auth/login", json={"username": "josh", "password": "nope"})
        r = c.post("/api/auth/login", json={"username": "josh", "password": "sesame"})
        assert r.status_code == 429


# --- discovery --------------------------------------------------------------------

def test_discovery_endpoints():
    with make_client() as c:
        h = login(c)
        home = c.get("/api/discover/home", headers=h).json()["shelves"]
        assert [s["title"] for s in home] == ["Mixed for you", "New releases"]
        assert home[0]["items"][0] == {**home[0]["items"][0], "type": "song", "id": "s1",
                                       "library_track_id": None}
        sim = c.get("/api/discover/similar/s1", headers=h).json()["items"]
        assert [i["id"] for i in sim] == ["s2", "s3"]
        charts = c.get("/api/discover/charts", headers=h).json()
        assert charts["playlists"][0]["id"] == "PLtop" and charts["artists"][0]["type"] == "artist"
        found = c.get("/api/yt/search", params={"q": "two"}, headers=h).json()["items"]
        assert [i["id"] for i in found] == ["s2"]
        album = c.get("/api/yt/album/MPREb_1", headers=h).json()
        assert album["info"]["title"] == "Debut" and len(album["tracks"]) == 2
        assert c.get("/api/yt/album/nope", headers=h).status_code == 502
        assert c.get("/api/yt/search", params={"q": "x", "type": "podcast"}, headers=h).status_code == 422


def test_spec_is_published():
    with make_client() as c:
        spec = c.get("/api/openapi.json").json()
        assert "/api/downloads" in spec["paths"] and "/rest/{method}" not in spec["paths"]


# --- downloads --------------------------------------------------------------------

def test_discover_request_progress_play():
    """The Phase 3 acceptance flow, end to end."""
    with make_client() as c:
        h = login(c)
        song = c.get("/api/discover/similar/s2", headers=h).json()["items"][0]
        jobs = c.post("/api/downloads", headers=h, json={"type": "song", "id": song["id"],
                                                          "title": song["title"]}).json()["downloads"]
        assert len(jobs) == 1 and jobs[0]["status"] == "queued"
        job = wait_done(c, h, jobs[0]["id"])
        assert job["status"] == "done" and job["progress"] == 1.0 and job["track_id"]
        assert (job["title"], job["artist"], job["album"]) == ("Song One", "Band", "Debut")
        track = c.get(f"/api/library/tracks/{job['track_id']}", headers=h).json()
        assert track["video_id"] == "s1" and track["cover_url"]
        audio = c.get(track["stream_url"], headers=h)
        assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mp4"
        assert len(audio.content) == track["size"]
        part = c.get(track["stream_url"], headers={**h, "Range": "bytes=0-99"})
        assert part.status_code == 206 and len(part.content) == 100
        assert c.get(track["cover_url"], params={"size": 64}, headers=h).headers["content-type"] == "image/jpeg"
        # discovery now knows it's downloaded; asking again doesn't download twice
        again = c.get("/api/discover/similar/s2", headers=h).json()["items"][0]
        assert again["library_track_id"] == job["track_id"]
        dup = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s1"}).json()["downloads"][0]
        assert dup["status"] == "done" and dup["track_id"] == job["track_id"]


def test_album_request_queues_each_track():
    fake = FakeDownloader()
    with make_client(fake) as c:
        h = login(c)
        jobs = c.post("/api/downloads", headers=h, json={"type": "album", "id": "MPREb_1"}).json()["downloads"]
        assert [j["video_id"] for j in jobs] == ["s1", "s2"]
        assert {j["request_title"] for j in jobs} == {"Debut"} and len({j["request_id"] for j in jobs}) == 1
        done = [wait_done(c, h, j["id"]) for j in jobs]
        assert all(j["status"] == "done" for j in done) and fake.calls == 2
        listed = c.get("/api/downloads", headers=h).json()["downloads"]
        assert [j["id"] for j in listed] == sorted((j["id"] for j in jobs), reverse=True)
        assert c.get("/api/downloads", params={"active": True}, headers=h).json()["downloads"] == []


def test_retry_then_success():
    fake = FakeDownloader(fail_times=1)
    with make_client(fake) as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        job = wait_done(c, h, job["id"])
        assert job["status"] == "done" and job["attempts"] == 2


def test_gives_up_after_max_attempts():
    with make_client(FakeDownloader(fail_times=99)) as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        job = wait_done(c, h, job["id"])
        assert job["status"] == "failed" and job["attempts"] == downloads.MAX_ATTEMPTS
        assert "403" in job["error"]


class SignInFlips(FakeDownloader):
    """Signed out at first (as when browser cookies go stale), signed in later."""
    signed_in = False

    def account_name(self):
        if not SignInFlips.signed_in:
            raise NotSignedIn("YouTube answered as if you were signed out")
        return "Josh"


def test_dead_signin_waits_instead_of_downgrading(monkeypatch):
    monkeypatch.setattr(downloads, "SIGNIN_WAIT_S", 0.2)
    SignInFlips.signed_in = False
    fake = SignInFlips()
    with make_client(fake) as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        end = time.time() + 10
        while not (job := c.get(f"/api/downloads/{job['id']}", headers=h).json())["error"] and time.time() < end:
            time.sleep(0.05)
        assert job["status"] == "queued" and "dielify auth login" in job["error"]
        assert fake.calls == 0 and job["attempts"] == 0  # nothing downloaded at lower quality
        SignInFlips.signed_in = True  # Josh signs in again
        job = wait_done(c, h, job["id"])
        assert job["status"] == "done" and job["error"] is None and fake.calls == 1


def test_no_signin_at_all_waits():
    def no_login(profile):
        raise NotSignedIn("Profile 'josh' is not signed in")
    with make_client(factory=no_login) as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        time.sleep(1)
        job = c.get(f"/api/downloads/{job['id']}", headers=h).json()
        assert job["status"] == "queued" and "not signed in" in job["error"]
        assert c.delete(f"/api/downloads/{job['id']}", headers=h).json()["status"] == "cancelled"


def test_cancel_running_download(tmp_path):
    with make_client(FakeDownloader(slow=True)) as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        end = time.time() + 10
        while c.get(f"/api/downloads/{job['id']}", headers=h).json()["progress"] == 0 and time.time() < end:
            time.sleep(0.02)
        assert c.delete(f"/api/downloads/{job['id']}", headers=h).json()["status"] == "cancelled"
        time.sleep(0.5)
        job = c.get(f"/api/downloads/{job['id']}", headers=h).json()
        assert job["status"] == "cancelled" and job["track_id"] is None
        lib = settings.load().profile_library("josh")
        assert not list(lib.rglob("*.m4a")) and not list(lib.glob(".dielify-dl-*"))


def test_users_only_see_their_own_queue():
    auth.add_user("daughter", "daughter", password="pw2")
    with make_client() as c:
        h = login(c)
        job = c.post("/api/downloads", headers=h, json={"type": "song", "id": "s3"}).json()["downloads"][0]
        wait_done(c, h, job["id"])
        hd = login(c, "daughter", "pw2")
        assert c.get("/api/downloads", headers=hd).json()["downloads"] == []
        assert c.get(f"/api/downloads/{job['id']}", headers=hd).status_code == 404
        track_id = c.get(f"/api/downloads/{job['id']}", headers=h).json()["track_id"]
        assert c.get(f"/api/library/tracks/{track_id}/stream", headers=hd).status_code == 404


def test_interrupted_jobs_resume_after_restart():
    from dielify.library import connect
    queue = DownloadQueue(adapter_factory=lambda p: FakeDownloader())
    job = queue.enqueue("josh", [item("s3")], "song")[0]
    with connect() as conn:  # as if the PC was switched off mid-download
        conn.execute("UPDATE downloads SET status = 'downloading', progress = 0.4 WHERE id = ?", (job["id"],))
    with TestClient(create_app(queue)) as c:
        h = login(c)
        assert wait_done(c, h, job["id"])["status"] == "done"


def test_settings_read_and_change():
    with make_client() as c:
        h = login(c)
        s = c.get("/api/settings", headers=h).json()
        assert s["profile"] == "josh" and s["quality"] == "auto"
        r = c.put("/api/settings", headers=h, json={"quality": "standard", "cache_limit_gb": 20})
        assert r.json()["quality"] == "standard" and r.json()["cache_limit_gb"] == 20
        assert c.put("/api/settings", headers=h, json={"library_root": "C:/x"}).json()["library_root"] != "C:/x"
        assert c.put("/api/settings", headers=h, json={"quality": "ultra"}).status_code == 422
