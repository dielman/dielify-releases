"""Leave out of my taste: songs and playlists that don't shape your recommendations.

For songs you played for someone else, or a playlist for the kids' party. They still play
and stay in your library; they just don't count when Dielify works out what you like:
For you, mixes (they're picked as if never played), the time-of-day mix, never-ending
discovery's fallback seeds and the artists watched for new releases. Stats still count them
(they did play).

A song is keyed like ratings (video id, or tr-<track id>); a playlist by its Dielify
playlist id. A left-out playlist leaves out every song in it, including songs added later.
"""

from __future__ import annotations

import time

from .library import connect

KINDS = ("song", "playlist")


def set_out(profile: str, kind: str, key: str, name: str, out: bool) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    with connect() as conn:
        if out:
            conn.execute("INSERT OR REPLACE INTO taste_out (profile, kind, key, name, added_at) VALUES (?,?,?,?,?)",
                         (profile, kind, str(key), name[:300], time.time()))
        else:
            conn.execute("DELETE FROM taste_out WHERE profile = ? AND kind = ? AND key = ?", (profile, kind, str(key)))


def listing(profile: str) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT kind, key, name, added_at FROM taste_out WHERE profile = ? ORDER BY added_at DESC", (profile,))]


class Taste:
    """What one person left out, ready to check songs against."""

    def __init__(self, profile: str):
        self.profile = profile
        self.videos: set[str] = set()
        self.tracks: set[int] = set()
        with connect() as conn:
            rows = conn.execute("SELECT kind, key FROM taste_out WHERE profile = ?", (profile,)).fetchall()
            playlists = [int(r["key"]) for r in rows if r["kind"] == "playlist" and str(r["key"]).isdigit()]
            for r in rows:
                if r["kind"] == "song":
                    self._add(r["key"])
            if playlists:
                marks = ",".join("?" * len(playlists))
                for r in conn.execute(f"SELECT video_id FROM playlist_items WHERE playlist_id IN ({marks}) "
                                      f"AND video_id IS NOT NULL", playlists):
                    self.videos.add(r["video_id"])
            if self.videos:  # library files of left-out videos
                marks = ",".join("?" * len(self.videos))
                for r in conn.execute(f"SELECT id FROM tracks WHERE video_id IN ({marks})", list(self.videos)):
                    self.tracks.add(r["id"])

    def _add(self, key: str) -> None:
        if key.startswith("tr-") and key[3:].isdigit():
            self.tracks.add(int(key[3:]))
        else:
            self.videos.add(key)

    def __bool__(self) -> bool:
        return bool(self.videos or self.tracks)

    def out(self, video_id: str | None = None, track_id: int | None = None) -> bool:
        return (video_id is not None and video_id in self.videos) or (track_id is not None and track_id in self.tracks)

    def sql(self, video_col: str = "p.video_id", track_col: str = "p.track_id") -> tuple[str, list]:
        """' AND NOT (...)' for a query over plays (empty when nothing is left out)."""
        if not self:
            return "", []
        parts, args = [], []
        if self.videos:
            parts.append(f"COALESCE({video_col}, '') IN ({','.join('?' * len(self.videos))})")
            args += list(self.videos)
        if self.tracks:
            parts.append(f"COALESCE({track_col}, -1) IN ({','.join('?' * len(self.tracks))})")
            args += list(self.tracks)
        return f" AND NOT ({' OR '.join(parts)})", args
