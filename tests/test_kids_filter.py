"""0.9.3: the parent's controls and the filter a kids account's songs go through."""

from datetime import datetime

import pytest

from dielify import kids
from dielify.library import set_person
from dielify.yt_adapter import YTItem


def song(vid, title="Song", artist="Band", explicit=None):
    return YTItem("song", vid, title, [artist], explicit=explicit)


@pytest.fixture
def kid():
    set_person("josh")
    set_person("emma", "child", store="josh")
    return "emma"


class FakeSearch:
    """YouTube's song search: knows which songs are explicit, and their clean versions."""

    def __init__(self, songs):
        self.songs, self.searches = songs, 0

    def __call__(self, fn, query, kind="song", limit=6):
        assert fn == "search_items"
        self.searches += 1
        return [s for s in self.songs if s.title.lower() in query.lower()]


def test_words():
    for bad in ("Fuck You", "Motherfucker", "Bad Bitch", "Ass Like That", "shit"):
        assert kids.bad_words(bad), bad
    for fine in ("Cocktail party", "Cucumber", "Document", "Spicy food", "The Assassin", "Class", "Dickens"):
        assert not kids.bad_words(fine), fine
    assert kids.bad_words("you dweeb", ["dweeb"])


def test_explicit_songs_are_hidden_and_unmarked_ones_checked(kid):
    yt = FakeSearch([song("e1", "Rude", explicit=True), song("c1", "Rude", explicit=False),
                     song("n1", "Nice", explicit=False)])
    f = kids.KidFilter(kid, yt, lookups=5)
    # marked by YouTube: decided at once; radio songs (no mark): looked up, then remembered
    items = [song("x1", "Known clean", explicit=False), song("x2", "Known rude", explicit=True),
             song("n1", "Nice"), song("e1", "Rude")]
    assert [i.id for i in f.items(items)] == ["x1", "n1", "c1"]   # e1 -> its clean version c1
    assert kids.flags(["n1", "e1"]) == {"n1": False, "e1": True}
    # without lookups, songs never checked wait
    assert [i.id for i in kids.KidFilter(kid).items([song("zz", "Unknown")])] == []

    c = kids.load(kid)
    c.explicit, c.lyrics_check = "allow", False
    kids.save(kid, c)
    assert [i.id for i in kids.KidFilter(kid).items(items)] == ["x1", "x2", "n1", "e1"]


def test_blocked_artists_songs_titles_and_albums(kid):
    c = kids.load(kid)
    c.blocked_artists, c.blocked_songs = ["The Bad Band"], [{"id": "b2", "title": "No"}]
    c.lyrics_check = True  # the title word check (off by default)
    kids.save(kid, c)
    f = kids.KidFilter(kid)
    items = [song("b1", "Ok", "the bad band", explicit=False), song("b2", "No", explicit=False),
             song("b3", "Shit Song", explicit=False), song("b4", "Fine", explicit=False),
             YTItem("album", "MPREb_x", "Rude album", ["Band"], explicit=True),
             YTItem("album", "MPREb_y", "Nice album", ["Band"], explicit=False),
             YTItem("artist", "UCbad", "The Bad Band")]
    assert [i.id for i in f.items(items)] == ["b4", "MPREb_y"]


def test_words_in_titles(kid):
    assert not kids.Controls().lyrics_check                   # off unless a parent turns it on (Josh, 10 Nov)
    kids.save(kid, kids.Controls(lyrics_check=True))
    f = kids.KidFilter(kid)
    items = [song("l1", "La la fucking la", explicit=False), song("l2", "La la la", explicit=False)]
    assert [i.id for i in f.items(items)] == ["l2"]


def test_quiet_hours_over_midnight():
    c = kids.Controls(quiet_hours=True, quiet_from="21:00", quiet_to="07:00")
    at = lambda h, m=0: datetime(2026, 11, 9, h, m)  # noqa: E731
    assert kids.quiet_message(c, at(22)) and kids.quiet_message(c, at(6, 59))
    assert kids.quiet_message(c, at(7)) is None and kids.quiet_message(c, at(20, 59)) is None
    assert kids.quiet_message(kids.Controls(), at(23)) is None
    with pytest.raises(ValueError):
        kids.Controls.from_dict({"quiet_from": "25:00"})


def test_background_check_marks_the_household_songs(kid):
    from dielify.library import connect
    now = 1.0
    with connect() as conn:
        ar = conn.execute("INSERT INTO artists (profile, name) VALUES ('josh', 'Band')").lastrowid
        al = conn.execute("INSERT INTO albums (profile, artist_id, name, created_at) VALUES ('josh', ?, 'LP', ?)", (ar, now)).lastrowid
        for vid, title in (("h1", "Nice"), ("h2", "Rude")):
            conn.execute("INSERT INTO tracks (profile, relpath, album_id, artist_id, title, artist, suffix, size, mtime, "
                         "video_id, created_at) VALUES ('josh', ?, ?, ?, ?, 'Band', 'opus', 1, ?, ?, ?)",
                         (f"{vid}.opus", al, ar, title, now, vid, now))
    yt = FakeSearch([song("h1", "Nice", explicit=False), song("h2", "Rude", explicit=True)])
    checker = kids.Checker(lambda profile, fn, *a: yt(fn, *a))
    assert [t["video_id"] for _, t in checker.todo(10)] == ["h1", "h2"]
    assert checker.run_once() == 2 and checker.todo(10) == []
    assert kids.flags(["h1", "h2"]) == {"h1": False, "h2": True}
    c = kids.load(kid)
    c.explicit = "allow"
    kids.save(kid, c)
    with connect() as conn:
        conn.execute("DELETE FROM yt_flags")
    assert checker.todo(10) == []  # no child blocks explicit: nothing to check


def test_picks_shelf(kid):
    from dielify import kids_home
    from dielify.library import library_for
    c = kids.load(kid)
    c.picks = [vars(YTItem("album", "MPREb_ok", "Nice album", ["Band"], explicit=False)),
               vars(YTItem("album", "MPREb_no", "Rude album", ["Band"], explicit=True))]
    kids.save(kid, c)
    shelves = kids_home.shelves(library_for(kid), FakeSearch([]))
    assert [(sh.title, [i.id for i in sh.items]) for sh in shelves] == [("Picked for you", ["MPREb_ok"])]
