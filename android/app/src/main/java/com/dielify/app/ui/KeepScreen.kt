package com.dielify.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.dielify.app.dielify
import com.dielify.app.net.PlaylistSummary

/** Settings: keep favourites on this phone automatically. */
@Composable
fun KeepSettings(vm: AppViewModel) {
    val keep = LocalContext.current.dielify.keep
    var liked by remember { mutableStateOf(keep.liked) }
    var top by remember { mutableStateOf(keep.top > 0) }
    var wifi by remember { mutableStateOf(keep.wifiOnly) }
    var chosen by remember { mutableStateOf(keep.playlists) }
    var lists by remember { mutableStateOf<List<PlaylistSummary>?>(null) }
    LaunchedEffect(Unit) { lists = runCatching { vm.server.playlists() }.getOrNull() }
    Column {
        Text("Keep on this phone automatically", style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text("Saved without tapping Save and checked twice a day, so they play with no signal. Songs that stop " +
            "qualifying are taken off again (not ones you saved yourself).",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        @Composable
        fun toggle(label: String, on: Boolean, set: (Boolean) -> Unit) = Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, Modifier.weight(1f)); Switch(checked = on, onCheckedChange = set)
        }
        toggle("Thumbs-up songs", liked) { liked = it; keep.liked = it }
        toggle("Your top 50 (last 30 days)", top) { top = it; keep.top = if (it) 50 else 0 }
        toggle("Only on Wi-Fi", wifi) { wifi = it; keep.wifiOnly = it }
        // Playlists are switched on from their own page; here only the ones already kept
        Text("Playlists", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodyMedium)
        val kept = lists?.filter { it.id in chosen }.orEmpty()
        if (chosen.isEmpty() || (lists != null && kept.isEmpty())) Text(
            "None. To keep a playlist on this phone, open it and switch on “Keep on this phone”.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        else if (lists == null) Text("Loading…", style = MaterialTheme.typography.bodySmall)
        else kept.forEach { p ->
            toggle("${p.name} (${p.count})", true) { chosen = chosen - p.id; keep.playlists = chosen }
        }
        if (liked || top || chosen.isNotEmpty()) TextButton(onClick = {
            keep.runNow(); vm.messages.tryEmit(if (wifi) "Checking now (saves on Wi-Fi)" else "Checking now")
        }) { Text("Update now") }
    }
}

/** On a playlist's page: keep its songs on this phone (added and removed as the list changes). */
@Composable
fun KeepPlaylistSwitch(vm: AppViewModel, id: Long, modifier: Modifier = Modifier) {
    val keep = LocalContext.current.dielify.keep
    var on by remember(id) { mutableStateOf(id in keep.playlists) }
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Filled.DownloadForOffline, null)
        Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
            Text("Keep on this phone")
            Text(if (on) "Its songs stay on the phone and follow the playlist as it changes" +
                    (if (keep.wifiOnly) " (saves on Wi-Fi)" else "")
                else "Plays with no signal",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked = on, onCheckedChange = { v ->
            on = v
            keep.playlists = if (v) keep.playlists + id else keep.playlists - id
            // (changing the list starts a check at once)
            vm.messages.tryEmit(if (v) "Saving this playlist on your phone"
                else "Taking this playlist's songs off the phone (not ones you saved yourself)")
        })
    }
}
