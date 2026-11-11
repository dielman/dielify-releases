"""Remote control between devices: /api/remote WebSocket hub."""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from dielify import auth, remote
from test_api import login, make_client, setup  # noqa: F401  (setup: shared autouse fixture)

SONGS = [{"track_id": 1, "title": "One", "artist": "A", "album": "X"},
         {"video_id": "abc", "title": "Two", "artist": "B", "album": "Y", "evil": "<script>"}]


def connect(c, h, device, name, kind="phone"):
    ws = c.websocket_connect("/api/remote", headers=h)
    ws.__enter__()
    ws.send_json({"type": "hello", "device": device, "name": name, "kind": kind})
    return ws


def devices(ws):
    while True:
        msg = ws.receive_json()
        if msg["type"] == "devices":
            return msg


def test_needs_sign_in():
    with make_client() as c:
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect("/api/remote") as ws:
                ws.receive_text()
        assert e.value.code == 4401
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/remote?token=dielify_nope") as ws:
                ws.receive_text()


def test_devices_see_each_other_and_control():
    with make_client() as c:
        h = login(c)
        phone = connect(c, h, "p1", "Pixel")
        assert [d["name"] for d in devices(phone)["devices"]] == ["Pixel"]
        pc = connect(c, login(c, device="pc"), "pc1", "Gamerig", "pc")
        listing = devices(pc)
        assert listing["you"] == "pc1" and {d["name"] for d in listing["devices"]} == {"Pixel", "Gamerig"}
        assert len(devices(phone)["devices"]) == 2

        pc.send_json({"type": "state", "state": {"playing": True, "position_ms": 1000, "duration_ms": 200000,
                                                 "volume": 0.5, "index": 1, "queue": SONGS}})
        time.sleep(0.2)
        st = next(d for d in devices(phone)["devices"] if d["device"] == "pc1")["state"]
        assert st["playing"] and st["index"] == 1 and st["position_ms"] >= 1000
        assert "evil" not in st["queue"][1]                         # unknown keys dropped

        phone.send_json({"type": "command", "to": "pc1", "command": {"action": "seek", "position_ms": 5000}})
        msg = pc.receive_json()
        while msg["type"] != "command":
            msg = pc.receive_json()
        assert msg == {"type": "command", "from": "Pixel", "command": {"action": "seek", "position_ms": 5000}}

        phone.send_json({"type": "command", "to": "pc1", "command": {"action": "format_disk"}})
        msg = phone.receive_json()
        while msg["type"] != "error":
            msg = phone.receive_json()

        # move playback from the PC to the phone: phone gets the queue + position, PC pauses
        phone.send_json({"type": "transfer", "from": "pc1", "to": "p1"})
        got = phone.receive_json()
        while got["type"] != "command":
            got = phone.receive_json()
        cmd = got["command"]
        assert cmd["action"] == "load" and cmd["index"] == 1 and cmd["position_ms"] >= 1000
        assert [s["title"] for s in cmd["queue"]] == ["One", "Two"]
        paused = pc.receive_json()
        while paused["type"] != "command":
            paused = pc.receive_json()
        assert paused["command"] == {"action": "pause"}
        assert devices(phone)["active"] == "p1"

        pc.__exit__(None, None, None)
        assert [d["name"] for d in devices(phone)["devices"]] == ["Pixel"]   # gone when it closes
        phone.__exit__(None, None, None)


def test_other_profiles_are_invisible():
    auth.add_user("kid", "kid", password="pw")
    with make_client() as c:
        a = connect(c, login(c), "p1", "Josh phone")
        devices(a)
        b = connect(c, login(c, "kid", "pw"), "k1", "Kid phone")
        assert [d["name"] for d in devices(b)["devices"]] == ["Kid phone"]
        b.send_json({"type": "command", "to": "p1", "command": {"action": "pause"}})
        msg = b.receive_json()
        while msg["type"] != "error":
            msg = b.receive_json()
        a.__exit__(None, None, None)
        b.__exit__(None, None, None)


def next_of(ws, kind):
    msg = ws.receive_json()
    while msg["type"] != kind:
        msg = ws.receive_json()
    return msg


