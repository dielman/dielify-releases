package com.dielify.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.PersonAdd
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.dielify
import com.dielify.app.net.ApiError
import com.dielify.app.net.ArtistAbout
import com.dielify.app.net.Follow
import com.dielify.app.net.FollowIn
import com.dielify.app.net.NewReleases
import kotlinx.coroutines.launch

// 0.9.5 Discovery on the phone: Follow + About on artist pages, and the Settings sections.

/** Follow an artist: their new releases show in Discover's "New for you". */
@Composable
fun FollowButton(vm: AppViewModel, name: String, channelId: String? = null) {
    var on by remember(name) { mutableStateOf<Boolean?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(name) {
        on = runCatching { vm.server.follows().any { artistKeyOf(it.name) == artistKeyOf(name) } }.getOrNull() ?: false
    }
    OutlinedButton(enabled = on != null, onClick = {
        val want = on != true
        scope.launch {
            try {
                vm.server.follow(FollowIn(name, channelId, want))
                on = want
                vm.messages.tryEmit(if (want) "Following $name: their new releases show in Discover" else "Stopped following $name")
            } catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't change that") }
        }
    }) {
        Icon(if (on == true) Icons.Filled.Check else Icons.Filled.PersonAdd, null)
        Spacer(Modifier.width(4.dp))
        Text(if (on == true) "Following" else "Follow")
    }
}

private fun artistKeyOf(name: String) = com.dielify.app.net.Ratings.artistKey(name)

/** The artist's bio (4 lines, tap for all) and links (opened in the browser). */
@Composable
fun ArtistAboutSection(vm: AppViewModel, name: String) {
    var about by remember(name) { mutableStateOf<ArtistAbout?>(null) }
    var open by remember(name) { mutableStateOf(false) }
    LaunchedEffect(name) { about = runCatching { vm.server.artistAbout(name) }.getOrNull() }
    val a = about ?: return
    if (a.description.isNullOrBlank() && a.links.isEmpty()) return
    val uri = LocalUriHandler.current
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text("About", style = MaterialTheme.typography.titleMedium)
        a.description?.takeIf { it.isNotBlank() }?.let {
            Text(it, maxLines = if (open) Int.MAX_VALUE else 4, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyMedium, modifier = Modifier.clickable { open = !open }.padding(top = 4.dp))
        }
        if (a.links.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            a.links.forEach { l -> AssistChip(onClick = { runCatching { uri.openUri(l.url) } }, label = { Text(l.label) }) }
        }
    }
}

/** Settings: songs and playlists left out of your taste, with "Count again". */
@Composable
fun TasteList(vm: AppViewModel) {
    val all by LocalContext.current.dielify.taste.all.collectAsStateWithLifecycle()
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Left out of your taste", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text("These still play, but don't shape For you, mixes, the time-of-day mix or new releases. Leave a song out " +
            "from its ⋮ menu, a playlist from its page's menu.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (all.isEmpty()) Text("Nothing left out.")
        all.forEach { t ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${if (t.kind == "playlist") "Playlist" else "Song"}: ${t.name}", Modifier.weight(1f), maxLines = 2)
                TextButton(onClick = { vm.setTaste(t.kind, t.key, t.name, false) }) { Text("Count again") }
            }
        }
    }
}

/** Settings: new releases (auto-download, who you follow). */
@Composable
fun NewReleaseSettings(vm: AppViewModel) {
    var state by remember { mutableStateOf<NewReleases?>(null) }
    var follows by remember { mutableStateOf<List<Follow>>(emptyList()) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        state = runCatching { vm.server.newReleases() }.getOrNull()
        follows = runCatching { vm.server.follows() }.getOrDefault(emptyList())
    }
    var child by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { child = runCatching { vm.server.me().role == "child" }.getOrDefault(false) }
    val s = state ?: return
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("New releases", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text("Dielify checks ${s.watching} ${if (s.watching == 1) "artist" else "artists"} once a day: the ones you follow " +
            "and your 20 most played. What's new shows in Discover > New for you.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (!child) Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Download new albums automatically")
                Text("Only albums that come out from now on", style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Switch(checked = s.autoDownload, onCheckedChange = { v ->
                scope.launch {
                    try { state = vm.server.setNewReleases(v) } catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't change that") }
                }
            })
        }
        if (follows.isEmpty()) Text("Following nobody yet. Follow an artist from their page.", style = MaterialTheme.typography.bodySmall)
        follows.forEach { f ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(f.name, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                TextButton(onClick = {
                    scope.launch {
                        follows = runCatching { vm.server.follow(FollowIn(f.name, follow = false)) }.getOrDefault(follows)
                    }
                }) { Text("Unfollow") }
            }
        }
    }
}
