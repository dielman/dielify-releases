package com.dielify.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.net.ApiError
import com.dielify.app.net.BlendState
import kotlinx.coroutines.launch

// 0.9.8 Together on the phone: Jam (one shared queue) and Blend.

/** Top bar: the Jam (highlighted while one is going in the household). */
@Composable
fun JamButton(vm: AppViewModel) {
    val jam by vm.jam.collectAsStateWithLifecycle()
    IconButton(onClick = { vm.open(Screen.JamPage) }) {
        Icon(Icons.Filled.Groups, "Jam", tint = if (jam != null) MaterialTheme.colorScheme.primary else androidx.compose.ui.graphics.Color.Unspecified)
    }
}

@Composable
fun JamScreen(vm: AppViewModel) {
    val jam by vm.jam.collectAsStateWithLifecycle()
    val me = vm.account.collectAsStateWithLifecycle().value?.profile
    Page(vm, if (jam?.youHost == true) "Your Jam" else jam?.let { "${it.host}'s Jam" } ?: "Jam") { pad ->
        val j = jam
        if (j == null) {
            Column(Modifier.padding(pad).padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("One queue for everyone at home or in the car. This phone plays the music; everyone in your " +
                    "household can add songs from their phone or the PC.")
                Button(onClick = { vm.startJam() }) { Text("Start a Jam on this phone") }
            }
            return@Page
        }
        val now = j.songs.getOrNull(j.index)
        LazyColumn(Modifier.padding(pad).fillMaxSize()) {
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Playing on ${j.device} · ${j.members.joinToString(", ")}",
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (!j.youHost && j.members.none { it.equals(me, true) }) Button(onClick = { vm.joinJam() }) { Text("Join") }
                        OutlinedButton(onClick = { vm.leaveJam(j.youHost) }) { Text(if (j.youHost) "End the Jam" else "Leave") }
                    }
                    Text("Add songs from any song's ⋮ menu: Add to Jam.", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (now != null) {
                        Text("Playing now", style = MaterialTheme.typography.titleMedium)
                        Text("${now.item.title} · ${now.item.artistText}", fontWeight = FontWeight.Medium)
                        Text("added by ${now.addedBy}", style = MaterialTheme.typography.bodySmall)
                    }
                    Text("Up next", style = MaterialTheme.typography.titleMedium)
                    if (j.songs.size <= j.index + 1) Text("Nothing queued yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            items(j.songs.drop(j.index + 1), key = { it.id }) { s ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(s.item.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("${s.item.artistText} · added by ${s.addedBy}", maxLines = 1, overflow = TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (j.youHost || s.addedBy.equals(me, true)) IconButton(onClick = { vm.removeFromJam(s.id) }) {
                        Icon(Icons.Filled.Delete, "Take it out")
                    }
                }
            }
        }
    }
}

/** Library > Playlists: Blend on / off, and with whom. */
@Composable
fun BlendSection(vm: AppViewModel) {
    var state by remember { mutableStateOf<BlendState?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { state = runCatching { vm.server.blend() }.getOrNull() }
    val b = state ?: return
    if (b.partners.isEmpty() && b.waitingFor.isEmpty()) return  // nobody else in the household
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Blend", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            if (b.allowed) FilledTonalButton(onClick = {
                scope.launch {
                    try { state = vm.server.setBlend(!b.on); vm.playlistsChanged() }
                    catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't change that") }
                }
            }) { Text(if (b.on) "Turn off" else "Turn on") }
        }
        Text(when {
            !b.allowed -> "A parent needs to allow Blend for this account first."
            !b.on -> "A weekly playlist with each person in your household who turns it on too: songs you both play, and each other's favourites."
            b.partners.isNotEmpty() -> "You have a Blend with ${b.partners.joinToString(", ")}. New every week."
            else -> "Waiting for ${b.waitingFor.joinToString(", ")} to turn Blend on."
        }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        b.playlists.forEach { p ->
            OutlinedButton(onClick = { vm.open(Screen.PlaylistPage(p.id, p.name)) }) {
                Icon(Icons.Filled.Groups, null); Spacer(Modifier.width(6.dp)); Text(p.name)
            }
        }
    }
}
