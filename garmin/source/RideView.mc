// The screen: song + artist on top, six ride numbers below (from the Edge's own recording via
// Activity.getActivityInfo()), the button hints at the bottom. Redrawn every second.
import Toybox.Activity;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Timer;
import Toybox.WatchUi;

class RideView extends WatchUi.View {
    private var _app as DielifyApp;
    private var _timer as Timer.Timer?;

    function initialize(app as DielifyApp) {
        View.initialize();
        _app = app;
    }

    function onShow() as Void {
        _timer = new Timer.Timer();
        _timer.start(method(:tick), 1000, true);
    }

    function onHide() as Void {
        if (_timer != null) { _timer.stop(); }
    }

    function tick() as Void {
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        // what's playing
        var title = "Nothing playing";
        var artist = _app.link.equals("no phone") ? "Phone not connected" : "Open Dielify on the phone";
        var playing = false;
        var s = _app.song;
        if (s != null) {
            title = s.hasKey("t") ? s["t"].toString() : title;
            artist = s.hasKey("a") ? s["a"].toString() : "";
            playing = s.hasKey("p") && s["p"] == true;
        }
        dc.setColor(0xFF7A45, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(0, 0, w, 4);
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, 8, Graphics.FONT_SMALL, fit(dc, title, Graphics.FONT_SMALL, w - 8), Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, 34, Graphics.FONT_XTINY, fit(dc, artist, Graphics.FONT_XTINY, w - 8), Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(playing ? 0x55FF55 : Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, 54, Graphics.FONT_XTINY, playing ? "PLAYING" : "PAUSED", Graphics.TEXT_JUSTIFY_CENTER);

        // ride numbers
        var info = Activity.getActivityInfo();
        var metric = Fmt.metric();
        var cells = [
            ["SPEED", info != null ? Fmt.speed(info.currentSpeed, metric) : "--", metric ? "km/h" : "mph"],
            ["DIST", info != null ? Fmt.distance(info.elapsedDistance, metric) : "--", metric ? "km" : "mi"],
            ["TIME", info != null ? Fmt.duration(info.timerTime) : "--", ""],
            ["HR", info != null ? Fmt.whole(info.currentHeartRate) : "--", "bpm"],
            ["CAD", info != null ? Fmt.whole(info.currentCadence) : "--", "rpm"],
            ["POWER", info != null ? Fmt.whole(info.currentPower) : "--", "W"]
        ];
        var top = 76;
        var bottom = h - 34;
        var rowH = (bottom - top) / 3;
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(w / 2, top, w / 2, bottom);
        for (var r = 0; r <= 3; r++) {
            dc.drawLine(0, top + r * rowH, w, top + r * rowH);
        }
        for (var i = 0; i < cells.size(); i++) {
            var x = (i % 2) * (w / 2) + w / 4;
            var y = top + (i / 2) * rowH;
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(x, y + 2, Graphics.FONT_XTINY, cells[i][0] + " " + cells[i][2], Graphics.TEXT_JUSTIFY_CENTER);
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(x, y + 18, Graphics.FONT_NUMBER_MILD, cells[i][1], Graphics.TEXT_JUSTIFY_CENTER);
        }

        // buttons
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        var sent = _app.lastCmd != null ? ("sent: " + _app.lastCmd + " (" + _app.link + ")") : "UP prev  DOWN next  OK play";
        dc.drawText(w / 2, h - 26, Graphics.FONT_XTINY, sent, Graphics.TEXT_JUSTIFY_CENTER);
    }

    // shorten text to fit the width, with "..."
    private function fit(dc as Graphics.Dc, text as String, font as Graphics.FontType, width as Number) as String {
        if (dc.getTextWidthInPixels(text, font) <= width) { return text; }
        var t = text;
        while (t.length() > 1 && dc.getTextWidthInPixels(t + "...", font) > width) {
            t = t.substring(0, t.length() - 1) as String;
        }
        return t + "...";
    }
}
