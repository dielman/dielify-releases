"""Notifications: things the household should know about, shown in the PC app's and phones'
Notifications section (Josh, 21 Nov 2026). First use: YouTube Music Premium lapsing (premium.py).

A notice belongs to one music store (a household) and is shown to its parents (parents_only) or to
everyone in it. "warning" notices stay while the problem lasts (the code that posted them removes
them); "info" notices can be dismissed. Reading them clears the unread badge."""

from __future__ import annotations

import time

from .library import connect, person, signin_of

WARNING, INFO = "warning", "info"


def post(key: str, store: str, title: str, body: str, level: str = WARNING, parents_only: bool = True) -> None:
    """Add (or renew) a notice. Renewing makes it unread again."""
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO notices (key, store, parents_only, level, title, body, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (key, store, int(parents_only), level, title, body, time.time()))
        conn.execute("DELETE FROM notices_read WHERE key = ?", (key,))


def remove(key: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM notices WHERE key = ?", (key,))
        conn.execute("DELETE FROM notices_read WHERE key = ?", (key,))


def _visible(conn, profile: str) -> list:
    store = signin_of(profile)
    parent = person(profile)["role"] == "parent"
    return conn.execute(
        "SELECT n.*, r.read_at FROM notices n LEFT JOIN notices_read r ON r.key = n.key AND r.profile = ? "
        "WHERE n.store = ? COLLATE NOCASE AND (n.parents_only = 0 OR ?) ORDER BY n.created_at DESC",
        (profile, store, int(parent))).fetchall()


def for_person(profile: str) -> list[dict]:
    with connect() as conn:
        return [{"key": r["key"], "level": r["level"], "title": r["title"], "body": r["body"],
                 "created_at": r["created_at"], "read": r["read_at"] is not None,
                 "can_dismiss": r["level"] == INFO} for r in _visible(conn, profile)]


def mark_read(profile: str) -> None:
    with connect() as conn:
        for r in _visible(conn, profile):
            conn.execute("INSERT OR REPLACE INTO notices_read (profile, key, read_at) VALUES (?,?,?)",
                         (profile, r["key"], time.time()))


def dismiss(profile: str, key: str) -> bool:
    """Remove an info notice this person can see (warnings go away by themselves)."""
    with connect() as conn:
        mine = {r["key"]: r for r in _visible(conn, profile)}
        if key not in mine or mine[key]["level"] != INFO:
            return False
        conn.execute("DELETE FROM notices WHERE key = ?", (key,))
        conn.execute("DELETE FROM notices_read WHERE key = ?", (key,))
    return True
