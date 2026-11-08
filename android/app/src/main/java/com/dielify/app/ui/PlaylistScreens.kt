package com.dielify.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.net.Item
import com.dielify.app.net.PlaylistEntry
import com.dielify.app.net.PlaylistSummary
import com.dielify.app.net.SongIn

private fun describe(p: PlaylistSummary): String = listOfNotNull(
    "${p.count} songs",
    when {
        p.readOnly -> "from YouTube Music (one way)"
        p.ytId != null -> "synced with YouTube Music"
        else -> "only in Dielify"
    },
    if (p.pending > 0) "${p.pending} change${if (p.pending == 1) "" else "s"} waiting" else null,
).joinToString(" · ")

/** Library > Playlists: yours, then YouTube Music playlists not synced yet. */
@Composable
fun PlaylistsTab(vm: AppViewModel) {
    val version by vm.playlistsVersion.collectAsStateWithLifecycle()
    var creating by remember { mutableStateOf(false) }
    Loaded(vm, "playlists-$version", {
        val mine = vm.server.playlists()
        val yt = runCatching { vm.server.myPlaylists() }.getOrDefault(emptyList())
        mine to yt
    }) { (mine, yt) ->
        val synced = mine.mapNotNull { it.ytId }.toSet()
        val notSynced = yt.filter { it.id !in synced }
        LazyColumn(Modifier.fillMaxSize()) {
            item {
                Row(Modifier.fillMaxWidth().padding(16.dp, 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Your playlists", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                    FilledTonalButton(onClick = { creating = true }) { Icon(Icons.Filled.Add, null); Text("New") }
                }
            }
            if (mine.isEmpty()) item {
                Text("None yet. Make one, or sync one of your YouTube Music playlists below.",
                    Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            items(mine, key = { "p${it.id}" }) { p ->
                Row(
                    Modifier.fillMaxWidth().clickable { vm.open(Screen.PlaylistPage(p.id, p.name)) }
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Thumb(p.thumbnail, 52.dp)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(p.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(describe(p), maxLines = 1, overflow = TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.bodySmall,
                            color = if (p.syncError != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (p.ytId != null) Icon(Icons.Filled.Sync, "Synced", tint = MaterialTheme.colorScheme.primary)
                }
            }
            if (notSynced.isNotEmpty()) {
                item {
                    Text("On YouTube Music, not synced", style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(start = 16.dp, top = 20.dp, bottom = 4.dp))
                    Text("Sync one to keep it in Dielify and on your PC: its songs download, and changes go both ways.",
                        Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                items(notSynced, key = { "y${it.id}" }) { it ->
                    Row(Modifier.fillMaxWidth().padding(start = 16.dp, top = 6.dp, bottom = 6.dp, end = 8.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.weight(1f).clickable { vm.openItem(it) }) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Thumb(it.thumbnail, 52.dp)
                                Spacer(Modifier.width(12.dp))
                                Column {
                                    Text(it.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(it.subtitle ?: "", maxLines = 1, style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                        OutlinedButton(onClick = { vm.importPlaylist(it) }) { Text("Sync") }
                    }
                }
            }
        }
    }
    if (creating) NewPlaylistDialog(onDismiss = { creating = false }) { name, onYt ->
        creating = false
        vm.newPlaylistWith(name, onYt, emptyList())
    }
}

@Composable
fun PlaylistScreen(vm: AppViewModel, page: Screen.PlaylistPage) {
    val version by vm.playlistsVersion.collectAsStateWithLifecycle()
    var menu by remember { mutableStateOf(false) }
    var renaming by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<PlaylistEntry?>(null) }
    var current by remember { mutableStateOf<PlaylistSummary?>(null) }
    Page(vm, current?.name ?: page.name, actions = {
        Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "More") }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                val p = current
                if (p != null && !p.readOnly) DropdownMenuItem(text = { Text("Rename") },
                    leadingIcon = { Icon(Icons.Filled.Edit, null) }, onClick = { menu = false; renaming = true })
                if (p != null) DropdownMenuItem(text = { Text("Delete playlist") },
                    leadingIcon = { Icon(Icons.Filled.Delete, null) }, onClick = { menu = false; deleting = true })
            }
        }
    }) { pad ->
        Box(Modifier.padding(pad)) {
            Loaded(vm, "pl-${page.id}-$version", { vm.server.playlist(page.id) }) { d ->
                val p = d.playlist
                LaunchedEffect(p) { current = p }
                val songs = d.entries.map { it.item }
                val have = songs.mapNotNull { it.libraryTrackId }
                LazyColumn(Modifier.fillMaxSize()) {
                    item {
                        Column(Modifier.fillMaxWidth().padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Thumb(p.thumbnail, 180.dp)
                            Spacer(Modifier.height(12.dp))
                            Text(p.name, style = MaterialTheme.typography.titleLarge)
                            Text(describe(p), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            p.syncError?.let {
                                Text("Couldn't reach YouTube: $it", style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.error)
                            }
                            Spacer(Modifier.height(12.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                Button(enabled = songs.isNotEmpty(), onClick = { vm.openItem(songs.first(), songs) }) {
                                    Icon(Icons.Filled.PlayArrow, null); Text("Play")
                                }
                                FilledTonalButton(enabled = songs.isNotEmpty(), onClick = {
                                    val s = songs.shuffled()
                                    vm.openItem(s.first(), s)
                                }) { Icon(Icons.Filled.Shuffle, null); Spacer(Modifier.width(4.dp)); Text("Shuffle") }
                            }
                            Spacer(Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                if (p.ytId != null) OutlinedButton(onClick = { vm.syncPlaylist(p) }) {
                                    Icon(Icons.Filled.Sync, null); Spacer(Modifier.width(4.dp)); Text("Sync now")
                                }
                                if (have.isNotEmpty()) OutlinedButton(onClick = { vm.saveLibraryToPhone(have) }) {
                                    Icon(Icons.Filled.DownloadForOffline, null); Spacer(Modifier.width(4.dp)); Text("Save on phone")
                                }
                            }
                            if (have.size < songs.size) Text(
                                "${songs.size - have.size} not on your PC yet: they're downloading. Tap any song to play it now.",
                                Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    items(d.entries, key = { "e${it.entryId}" }) { e ->
                        ItemRow(vm, e.item, songs,
                            extra = if (p.readOnly) emptyList() else listOf("Remove from playlist" to { removing = e }))
                    }
                }
            }
        }
    }
    val p = current
    if (renaming && p != null) NameDialog("Rename playlist", p.name, onDismiss = { renaming = false }) {
        renaming = false
        vm.renamePlaylist(p, it)
    }
    if (deleting && p != null) AlertDialog(
        onDismissRequest = { deleting = false },
        title = { Text("Delete \"${p.name}\"?") },
        text = {
            Text(if (p.ytId != null && !p.readOnly)
                "You can delete it only from Dielify (it stays on YouTube Music and stops syncing), or from YouTube Music too. Your downloaded songs are kept either way."
            else "Your downloaded songs are kept.")
        },
        confirmButton = {
            Column(horizontalAlignment = Alignment.End) {
                if (p.ytId != null && !p.readOnly) TextButton(onClick = { deleting = false; vm.deletePlaylist(p, true) }) {
                    Text("Delete here and on YouTube Music", color = MaterialTheme.colorScheme.error)
                }
                TextButton(onClick = { deleting = false; vm.deletePlaylist(p, false) }) { Text("Delete from Dielify only") }
            }
        },
        dismissButton = { TextButton(onClick = { deleting = false }) { Text("Cancel") } },
    )
    val r = removing
    if (r != null && p != null) {
        if (p.ytId == null) { removing = null; vm.removeEntry(p, r) }
        else AlertDialog(
            onDismissRequest = { removing = null },
            title = { Text("Remove \"${r.item.title}\"?") },
            text = { Text("This playlist is synced, so it's also removed from \"${p.name}\" on YouTube Music. The song stays in your library.") },
            confirmButton = { TextButton(onClick = { removing = null; vm.removeEntry(p, r) }) { Text("Remove") } },
            dismissButton = { TextButton(onClick = { removing = null }) { Text("Cancel") } },
        )
    }
}

/** Shown over any screen while vm.addToPlaylist holds songs. */
@Composable
fun AddToPlaylistDialog(vm: AppViewModel) {
    val songs by vm.addToPlaylist.collectAsStateWithLifecycle()
    val chosen = songs ?: return
    var creating by remember { mutableStateOf(false) }
    val close = { vm.addToPlaylist.value = null }
    if (creating) {
        NewPlaylistDialog(onDismiss = { creating = false }) { name, onYt ->
            creating = false
            close()
            vm.newPlaylistWith(name, onYt, chosen)
        }
        return
    }
    AlertDialog(
        onDismissRequest = close,
        title = { Text(if (chosen.size == 1) "Add \"${chosen[0].title}\" to…" else "Add ${chosen.size} songs to…") },
        text = {
            Loaded(vm, "pick", { vm.server.playlists().filter { !it.readOnly } }) { lists ->
                LazyColumn(Modifier.heightIn(max = 360.dp)) {
                    item {
                        Row(Modifier.fillMaxWidth().clickable { creating = true }.padding(vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.Add, null)
                            Spacer(Modifier.width(12.dp))
                            Text("New playlist", fontWeight = FontWeight.Medium)
                        }
                        HorizontalDivider()
                    }
                    items(lists, key = { it.id }) { p ->
                        Column(Modifier.fillMaxWidth().clickable { close(); vm.addSongsTo(p, chosen) }.padding(vertical = 10.dp)) {
                            Text(p.name)
                            Text(describe(p), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = close) { Text("Cancel") } },
    )
}

@Composable
private fun NewPlaylistDialog(onDismiss: () -> Unit, onCreate: (String, Boolean) -> Unit) {
    var name by remember { mutableStateOf("") }
    var onYoutube by remember { mutableStateOf(true) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New playlist") },
        text = {
            Column {
                OutlinedTextField(name, { name = it }, label = { Text("Name") }, singleLine = true)
                Row(Modifier.fillMaxWidth().clickable { onYoutube = !onYoutube }, verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(onYoutube, { onYoutube = it })
                    Text("Also on YouTube Music (private), kept in sync")
                }
            }
        },
        confirmButton = { TextButton(enabled = name.isNotBlank(), onClick = { onCreate(name.trim(), onYoutube) }) { Text("Create") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun NameDialog(title: String, initial: String, onDismiss: () -> Unit, onDone: (String) -> Unit) {
    var name by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { OutlinedTextField(name, { name = it }, singleLine = true) },
        confirmButton = { TextButton(enabled = name.isNotBlank(), onClick = { onDone(name.trim()) }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