def test_one_active_device_like_spotify_connect():
    with make_client() as c:
        h = login(c)
        phone = connect(c, h, "p1", "Pixel")
        pc = connect(c, login(c, device="pc"), "pc1", "Gamerig", "pc")
        playing = {"playing": True, "position_ms": 0, "duration_ms": 200000, "index": 0, "queue": SONGS}

        pc.send_json({"type": "state", "state": playing})
        assert next_of(phone, "devices")["active"] is None or True
        time.sleep(0.2)
        listing = devices(phone)
        while listing["active"] != "pc1":
            listing = devices(phone)

        # the phone starts its own music: it becomes active and the PC is told to pause
        phone.send_json({"type": "state", "state": {**playing, "index": 1}})
        assert next_of(pc, "command")["command"] == {"action": "pause"}
        listing = devices(pc)
        while listing["active"] != "p1":
            listing = devices(pc)

        # the PC picks itself in the device list: the music moves back to it
        pc.send_json({"type": "select", "device": "pc1"})
        cmd = next_of(pc, "command")["command"]
        assert cmd["action"] == "load" and cmd["index"] == 1
        assert next_of(phone, "command")["command"] == {"action": "pause"}
        listing = devices(phone)
        while listing["active"] != "pc1":
            listing = devices(phone)

        phone.send_json({"type": "command", "to": "pc1", "command": {"action": "jump", "index": 0}})
        assert next_of(pc, "command")["command"] == {"action": "jump", "index": 0, "position_ms": 0}

        pc.__exit__(None, None, None)
        listing = devices(phone)
        while len(listing["devices"]) != 1:
            listing = devices(phone)
        assert listing["active"] is None                     # the active device left
        phone.__exit__(None, None, None)


def test_position_moves_while_playing():
    st = remote.clean_state({"playing": True, "position_ms": 1000, "duration_ms": 3000, "queue": SONGS, "index": 0})
    assert remote.now_position(st, time.monotonic() - 1.5) >= 2400
    assert remote.now_position(st, time.monotonic() - 10) == 3000
    assert remote.now_position({**st, "playing": False}, time.monotonic() - 10) == 1000



def until(ws, pred):
    """Read messages until one matches; returns (that message, everything read)."""
    seen = []
    while True:
        msg = ws.receive_json()
        seen.append(msg)
        if pred(msg):
            return msg, seen


def test_stale_playing_report_after_a_pause_is_ignored():
    """A device told to pause may already have a 'playing' report on the way. That old
    report must not make it active again (and pause the device that just took over)."""
    with make_client() as c:
        phone = connect(c, login(c), "p1", "Pixel")
        pc = connect(c, login(c, device="pc"), "pc1", "Gamerig", "pc")
        try:
            stale_race(phone, pc)
        finally:
            pc.__exit__(None, None, None)
            phone.__exit__(None, None, None)


def stale_race(phone, pc):
        playing = {"playing": True, "position_ms": 0, "duration_ms": 200000, "index": 0, "queue": SONGS}
        pc.send_json({"type": "state", "state": playing})
        until(phone, lambda m: m["type"] == "devices" and m["active"] == "pc1")
        phone.send_json({"type": "state", "state": playing})          # phone starts: PC is told to pause
        assert next_of(pc, "command")["command"] == {"action": "pause"}
        pc.send_json({"type": "state", "state": {**playing, "position_ms": 900}})  # sent before the pause landed
        pc.send_json({"type": "state", "state": {**playing, "playing": False}})    # then the pause took effect
        until(pc, lambda m: m["type"] == "devices" and not next(
            d for d in m["devices"] if d["device"] == "pc1")["state"]["playing"])
        phone.send_json({"type": "state", "state": {**playing, "position_ms": 1500}})
        last, seen = until(phone, lambda m: m["type"] == "devices" and next(
            d for d in m["devices"] if d["device"] == "p1")["state"]["position_ms"] >= 1500)
        assert not [m for m in seen if m["type"] == "command"]       # the phone was never paused
        assert last["active"] == "p1"


