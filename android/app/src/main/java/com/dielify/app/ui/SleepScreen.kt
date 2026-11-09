package com.dielify.app.ui

import kotlin.math.roundToInt
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.dielify
import kotlinx.coroutines.delay

/** Moon button on Now playing: pause after 15 / 30 / 45 / 60 minutes or at the end of the song. */
@Composable
fun SleepButton(vm: AppViewModel) {
    val timer = LocalContext.current.dielify.sleep
    val s by timer.state.collectAsStateWithLifecycle()
    var menu by remember { mutableStateOf(false) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(s.endsAt) { while (s.endsAt > 0) { now = System.currentTimeMillis(); delay(15_000) } }
    val label = when {
        s.songEnd -> "Stops at the end of this song"
        s.endsAt > 0 -> "Pauses in ${maxOf(1, ((s.endsAt - now + 59_999) / 60_000).toInt())} min"
        else -> null
    }
    Box {
        IconButton(onClick = { menu = true }) {
            Icon(Icons.Filled.Bedtime, label ?: "Sleep timer",
                tint = if (s.on) ConnectGreen else MaterialTheme.colorScheme.onSurfaceVariant)
        }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            Text(label ?: "Sleep timer", Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            listOf(15, 30, 45, 60).forEach { m ->
                DropdownMenuItem(text = { Text(if (m == 60) "1 hour" else "$m minutes") }, onClick = {
                    menu = false; timer.minutes(m); vm.messages.tryEmit("Sleep timer: pauses in ${if (m == 60) "1 hour" else "$m minutes"}")
                })
            }
            DropdownMenuItem(text = { Text("End of this song") }, onClick = {
                menu = false; vm.sleepAtSongEnd()
            })
            if (s.on) DropdownMenuItem(text = { Text("Turn off") }, onClick = {
                menu = false; timer.off(); vm.messages.tryEmit("Sleep timer off")
            })
        }
    }
}

/** Settings: "Even out volume" (levelling, leveller.py on the PC). */
@Composable
fun LevelSetting() {
    val prefs = LocalContext.current.dielify.levelPrefs
    var on by remember { mutableStateOf(prefs.getBoolean("level", true)) }
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Even out volume", Modifier.weight(1f))
            Switch(checked = on, onCheckedChange = { on = it; prefs.edit().putBoolean("level", it).apply() })
        }
        Text("Loud songs are turned down to match the rest (from the next song on). Works for songs in your library.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}


/** Settings: the equaliser on this phone (preset + bass + treble; same presets as the PC). */
@Composable
fun EqSetting() {
    val prefs = LocalContext.current.dielify.levelPrefs
    val presets = com.dielify.app.playback.SoundEq.PRESETS
    var preset by remember { mutableStateOf(prefs.getString(com.dielify.app.playback.SoundEq.KEY_PRESET, "flat") ?: "flat") }
    var bass by remember { mutableStateOf(prefs.getInt(com.dielify.app.playback.SoundEq.KEY_BASS, 0).toFloat()) }
    var treble by remember { mutableStateOf(prefs.getInt(com.dielify.app.playback.SoundEq.KEY_TREBLE, 0).toFloat()) }
    Column {
        Text("Equaliser", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        androidx.compose.foundation.layout.FlowRow(horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(6.dp)) {
            presets.forEach { (key, v) ->
                androidx.compose.material3.FilterChip(selected = preset == key, onClick = {
                    preset = key
                    prefs.edit().putString(com.dielify.app.playback.SoundEq.KEY_PRESET, key).apply()
                }, label = { Text(v.first) })
            }
        }
        @Composable
        fun slider(label: String, value: Float, key: String, set: (Float) -> Unit) = Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, Modifier.width(64.dp))
            Box(Modifier.weight(1f)) {
                ThinSeek(value = (value + 12f) / 24f, enabled = true, onChange = { v ->
                    val db = (v * 24f - 12f).roundToInt()
                    if (db.toFloat() != value) { set(db.toFloat()); prefs.edit().putInt(key, db).apply() }  // heard at once
                }, onDone = {})
            }
            Text("${if (value > 0) "+" else ""}${value.roundToInt()} dB", Modifier.width(56.dp),
                style = MaterialTheme.typography.bodySmall)
        }
        slider("Bass", bass, com.dielify.app.playback.SoundEq.KEY_BASS) { bass = it }
        slider("Treble", treble, com.dielify.app.playback.SoundEq.KEY_TREBLE) { treble = it }
        Text("On this phone only. Changes are heard straight away.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
