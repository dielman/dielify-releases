// Dielify on the Edge: what's playing on the phone, the music buttons, and the ride's numbers
// on one screen. The phone side is the Dielify Android app (Garmin's companion SDK): it sends
// {"t" title, "a" artist, "p" playing} and takes {"cmd" "hello"|"play"|"pause"|"next"|"prev"}.
// Garmin Connect only carries the messages.
import Toybox.Application;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.WatchUi;

class DielifyApp extends Application.AppBase {
    var song as Dictionary? = null;   // the last "now playing" from the phone
    var lastCmd as String? = null;    // the last button sent
    var link as String = "waiting";   // "ok" | "no phone" | "waiting"

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
        if (Communications has :registerForPhoneAppMessages) {
            Communications.registerForPhoneAppMessages(method(:onPhone));
        }
        // The phone app sends "now playing" whenever it changes, so nothing is sent at start-up
        // (the simulator also stops with an error box when there's no phone to send to).
    }

    function getInitialView() as [WatchUi.Views] or [WatchUi.Views, WatchUi.InputDelegates] {
        return [new RideView(self), new RideDelegate(self)];
    }

    function onPhone(msg as Communications.PhoneAppMessage) as Void {
        var d = msg.data;
        if (d instanceof Dictionary) {
            song = d;
            link = "ok";
            WatchUi.requestUpdate();
        }
    }

    function send(cmd as String) as Void {
        lastCmd = cmd;
        Communications.transmit({"cmd" => cmd}, null, new SendListener(self));
        WatchUi.requestUpdate();
    }
}

class SendListener extends Communications.ConnectionListener {
    private var _app as DielifyApp;

    function initialize(app as DielifyApp) {
        ConnectionListener.initialize();
        _app = app;
    }

    function onComplete() as Void {
        _app.link = "ok";
        WatchUi.requestUpdate();
    }

    function onError() as Void {
        _app.link = "no phone";
        WatchUi.requestUpdate();
    }
}
