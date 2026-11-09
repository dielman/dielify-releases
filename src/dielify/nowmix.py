"""Time-of-day mix: songs from your library that you tend to play at this time of day.

Every counted play in the last 180 days scores its song by how close its hour is to now
(same hour 1, an hour off 0.5, two hours off 0.25), with a bonus when it was the same kind
of day (weekday / weekend). A weighted sample of the best-scoring songs makes the mix; it
stays the same within one part of the day (morning, afternoon, evening, late night) and
changes in the next. Banned songs and songs left out of your taste are never in it.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime

from .library import Library, connect
from .ratings import Ratings
from .taste import Taste

SIZE = 40
MIN_SONGS = 15
DAYS = 180

PARTS = [(5, "morning"), (12, "afternoon"), (17, "evening"), (22, "late night")]


@dataclass
class NowMix:
    title: str
    description: str
    track_ids: list[int]


def part_of_day(hour: int) -> str:
    name = PARTS[-1][1]
    for start, label in PARTS:
        if hour >= start:
            name = label
    return name  # 0-4 stays "late night"


def build(lib: Library, now: datetime | None = None) -> NowMix | None:
    now = now or datetime.now()
    weekend = now.weekday() >= 5
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.track_id, p.video_id, p.artist, "
            "CAST(strftime('%H', p.started_at, 'unixepoch', 'localtime') AS INTEGER) h, "
            "CAST(strftime('%w', p.started_at, 'unixepoch', 'localtime') AS INTEGER) dow "
            "FROM plays p JOIN library_items li ON li.track_id = p.track_id AND li.profile = p.profile "
            "WHERE p.profile = ? AND p.counted = 1 AND p.started_at >= ?",
            (lib.profile, time.time() - DAYS * 86400)).fetchall()
    taste, ratings = Taste(lib.profile), Ratings(lib.profile)
    score: dict[int, float] = {}
    for r in rows:
        d = abs(r["h"] - now.hour)
        d = min(d, 24 - d)
        if d > 2 or taste.out(r["video_id"], r["track_id"]):
            continue
        w = 0.5 ** d
        if (r["dow"] in (0, 6)) == weekend:
            w *= 1.5
        score[r["track_id"]] = score.get(r["track_id"], 0.0) + w
    ok = {}
    for tid, s in score.items():
        t = lib.track(tid)
        if t is None:
            continue
        f = ratings.factor(t["video_id"], t["artist"], tid)
        if f > 0:
            ok[tid] = s * f
    if len(ok) < MIN_SONGS:
        return None
    part = part_of_day(now.hour)
    rnd = random.Random(f"{lib.profile}:{now:%Y-%m-%d}:{part}")
    keyed = sorted(ok, key=lambda tid: -(rnd.random() ** (1.0 / ok[tid])))
    day = "weekend" if weekend else now.strftime("%A")
    return NowMix(title=f"Your {day} {part}",
                  description=f"What you usually play on a {'weekend' if weekend else 'weekday'} {part}",
                  track_ids=keyed[:SIZE])
