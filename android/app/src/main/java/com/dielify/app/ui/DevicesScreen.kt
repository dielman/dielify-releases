package com.dielify.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Smartphone
import androidx.compose.material.icons.filled.Tv
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.Speaker
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.dielify

/** Spotify green, for "this is where the music is playing". */
val ConnectGreen = Color(0xFF1DB954)

/** Speaker button for the player: opens the device list; green while music plays elsewhere. */
@Composable
fun DevicesButton(vm: AppViewModel) {
    val on by vm.playingOn.collectAsStateWithLifecycle()
    IconButton(onClick = { vm.showDevices.value = true }) {
        Icon(Icons.Filled.Speaker, "Play on another device", tint = if (on != null) ConnectGreen else MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** "Playing on Gamerig", shown with the player while another device is playing. */
@Composable
fun PlayingOnStrip(vm: AppViewModel) {
    val on by vm.playingOn.collectAsStateWithLifecycle()
    val name = on ?: return
    Row(
        Modifier.fillMaxWidth().background(ConnectGreen).clickable { vm.showDevices.value = true }
            .padding(horizontal = 16.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Filled.Speaker, null, Modifier.size(16.dp), tint = Color(0xFF04130A))
        Spacer(Modifier.width(6.dp))
        Text("Playing on $name", color = Color(0xFF04130A), style = MaterialTheme.typography.labelLarge)
    }
}

/** The device list (a bottom sheet): pick a device and the music moves there. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DevicePicker(vm: AppViewModel) {
    val open by vm.showDevices.collectAsStateWithLifecycle()
    if (!open) return
    val remote = androidx.compose.ui.platform.LocalContext.current.dielify.remote
    val devices by remote.devices.collectAsStateWithLifecycle()
    val connected by remote.connected.collectAsStateWithLifecycle()
    val playingOn by vm.playingOn.collectAsStateWithLifecycle()
    val error by remote.errors.collectAsStateWithLifecycle()
    LaunchedEffect(error) { error?.let { vm.messages.tryEmit(it); remote.clearError() } }
    val activeId = remote.elsewhere()?.device ?: remote.deviceId
    fun close() { vm.showDevices.value = false }
    ModalBottomSheet(onDismissRequest = { close() }) {
        Column(Modifier.padding(bottom = 16.dp).navigationBarsPadding()) {
            Text("Play on", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
            Row(
                Modifier.fillMaxWidth().clickable {
                    close()
                    if (activeId != remote.deviceId) remote.select(remote.deviceId)
                }.padding(horizontal = 24.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) { DeviceRow(Icons.Filled.Smartphone, "This phone", null, activeId == remote.deviceId) }
            devices.forEach { d ->
                val song = d.state?.song
                val on = d.device == activeId
                Row(
                    Modifier.fillMaxWidth().clickable {
                        close()
                        if (!on) remote.select(d.device)
                    }.padding(horizontal = 24.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    DeviceRow(
                        when (d.kind) { "pc" -> Icons.Filled.Computer; "tv" -> Icons.Filled.Tv; else -> Icons.Filled.Smartphone }, d.name,
                        when {
                            on && d.state?.playing == true -> "Playing: ${song?.title ?: ""}"
                            song != null -> "Paused: ${song.title}"
                            else -> null
                        },
                        on,
                    )
                }
            }
            KidDevices(remote)
            if (!connected) Text(
                "Connecting to your PC…", Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            ) else if (devices.isEmpty()) Text(
                "Dielify on your PC shows up here while it's running.", Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            // volume of wherever it's playing
            val c = vm.controller
            if (c != null && (playingOn != null || vm.player.value.hasItem)) {
                var vol by remember(playingOn) { mutableFloatStateOf(c.volume) }
                Row(Modifier.padding(horizontal = 24.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.AutoMirrored.Filled.VolumeUp, "Volume")
                    Slider(
                        value = vol, onValueChange = { vol = it; if (playingOn == null) c.volume = it },
                        onValueChangeFinished = { c.volume = vol },
                        modifier = Modifier.padding(start = 12.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.DeviceRow(icon: androidx.compose.ui.graphics.vector.ImageVector, name: String, detail: String?, on: Boolean) {
    val color = if (on) ConnectGreen else MaterialTheme.colorScheme.onSurface
    Icon(icon, null, tint = color)
    Spacer(Modifier.width(16.dp))
    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(name, color = color, style = MaterialTheme.typography.titleMedium)
        detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1) }
    }
    if (on) Icon(Icons.Filled.Check, "Playing here", tint = ConnectGreen)
}


/** A parent sees what plays on their kids' devices: pause / play, next song, volume (never put songs there). */
@Composable
private fun KidDevices(remote: com.dielify.app.net.RemoteClient) {
    val kids by remote.kids.collectAsStateWithLifecycle()
    kids.groupBy { it.person ?: "" }.forEach { (person, devs) ->
        Text("$person's devices", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 24.dp, end = 24.dp, top = 16.dp, bottom = 4.dp))
        devs.forEach { d ->
            val st = d.state
            val song = st?.song
            Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(when (d.kind) { "pc" -> Icons.Filled.Computer; "tv" -> Icons.Filled.Tv; else -> Icons.Filled.Smartphone }, null)
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(d.name, style = MaterialTheme.typography.titleMedium)
                    Text(if (song == null) "Nothing playing" else "${if (st.playing) "Playing" else "Paused"}: ${song.title}",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                if (song != null) {
                    androidx.compose.material3.IconButton(onClick = {
                        remote.command(d.device, com.dielify.app.net.RemoteCommand(if (st.playing) "pause" else "play"))
                    }) { Icon(if (st.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (st.playing) "Pause" else "Play") }
                    androidx.compose.material3.IconButton(onClick = {
                        remote.command(d.device, com.dielify.app.net.RemoteCommand("next"))
                    }) { Icon(Icons.Filled.SkipNext, "Next song") }
                }
            }
            if (song != null) {
                var vol by remember(d.device) { mutableFloatStateOf(st.volume) }
                Slider(value = vol, onValueChange = { vol = it },
                    onValueChangeFinished = { remote.command(d.device, com.dielify.app.net.RemoteCommand("volume", value = vol)) },
                    modifier = Modifier.padding(start = 64.dp, end = 24.dp))
            }
        }
    }
}
