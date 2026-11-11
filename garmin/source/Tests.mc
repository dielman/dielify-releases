// Unit tests (run in the simulator: monkeydo <prg> edge530 /t).
import Toybox.Lang;
import Toybox.Test;

(:test)
function speedInKmh(logger as Logger) as Boolean {
    return Fmt.speed(10.0, true).equals("36.0") && Fmt.speed(null, true).equals("--");
}

(:test)
function speedInMph(logger as Logger) as Boolean {
    return Fmt.speed(10.0, false).equals("22.4");
}

(:test)
function distanceInKm(logger as Logger) as Boolean {
    return Fmt.distance(12345.0, true).equals("12.35") && Fmt.distance(null, true).equals("--");
}

(:test)
function rideTime(logger as Logger) as Boolean {
    logger.debug(Fmt.duration(3723000));
    return Fmt.duration(3723000).equals("1:02:03") && Fmt.duration(65000).equals("1:05")
        && Fmt.duration(null).equals("--");
}

(:test)
function wholeNumbers(logger as Logger) as Boolean {
    return Fmt.whole(142).equals("142") && Fmt.whole(87.6).equals("87") && Fmt.whole(null).equals("--");
}