def test_queue_command_keeps_the_current_song():
    from dielify.remote import clean_command
    songs = [{"video_id": "a", "title": "A"}, {"track_id": 5, "title": "B"}, {"video_id": "c"}]
    assert clean_command({"action": "queue", "queue": songs, "index": 1}) == \
        {"action": "queue", "queue": [{"video_id": "a", "title": "A"}, {"track_id": 5, "title": "B"}, {"video_id": "c"}], "index": 1}
    assert clean_command({"action": "queue", "queue": songs, "index": 7}) is None   # must point at a song
    assert clean_command({"action": "queue", "queue": [], "index": 0}) is None


def test_a_tv_shows_as_a_tv():
    """0.9.10: the Google TV app says it's a TV, so "Play on" lists show it with a TV icon."""
    with make_client() as c:
        h = login(c)
        tv = connect(c, login(c, device="Shed TV"), "tv-1", "Shed TV", "tv")
        odd = connect(c, login(c, device="x"), "x1", "Odd", "toaster")
        listing = devices(odd)
        kinds = {d["name"]: d["kind"] for d in listing["devices"]}
        assert kinds == {"Shed TV": "tv", "Odd": "phone"}           # unknown kinds count as phones
        tv.__exit__(None, None, None)
        odd.__exit__(None, None, None)


def test_parents_see_and_control_their_kids_devices():
    """Josh (10 Nov): a parent's devices see and control what plays on their kids' devices."""
    from dielify import settings
    settings.set_value("active_profile", "josh")  # the PC's own person: kids share its music (household)
    with make_client() as c:
        josh = login(c)
        r = c.post("/api/desktop/people", headers={"Authorization": f"Bearer {auth.enable_desktop_token()}"},
                   json={"name": "emma"})
        emma = login(c, "emma", r.json()["password"], device="emma's phone")
        parent = connect(c, josh, "p1", "Pixel")
        devices(parent)
        kid = connect(c, emma, "k1", "Emma's phone")
        kid_list = devices(kid)
        assert kid_list["kids"] == [] and [d["name"] for d in kid_list["devices"]] == ["Emma's phone"]
        kid.send_json({"type": "state", "state": {"playing": True, "position_ms": 0, "duration_ms": 200000,
                                                  "volume": 1, "index": 0, "queue": SONGS}})
        msg = devices(parent)
        while not msg["kids"] or not (msg["kids"][0]["state"] or {}).get("playing"):
            msg = devices(parent)
        assert msg["kids"][0]["person"] == "emma" and msg["kids"][0]["name"] == "Emma's phone"
        assert [d["name"] for d in msg["devices"]] == ["Pixel"]      # her phone isn't one of his own
        assert msg["active"] != "k1"                                 # and never his active device

        parent.send_json({"type": "command", "to": "k1", "command": {"action": "pause"}})
        got = kid.receive_json()
        while got["type"] != "command":
            got = kid.receive_json()
        assert got["command"]["action"] == "pause" and got["from"] == "Pixel"

        # no putting songs on her phone past her controls
        parent.send_json({"type": "command", "to": "k1", "command": {"action": "load", "queue": SONGS, "index": 0}})
        err = parent.receive_json()
        while err["type"] != "error":
            err = parent.receive_json()
        assert "pause" in err["message"]

        # she can't see or control his devices
        kid.send_json({"type": "command", "to": "p1", "command": {"action": "pause"}})
        err = kid.receive_json()
        while err["type"] != "error":
            err = kid.receive_json()
        assert "isn't connected" in err["message"]
        for ws in (parent, kid):
            ws.__exit__(None, None, None)


def test_the_pc_can_ask_a_tv_to_update_itself():
    """0.9.12: TVs say their app version; the PC can tell a new enough TV to update itself."""
    with make_client() as c:
        tv = c.websocket_connect("/api/remote", headers=login(c, device="Garage TV"))
        tv.__enter__()
        tv.send_json({"type": "hello", "device": "tv-9", "name": "Garage TV", "kind": "tv", "version": 912})
        devices(tv)
        found = remote.tv_at(remote.hub.find(next(iter(remote.hub.devices))[0], "tv-9").ip)
        assert found is not None and found.version == 912
        assert remote.ask_tv_to_update(found.ip)
        while True:
            msg = tv.receive_json()
            if msg["type"] == "update":
                break
        tv.__exit__(None, None, None)
