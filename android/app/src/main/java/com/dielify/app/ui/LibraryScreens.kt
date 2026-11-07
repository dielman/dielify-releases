package com.dielify.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material.icons.filled.OfflinePin
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.net.Album
import com.dielify.app.net.Artist
import com.dielify.app.net.Link
import com.dielify.app.net.Track
import kotlinx.coroutines.delay

/** Top bar + content + the mini player at the bottom. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Page(
    vm: AppViewModel,
    title: String,
    back: Boolean = true,
    tabs: Boolean = false,
    actions: @Composable () -> Unit = {},
    content: @Composable (PaddingValues) -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                navigationIcon = {
                    if (back) IconButton(onClick = { vm.back() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back")
                    }
                },
                actions = { actions() },
            )
        },
        bottomBar = {
            Column {
                MiniPlayer(vm)
                if (tabs) TabBar(vm) else Spacer(Modifier.navigationBarsPadding())
            }
        },
        snackbarHost = { SnackbarHost(LocalSnackbar.current) },
        content = content,
    )
}

val LocalSnackbar = staticCompositionLocalOf { SnackbarHostState() }

@Composable
private fun TabBar(vm: AppViewModel) {
    val tab by vm.tab.collectAsStateWithLifecycle()
    val active by vm.activeDownloads.collectAsStateWithLifecycle()
    NavigationBar {
        Tab.entries.forEach { t ->
            NavigationBarItem(
                selected = tab == t,
                onClick = { vm.selectTab(t) },
                label = { Text(t.label) },
                icon = {
                    val icon = when (t) {
                        Tab.Library -> Icons.Filled.LibraryMusic
                        Tab.Discover -> Icons.Filled.Explore
                        Tab.Search -> Icons.Filled.Search
                        Tab.Downloads -> Icons.Filled.Download
                    }
                    if (t == Tab.Downloads && active > 0) {
                        BadgedBox(badge = { Badge { Text(if (active > 999) "999+" else active.toString()) } }) {
                            Icon(icon, null)
                        }
                    } else Icon(icon, null)
                },
            )
        }
    }
}

@Composable
fun TopActions(vm: AppViewModel) {
    LinkLabel(vm)
    IconButton(onClick = { vm.open(Screen.Settings) }) { Icon(Icons.Filled.Settings, "Settings") }
}

@Composable
private fun LinkLabel(vm: AppViewModel) {
    val link by vm.server.link.collectAsStateWithLifecycle()
    val text = when (val l = link) {
        is Link.Up -> if (l.viaTailscale) "via Tailscale" else "at home"
        Link.Down -> "PC not reachable"
        Link.Unknown -> ""
    }
    if (text.isNotEmpty()) Text(
        text, style = MaterialTheme.typography.labelMedium,
        color = if (link is Link.Down) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(end = 4.dp),
    )
}

@Composable
fun LibraryScreen(vm: AppViewModel) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var searching by rememberSaveable { mutableStateOf(false) }
    var query by rememberSaveable { mutableStateOf("") }
    Page(vm, "Library", back = false, tabs = true, actions = {
        IconButton(onClick = { searching = !searching; if (!searching) query = "" }) {
            Icon(if (searching) Icons.Filled.Close else Icons.Filled.Search, "Search your library")
        }
        TopActions(vm)
    }) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (searching) {
                OutlinedTextField(
                    query, { query = it },
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                    placeholder = { Text("Search your library") }, singleLine = true,
                )
            }
            if (searching && query.isNotBlank()) {
                SearchResults(vm, query.trim())
            } else {
                val tabs = listOf("Albums", "Artists", "Recent", "On phone")
                val link by vm.server.link.collectAsStateWithLifecycle()
                val savedCount = vm.savedSongs.collectAsStateWithLifecycle().value.size
                LaunchedEffect(link) {
                    // No PC? Show what's on the phone instead of an error.
                    if (link is Link.Down && savedCount > 0) tab = 3
                }
                PrimaryTabRow(selectedTabIndex = tab) {
                    tabs.forEachIndexed { i, name -> Tab(tab == i, { tab = i }, text = { Text(name) }) }
                }
                when (tab) {
                    0 -> Loaded(vm, "albums", { vm.server.albums() }) { AlbumGrid(vm, it) }
                    1 -> Loaded(vm, "artists", { vm.server.artists() }) { ArtistList(vm, it) }
                    2 -> Loaded(vm, "recent", { vm.server.recentAlbums() }) { AlbumGrid(vm, it) }
                    else -> SavedAlbums(vm)
                }
            }
        }
    }
}

@Composable
private fun SearchResults(vm: AppViewModel, query: String) {
    var debounced by rememberSaveable { mutableStateOf(query) }
    LaunchedEffect(query) { delay(300); debounced = query }
    Loaded(vm, debounced, { vm.server.search(debounced) }) { r ->
        if (r.artists.isEmpty() && r.albums.isEmpty() && r.tracks.isEmpty()) {
            Box(Modifier.fillMaxSize(), Alignment.Center) { Text("Nothing in your library matches \"$debounced\"") }
            return@Loaded
        }
        LazyColumn(Modifier.fillMaxSize()) {
            if (r.artists.isNotEmpty()) item { Heading("Artists") }
            items(r.artists, key = { "ar${it.id}" }) { ArtistRow(vm, it) }
            if (r.albums.isNotEmpty()) item { Heading("Albums") }
            items(r.albums, key = { "al${it.id}" }) { AlbumRow(vm, it) }
            if (r.tracks.isNotEmpty()) item { Heading("Songs") }
            itemsIndexed(r.tracks, key = { _, t -> "tr${t.id}" }) { i, t ->
                TrackRow(vm, t, showArtist = true) { vm.play(r.tracks, i) }
            }
        }
    }
}

@Composable
private fun Heading(text: String) = Text(
    text, style = MaterialTheme.typography.titleMedium,
    modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 4.dp),
)

@Composable
fun AlbumGrid(vm: AppViewModel, albums: List<Album>, header: (@Composable () -> Unit)? = null) {
    if (albums.isEmpty() && header == null) {
        Box(Modifier.fillMaxSize().padding(32.dp), Alignment.Center) {
            Text("No music yet. Download some in Dielify on the PC.")
        }
        return
    }
    LazyVerticalGrid(
        GridCells.Adaptive(150.dp),
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        if (header != null) item(span = { GridItemSpan(maxLineSpan) }) { header() }
        items(albums, key = { it.id }) { a ->
            Column(Modifier.clickable { vm.open(Screen.AlbumPage(a.id, a.name)) }) {
                Cover(vm, a.coverUrl, null)
                Spacer(Modifier.height(6.dp))
                Text(a.name, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
                Text(
                    a.artist, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ArtistList(vm: AppViewModel, artists: List<Artist>) {
    LazyColumn(Modifier.fillMaxSize()) { items(artists, key = { it.id }) { ArtistRow(vm, it) } }
}

@Composable
private fun ArtistRow(vm: AppViewModel, a: Artist) = ListRow(
    vm, a.coverUrl, a.name,
    if (a.albumCount == 1) "1 album" else "${a.albumCount} albums",
) { vm.open(Screen.ArtistPage(a.id, a.name)) }

@Composable
private fun AlbumRow(vm: AppViewModel, a: Album) = ListRow(vm, a.coverUrl, a.name, a.artist) {
    vm.open(Screen.AlbumPage(a.id, a.name))
}

@Composable
private fun ListRow(vm: AppViewModel, cover: String?, title: String, subtitle: String, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Cover(vm, cover, 52.dp, pixels = 150)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                subtitle, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
fun TrackRow(vm: AppViewModel, t: Track, showArtist: Boolean, onClick: () -> Unit) {
    val player by vm.player.collectAsStateWithLifecycle()
    val playing = player.trackId == t.id
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (showArtist) {
            Cover(vm, t.coverUrl, 44.dp, pixels = 150)
        } else {
            Text(
                t.trackNo?.toString() ?: "", Modifier.widthIn(min = 28.dp),
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                t.title, maxLines = 1, overflow = TextOverflow.Ellipsis,
                color = if (playing) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
            )
            if (showArtist) Text(
                "${t.artist} · ${t.album}", maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        val saved by vm.savedSongs.collectAsStateWithLifecycle()
        val saving by vm.savingIds.collectAsStateWithLifecycle()
        when {
            t.id in saved -> Icon(Icons.Filled.OfflinePin, "On this phone", Modifier.padding(end = 8.dp).size(18.dp),
                tint = MaterialTheme.colorScheme.primary)
            t.id in saving -> CircularProgressIndicator(Modifier.padding(end = 8.dp).size(16.dp), strokeWidth = 2.dp)
        }
        Text(
            formatDuration(t.durationS?.toLong()), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** "Save on phone" / "Saving 3 of 12" / "Remove from phone" for a set of songs. */
