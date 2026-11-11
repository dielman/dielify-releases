// Ride numbers as text (km or miles by the Edge's own setting). "--" when there's no value.
import Toybox.Lang;
import Toybox.System;

module Fmt {
    function metric() as Boolean {
        return System.getDeviceSettings().distanceUnits == System.UNIT_METRIC;
    }

    function speed(mps as Float or Null, metricUnits as Boolean) as String {
        if (mps == null) { return "--"; }
        return (mps * (metricUnits ? 3.6 : 2.23694)).format("%.1f");
    }

    function distance(m as Float or Null, metricUnits as Boolean) as String {
        if (m == null) { return "--"; }
        return (m / (metricUnits ? 1000.0 : 1609.344)).format("%.2f");
    }

    function duration(ms as Number or Null) as String {
        if (ms == null) { return "--"; }
        var s = ms / 1000;
        var h = s / 3600;
        var m = (s % 3600) / 60;
        var sec = s % 60;
        if (h > 0) { return h.format("%d") + ":" + m.format("%02d") + ":" + sec.format("%02d"); }
        return m.format("%d") + ":" + sec.format("%02d");
    }

    function whole(n as Number or Float or Null) as String {
        if (n == null) { return "--"; }
        return n.toNumber().format("%d");
    }
}
