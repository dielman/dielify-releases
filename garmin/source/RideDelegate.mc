// Buttons: up = previous song, down = next, select = play/pause, back = leave (the ride keeps
// recording). Every key is also logged (simulator console) so the Edge 530's mapping can be checked.
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

class RideDelegate extends WatchUi.BehaviorDelegate {
    private var _app as DielifyApp;

    function initialize(app as DielifyApp) {
        BehaviorDelegate.initialize();
        _app = app;
    }

    function onKey(evt as WatchUi.KeyEvent) as Boolean {
        System.println("key " + evt.getKey() + " type " + evt.getType());
        return BehaviorDelegate.onKey(evt);
    }

    function onSelect() as Boolean {
        var s = _app.song;
        var playing = s != null && s.hasKey("p") && s["p"] == true;
        _app.send(playing ? "pause" : "play");
        return true;
    }

    function onNextPage() as Boolean {
        _app.send("next");
        return true;
    }

    function onPreviousPage() as Boolean {
        _app.send("prev");
        return true;
    }
}