@Composable
fun SaveButton(vm: AppViewModel, tracks: List<Track>) {
    val saved by vm.savedSongs.collectAsStateWithLifecycle()
    val saving by vm.savingIds.collectAsStateWithLifecycle()
    val have = tracks.count { it.id in saved }
    val busy = tracks.count { it.id in saving }
    when {
        busy > 0 -> OutlinedButton(onClick = { vm.removeFromPhone(tracks.map { it.id }) }) {
            CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(8.dp)); Text("Saving on phone: $have of ${tracks.size} (tap to stop)")
        }
        have == tracks.size && have > 0 -> OutlinedButton(onClick = { vm.removeFromPhone(tracks.map { it.id }) }) {
            Icon(Icons.Filled.OfflinePin, null, tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(8.dp)); Text("On this phone · Remove")
        }
        else -> OutlinedButton(onClick = { vm.saveToPhone(tracks) }) {
            Icon(Icons.Filled.DownloadForOffline, null)
            Spacer(Modifier.width(8.dp))
            Text(if (have == 0) "Save on phone" else "Save the other ${tracks.size - have} on phone")
        }
    }
}

// --- songs saved on the phone (works with no connection to the PC) ------------------------------

private data class SavedAlbum(val album: String, val artist: String, val tracks: List<Track>)

