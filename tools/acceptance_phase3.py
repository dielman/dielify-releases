"""Phase 3 acceptance test client: discover a track, request it, watch progress, play it.

    python tools/acceptance_phase3.py http://127.0.0.1:4747 USER [--seed VIDEO_ID]

Asks for the server user's password (never pass it on the command line).
"""

from __future__ import annotations

import argparse
import getpass
import sys
import time

try:
    import httpx
except ImportError:
    sys.exit("This needs the project's environment. Run it as:\n"
             "  .venv\\Scripts\\python tools\\acceptance_phase3.py " + " ".join(sys.argv[1:]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="server address, e.g. http://127.0.0.1:4747")
    ap.add_argument("user")
    ap.add_argument("--seed", default="BaxnrepwXck", help="find songs similar to this video id")
    ap.add_argument("--password-env", help=argparse.SUPPRESS)  # for scripted runs
    args = ap.parse_args()
    import os
    password = os.environ[args.password_env] if args.password_env else getpass.getpass(
        f"Server password for '{args.user}' (the one Symfonium uses; typing is hidden): ")

    c = httpx.Client(base_url=args.base, timeout=60)
    r = c.post("/api/auth/login", json={"username": args.user, "password": password,
                                        "device_name": "phase-3 acceptance"})
    r.raise_for_status()
    login = r.json()
    c.headers["Authorization"] = f"Bearer {login['token']}"
    print(f"1. Signed in as {login['username']} (profile {login['profile']}, device {login['device_id']})")

    try:
        home = c.get("/api/discover/home", params={"shelves": 3}).raise_for_status().json()
        print("2. Home feed:", "; ".join(f"{s['title']} ({len(s['items'])})" for s in home["shelves"]))

        similar = c.get(f"/api/discover/similar/{args.seed}", params={"limit": 15}).raise_for_status().json()
        pick = next((i for i in similar["items"] if i["type"] == "song" and not i["library_track_id"]), None)
        if pick is None:
            print("   Every similar song is already downloaded; nothing new to request.")
            return 1
        print(f"3. Discovered (similar to {args.seed}): {pick['title']} — {', '.join(pick['artists'])}")

        jobs = c.post("/api/downloads", json={"type": "song", "id": pick["id"], "title": pick["title"],
                                              "artists": pick["artists"]}).raise_for_status().json()
        job = jobs["downloads"][0]
        print(f"4. Requested: job {job['id']} is {job['status']}")

        print("5. Progress:", end=" ", flush=True)
        last = None
        while job["status"] not in ("done", "failed", "cancelled"):
            time.sleep(0.5)
            job = c.get(f"/api/downloads/{job['id']}").raise_for_status().json()
            shown = (job["status"], round(job["progress"] * 10))
            if shown != last:
                print(f"{job['status']} {job['progress']:.0%}", end=" | ", flush=True)
                last = shown
        print()
        if job["status"] != "done":
            print(f"   Download {job['status']}: {job['error']}")
            return 1

        track = c.get(f"/api/library/tracks/{job['track_id']}").raise_for_status().json()
        print(f"6. In library: track {track['id']}: {track['artist']} — {track['title']} "
              f"({track['album']}, {track['year']}), {track['suffix']} {track['bitrate_kbps']} kbps")
        audio = c.get(track["stream_url"]).raise_for_status()
        seek = c.get(track["stream_url"], headers={"Range": "bytes=100000-199999"})
        print(f"7. Played: streamed {len(audio.content):,} bytes ({audio.headers['content-type']}), "
              f"seek -> HTTP {seek.status_code} {len(seek.content):,} bytes")
        print("PASS: discovered, requested, watched progress, played from the library.")
        return 0
    finally:
        c.delete(f"/api/auth/device-token/{login['device_id']}")  # sign this test device out


if __name__ == "__main__":
    sys.exit(main())
