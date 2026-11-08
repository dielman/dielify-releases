package com.dielify.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.Smartphone
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material3.Card
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.dielify
import com.dielify.app.net.RemoteCommand
import com.dielify.app.net.RemoteDevice
import kotlinx.coroutines.delay

/** Your other devices (the PC app, other phones): control them or move the music. */
@Composable
fun DevicesScreen(vm: AppViewModel) {
    val remote = androidx.compose.ui.platform.LocalContext.current.dielify.remote
    val devices by remote.devices.collectAsStateWithLifecycle()
    val connected by remote.connected.collectAsStateWithLifecycle()
    val error by remote.errors.collectAsStateWithLifecycle()
    val p by vm.player.collectAsStateWithLifecycle()
    LaunchedEffect(error) { error?.let { vm.messages.tryEmit(it); remote.clearError() } }
    Page(vm, "Devices") { pad ->
        Column(
            Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            when {
                !connected -> Text("Connecting to your PC…", color = MaterialTheme.colorScheme.onSurfaceVariant)
                devices.isEmpty() -> Text(
                    "No other devices right now. The PC shows up while Dielify runs on it; other phones while " +
                        "Dielify is open or playing on them.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            devices.forEach { d -> DeviceCard(vm, d, canSend = p.hasItem) }
        }
    }
}

@Composable
private fun DeviceCard(vm: AppViewModel, d: RemoteDevice, canSend: Boolean) {
    val remote = androidx.compose.ui.platform.LocalContext.current.dielify.remote
    val st = d.state
    val song = st?.song
    fun cmd(c: RemoteCommand) = remote.command(d.device, c)
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(if (d.kind == "pc") Icons.Filled.Computer else Icons.Filled.Smartphone, null)
                Text(d.name, style = MaterialTheme.typography.titleMedium)
            }
            Text(
                if (song == null) "Not playing"
                else "${if (st.playing) "Playing" else "Paused"}: ${song.title}" + (song.artist?.let { " · $it" } ?: ""),
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (song != null) {
                // position moves on by itself while playing; the list only says where it was
                var now by remember { mutableLongStateOf(android.os.SystemClock.elapsedRealtime()) }
                LaunchedEffect(st) { while (true) { now = android.os.SystemClock.elapsedRealtime(); delay(1000) } }
                val duration = st.durationMs ?: 0
                val pos = (st.positionMs + if (st.playing) now - remote.listedAt else 0).coerceIn(0, duration.coerceAtLeast(0))
                var drag by remember { mutableStateOf<Float?>(null) }
                if (duration > 0) Slider(
                    value = drag ?: (pos.toFloat() / duration),
                    onValueChange = { drag = it },
                    onValueChangeFinished = { drag?.let { cmd(RemoteCommand("seek", positionMs = (it * duration).toLong())) }; drag = null },
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = { cmd(RemoteCommand("previous")) }) { Icon(Icons.Filled.SkipPrevious, "Previous") }
                    IconButton(onClick = { cmd(RemoteCommand(if (st.playing) "pause" else "play")) }) {
                        Icon(if (st.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (st.playing) "Pause" else "Play")
                    }
                    IconButton(onClick = { cmd(RemoteCommand("next")) }) { Icon(Icons.Filled.SkipNext, "Next") }
                }
                var vol by remember(st.volume) { mutableStateOf(st.volume) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.AutoMirrored.Filled.VolumeUp, "Volume")
                    Slider(value = vol, onValueChange = { vol = it }, onValueChangeFinished = { cmd(RemoteCommand("volume", value = vol)) },
                        modifier = Modifier.padding(start = 8.dp))
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (song != null) FilledTonalButton(onClick = { remote.transfer(d.device, remote.deviceId) }) { Text("Play it here") }
                if (canSend) OutlinedButton(onClick = {
                    remote.transfer(remote.deviceId, d.device)
                    vm.messages.tryEmit("Moving the music to ${d.name}…")
                }) { Text("Move my music there") }
            }
        }
    }
}