private fun savedAlbums(songs: Collection<com.dielify.app.saved.SavedSong>): List<SavedAlbum> =
    songs.map { it.track }
        .groupBy { (it.albumArtist.ifEmpty { it.artist }) to it.album }
        .map { (k, ts) -> SavedAlbum(k.second, k.first, ts.sortedWith(compareBy({ it.trackNo ?: 999 }, { it.title }))) }
        .sortedWith(compareBy({ it.artist.lowercase() }, { it.album.lowercase() }))

@Composable
private fun SavedAlbums(vm: AppViewModel) {
    val songs by vm.savedSongs.collectAsStateWithLifecycle()
    val albums = savedAlbums(songs.values)
    if (albums.isEmpty()) {
        Box(Modifier.fillMaxSize().padding(32.dp), Alignment.Center) {
            Text("Nothing saved on this phone yet. Open an album and tap \"Save on phone\" to listen " +
                "without a connection to your PC.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        return
    }
    LazyVerticalGrid(
        GridCells.Adaptive(150.dp), Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Text(
                "${songs.size} songs · ${formatBytes(vm.saved.totalBytes())} on this phone",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        items(albums, key = { it.artist + "|" + it.album }) { a ->
            Column(Modifier.clickable { vm.open(Screen.SavedAlbumPage(a.album, a.artist)) }) {
                Cover(vm, a.tracks.first().coverUrl, null)
                Spacer(Modifier.height(6.dp))
                Text(a.album, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
                Text(
                    "${a.artist} · ${a.tracks.size}", maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
fun SavedAlbumScreen(vm: AppViewModel, page: Screen.SavedAlbumPage) {
    val songs by vm.savedSongs.collectAsStateWithLifecycle()
    val album = savedAlbums(songs.values).firstOrNull { it.album == page.album && it.artist == page.artist }
    Page(vm, page.album) { pad ->
        if (album == null) {
            Box(Modifier.padding(pad).fillMaxSize(), Alignment.Center) { Text("No longer on this phone") }
            return@Page
        }
        LazyColumn(Modifier.padding(pad).fillMaxSize()) {
            item {
                Column(Modifier.fillMaxWidth().padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Cover(vm, album.tracks.first().coverUrl, 220.dp, pixels = 600)
                    Spacer(Modifier.height(12.dp))
                    Text(album.album, style = MaterialTheme.typography.titleLarge)
                    Text(album.artist, color = MaterialTheme.colorScheme.primary)
                    Text("${album.tracks.size} songs on this phone", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Button(onClick = { vm.play(album.tracks) }) { Icon(Icons.Filled.PlayArrow, null); Text("Play") }
                        FilledTonalButton(onClick = { vm.play(album.tracks, shuffle = true) }) {
                            Icon(Icons.Filled.Shuffle, null); Spacer(Modifier.width(4.dp)); Text("Shuffle")
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(onClick = { vm.removeFromPhone(album.tracks.map { it.id }) }) {
                        Text("Remove from phone")
                    }
                }
            }
            itemsIndexed(album.tracks, key = { _, t -> t.id }) { i, t ->
                TrackRow(vm, t, showArtist = false) { vm.play(album.tracks, i) }
            }
        }
    }
}

fun formatBytes(bytes: Long): String = when {
    bytes >= 1L shl 30 -> "%.1f GB".format(bytes / (1L shl 30).toDouble())
    bytes >= 1L shl 20 -> "%.0f MB".format(bytes / (1L shl 20).toDouble())
    else -> "%.0f KB".format(bytes / 1024.0)
}

@Composable
fun AlbumScreen(vm: AppViewModel, page: Screen.AlbumPage) {
    Page(vm, page.name) { pad ->
        Box(Modifier.padding(pad)) {
            Loaded(vm, page.id, { vm.server.album(page.id) }) { detail ->
                val a = detail.album
                LazyColumn(Modifier.fillMaxSize()) {
                    item {
                        Column(
                            Modifier.fillMaxWidth().padding(16.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Cover(vm, a.coverUrl, 220.dp, pixels = 600)
                            Spacer(Modifier.height(12.dp))
                            Text(a.name, style = MaterialTheme.typography.titleLarge)
                            Text(
                                a.artist, color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.clickable { vm.open(Screen.ArtistPage(a.artistId, a.artist)) },
                            )
                            Text(
                                listOfNotNull(a.year?.toString(), "${a.songCount} songs",
                                    formatDuration(a.durationS.toLong())).joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Spacer(Modifier.height(12.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                Button(onClick = { vm.play(detail.tracks) }) {
                                    Icon(Icons.Filled.PlayArrow, null); Text("Play")
                                }
                                FilledTonalButton(onClick = { vm.play(detail.tracks, shuffle = true) }) {
                                    Icon(Icons.Filled.Shuffle, null); Spacer(Modifier.width(4.dp)); Text("Shuffle")
                                }
                            }
                            Spacer(Modifier.height(8.dp))
                            SaveButton(vm, detail.tracks)
                        }
                    }
                    itemsIndexed(detail.tracks, key = { _, t -> t.id }) { i, t ->
                        TrackRow(vm, t, showArtist = false) { vm.play(detail.tracks, i) }
                    }
                }
            }
        }
    }
}

@Composable
fun ArtistScreen(vm: AppViewModel, page: Screen.ArtistPage) {
    Page(vm, page.name) { pad ->
        Box(Modifier.padding(pad)) {
            Loaded(vm, page.id, { vm.server.artist(page.id) }) { detail ->
                AlbumGrid(vm, detail.albums)
            }
        }
    }
}
