package com.dielify.app.playback

import android.content.SharedPreferences
import android.media.audiofx.Equalizer
import android.util.Log
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * The phone's equaliser: a preset plus bass and treble (the same presets as the PC app),
 * on Android's own equaliser for the player's audio session. Kept in the "playback" prefs
 * (eq_preset, eq_bass, eq_treble), so it's set per device. Flat = the equaliser is off.
 *
 * Phones have their own band layout (usually 5 bands), so the preset is drawn as a curve
 * over our 5 frequencies and read off at each of the phone's bands. Everything is shifted
 * down by the biggest boost, so a boosted song can't distort.
 */
class SoundEq(private val prefs: SharedPreferences) {
    private var eq: Equalizer? = null

    fun attach(sessionId: Int) {
        release()
        if (sessionId <= 0) return
        eq = runCatching { Equalizer(0, sessionId) }.onFailure { Log.w("Dielify", "No equaliser: $it") }.getOrNull()
        apply()
    }

    fun release() {
        runCatching { eq?.release() }
        eq = null
    }

    fun apply() {
        val e = eq ?: return
        val preset = PRESETS[prefs.getString(KEY_PRESET, "flat")] ?: PRESETS.getValue("flat")
        val bass = prefs.getInt(KEY_BASS, 0)
        val treble = prefs.getInt(KEY_TREBLE, 0)
        runCatching {
            if (preset.second.all { it == 0 } && bass == 0 && treble == 0) {
                e.enabled = false
                return
            }
            val n = e.numberOfBands.toInt()
            val gains = DoubleArray(n) { i -> gainAt(e.getCenterFreq(i.toShort()) / 1000.0, preset.second, bass, treble) }
            val shift = max(0.0, gains.maxOrNull() ?: 0.0)
            val (lo, hi) = e.bandLevelRange.let { it[0].toInt() to it[1].toInt() }
            for (i in 0 until n) {
                val mb = ((gains[i] - shift) * 100).roundToInt().coerceIn(lo, hi)
                e.setBandLevel(i.toShort(), mb.toShort())
            }
            e.enabled = true
        }.onFailure { Log.w("Dielify", "Equaliser not applied: $it") }
    }

    companion object {
        const val KEY_PRESET = "eq_preset"
        const val KEY_BASS = "eq_bass"
        const val KEY_TREBLE = "eq_treble"
        private val BANDS = doubleArrayOf(60.0, 230.0, 910.0, 3600.0, 14000.0)

        /** Same as the PC app (app.js EQ_PRESETS): name to (label, dB at 60/230/910/3600/14000 Hz). */
        val PRESETS: LinkedHashMap<String, Pair<String, IntArray>> = linkedMapOf(
            "flat" to ("Flat" to intArrayOf(0, 0, 0, 0, 0)),
            "bass" to ("Bass boost" to intArrayOf(6, 4, 1, 0, 0)),
            "treble" to ("Treble boost" to intArrayOf(0, 0, 0, 3, 6)),
            "vocal" to ("Vocal" to intArrayOf(-2, -1, 4, 3, 0)),
            "rock" to ("Rock" to intArrayOf(4, 2, -2, 2, 4)),
            "pop" to ("Pop" to intArrayOf(-1, 2, 4, 2, -1)),
            "hiphop" to ("Hip-hop" to intArrayOf(5, 3, 0, 1, 2)),
            "electronic" to ("Electronic" to intArrayOf(4, 2, 0, 2, 4)),
            "jazz" to ("Jazz" to intArrayOf(3, 1, -1, 1, 3)),
            "classical" to ("Classical" to intArrayOf(3, 2, -1, 2, 3)),
            "acoustic" to ("Acoustic" to intArrayOf(2, 1, 1, 2, 2)),
            "late" to ("Late night (quieter bass)" to intArrayOf(-4, -2, 0, 0, -1)),
        )

        /** dB at frequency hz: the preset's curve (straight lines on a log scale) + bass + treble. */
        fun gainAt(hz: Double, preset: IntArray, bass: Int, treble: Int): Double {
            val x = log10(hz.coerceIn(BANDS.first(), BANDS.last()))
            var g = preset.last().toDouble()
            for (i in 0 until BANDS.size - 1) {
                val a = log10(BANDS[i])
                val b = log10(BANDS[i + 1])
                if (x <= b) {
                    g = preset[i] + (preset[i + 1] - preset[i]) * ((x - a) / (b - a))
                    break
                }
            }
            val bassPart = when { hz <= 150 -> 1.0; hz <= 400 -> 0.5; else -> 0.0 }
            val treblePart = when { hz >= 6000 -> 1.0; hz >= 2500 -> 0.5; else -> 0.0 }
            return g + bass * bassPart + treble * treblePart
        }
    }
}
