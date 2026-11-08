package com.dielify.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.material3.TextButton
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.DownloadForOffline
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.VerticalAlignTop
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.SubcomposeAsyncImage
import com.dielify.app.net.ApiError
import com.dielify.app.net.Download
import com.dielify.app.net.DownloadList
import com.dielify.app.net.Item
import com.dielify.app.net.YtCollection
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun RootScreen(vm: AppViewModel) {
    val tab by vm.tab.collectAsStateWithLifecycle()
    when (tab) {
        Tab.Library -> LibraryScreen(vm)
        Tab.Discover -> DiscoverScreen(vm)
        Tab.Search -> YtSearchScreen(vm)
        Tab.Downloads -> DownloadsScreen(vm)
    }
}

// --- pictures and rows for YouTube items ---------------------------------------------------

/** YouTube's own artwork (loaded straight from YouTube's image servers). */
@Composable
fun Thumb(url: String?, size: Dp?, round: Boolean = false, modifier: Modifier = Modifier) {
    val shape = if (round) CircleShape else RoundedCornerShape(if (size == null || size > 100.dp) 8.dp else 4.dp)
    val base = if (size == null) modifier.fillMaxWidth().height(160.dp) else modifier.size(size)
    val placeholder = @Composable {
        Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceVariant), Alignment.Center) {
            Icon(Icons.Filled.MusicNote, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
    Box(base.clip(shape)) {
        if (url == null) placeholder()
        else SubcomposeAsyncImage(
            model = url, contentDescription = null, contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(), loading = { placeholder() }, error = { placeholder() },
        )
    }
}

private fun subtitleOf(item: Item): String = when (item.type) {
    "song", "video" -> listOfNotNull(item.artistText.ifEmpty { null }, item.album,
        item.durationS?.let { formatDuration(it.toLong()) }).joinToString(" · ")
    "album" -> listOfNotNull("Album", item.artistText.ifEmpty { null }, item.year).joinToString(" · ")
    "playlist" -> item.subtitle ?: "Playlist"
    "artist" -> item.subtitle ?: "Artist"
    else -> item.subtitle ?: ""
}

/** A row for a song/album/playlist/artist, with a menu (download, similar songs). */
@Composable
fun ItemRow(vm: AppViewModel, item: Item, queue: List<Item> = listOf(item),
            extra: List<Pair<String, () -> Unit>> = emptyList(),
            onClick: () -> Unit = { vm.openItem(item, queue) }) {
    var menu by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(start = 16.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Thumb(item.thumbnail, 52.dp, round = item.type == "artist")
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(item.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (item.libraryTrackId != null) {
                    Icon(Icons.Filled.CheckCircle, "In your library", Modifier.size(14.dp),
                        tint = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(4.dp))
                }
                Text(
                    subtitleOf(item), maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (item.isSong && item.libraryTrackId == null) {
            IconButton(onClick = { vm.download(item) }) { Icon(Icons.Filled.Download, "Download to the PC") }
        }
        Box {
            IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "More") }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                if (item.isSong) DropdownMenuItem(
                    text = { Text("Play") }, onClick = { menu = false; vm.openItem(item, queue) })
                if (item.type != "artist" && item.libraryTrackId == null) {
                    DropdownMenuItem(
                        text = { Text(if (item.isSong) "Download next" else "Download all next") },
                        onClick = { menu = false; vm.download(item, next = true) })
                    DropdownMenuItem(
                        text = { Text(if (item.isSong) "Download (back of the line)" else "Download all") },
                        onClick = { menu = false; vm.download(item, next = false) })
                }
                if (item.isSong) DropdownMenuItem(
                    text = { Text("Add to playlist…") },
                    onClick = { menu = false; vm.pickPlaylistFor(listOf(item)) })
                extra.forEach { (label, action) ->
                    DropdownMenuItem(text = { Text(label) }, onClick = { menu = false; action() })
                }
                if (item.isSong) DropdownMenuItem(
                    text = { Text("Similar songs") },
                    onClick = { menu = false; vm.open(Screen.SimilarPage(item.id, item.title)) })
                if (item.isSong && item.albumId != null) DropdownMenuItem(
                    text = { Text("Go to album") },
                    onClick = { menu = false; vm.open(Screen.YtAlbumPage(item.albumId, item.album ?: "Album")) })
                if (item.type != "artist" && item.artists.isNotEmpty()) DropdownMenuItem(
                    text = { Text("Search ${item.artists.first()}") },
                    onClick = { menu = false; vm.searchRequest.value = item.artists.first(); vm.selectTab(Tab.Search) })
            }
        }
    }
}

/** A square card for the horizontal shelves on Discover. */
@Composable
private fun ItemCard(vm: AppViewModel, item: Item, queue: List<Item>) {
    Column(Modifier.width(150.dp).clickable { vm.openItem(item, queue) }) {
        Box {
            Thumb(item.thumbnail, 150.dp, round = item.type == "artist")
            if (item.isSong) Box(
                Modifier.align(Alignment.BottomEnd).padding(6.dp).size(30.dp).clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.8f)),
                Alignment.Center,
            ) {
                Icon(
                    Icons.Filled.PlayArrow,
                    null, Modifier.size(18.dp),
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(item.title, maxLines = 2, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium,
            style = MaterialTheme.typography.bodyMedium)
        Text(subtitleOf(item), maxLines = 1, overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun ShelfRow(vm: AppViewModel, title: String, items: List<Item>) {
    if (items.isEmpty()) return
    Text(title, style = MaterialTheme.typography.titleMedium,
        modifier = Modifier.padding(start = 16.dp, top = 20.dp, bottom = 8.dp))
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items(items, key = { it.type + it.id }) { ItemCard(vm, it, items) }
    }
}

/** A shelf of your own (library) songs. */
@Composable
fun TrackShelf(vm: AppViewModel, title: String, tracks: List<com.dielify.app.net.Track>) {
    if (tracks.isEmpty()) return
    Text(title, style = MaterialTheme.typography.titleMedium,
        modifier = Modifier.padding(start = 16.dp, top = 20.dp, bottom = 8.dp))
    LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items(tracks.size, key = { tracks[it].id }) { i ->
            val t = tracks[i]
            Column(Modifier.width(150.dp).clickable { vm.play(tracks, i) }) {
                Cover(vm, t.coverUrl, 150.dp)
                Spacer(Modifier.height(6.dp))
                Text(t.title, maxLines = 2, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium,
                    style = MaterialTheme.typography.bodyMedium)
                Text(t.artist, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

// --- Discover ---------------------------------------------------------------------------------

private data class DiscoverData(
    val home: com.dielify.app.net.HomeFeed,
    val charts: com.dielify.app.net.Charts?,
    val forYou: com.dielify.app.net.ForYou?,
    val mixes: List<com.dielify.app.net.PlaylistSummary>,
)

@Composable
fun DiscoverScreen(vm: AppViewModel) {
    Page(vm, "Discover", back = false, tabs = true, actions = { TopActions(vm) }) { pad ->
        Box(Modifier.padding(pad)) {
            Loaded(vm, "discover", {
                val home = vm.server.home()
                val charts = runCatching { vm.server.charts() }.getOrNull()
                val forYou = runCatching { vm.server.forYou() }.getOrNull()
                val mixes = runCatching { vm.server.mixes().mixes }.getOrDefault(emptyList())
                DiscoverData(home, charts, forYou, mixes)
            }) { (home, charts, forYou, mixes) ->
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 16.dp)) {
                    item(key = "endless") {
                        androidx.compose.material3.FilledTonalButton(onClick = { vm.startEndless() },
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                            Icon(Icons.Filled.Explore, null)
                            Text("  Never-ending discovery")
                        }
                    }
                    item(key = "mixes") { MixShelf(vm, mixes) }
                    if (forYou != null) {
                        item(key = "fy-more") { ShelfRow(vm, "More like your top songs", forYou.moreLike) }
                        item(key = "fy-forgotten") { TrackShelf(vm, "Forgotten favourites", forYou.forgotten) }
                    }
                    items(home.shelves, key = { "shelf-" + it.title }) { ShelfRow(vm, it.title, it.items) }
                    if (charts != null) {
                        item(key = "charts-pl") { ShelfRow(vm, "Charts", charts.playlists) }
                        item(key = "charts-ar") { ShelfRow(vm, "Top artists", charts.artists) }
                    }
                    item {
                        Text(
                            "Tap a song to play it straight away; your PC keeps a copy. ✓ songs are " +
                                "already in your library.",
                            Modifier.padding(16.dp), style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

// --- YouTube search -----------------------------------------------------------------------------

private val searchTypes = listOf("song" to "Songs", "album" to "Albums", "playlist" to "Playlists",
    "artist" to "Artists", "video" to "Videos")

@Composable
fun YtSearchScreen(vm: AppViewModel) {
    var text by rememberSaveable { mutableStateOf("") }
    var query by rememberSaveable { mutableStateOf("") }
    var type by rememberSaveable { mutableStateOf("song") }
    val requested by vm.searchRequest.collectAsStateWithLifecycle()
    LaunchedEffect(requested) {
        requested?.let { text = it; query = it; type = "song"; vm.searchRequest.value = null }
    }
    Page(vm, "Search YouTube Music", back = false, tabs = true, actions = { TopActions(vm) }) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            OutlinedTextField(
                text, { text = it },
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                placeholder = { Text("Songs, albums, artists") }, singleLine = true,
                trailingIcon = {
                    if (text.isNotEmpty()) IconButton(onClick = { text = ""; query = "" }) {
                        Icon(Icons.Filled.Close, "Clear")
                    }
                },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { query = text.trim() }),
            )
            Row(
                Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                searchTypes.forEach { (t, label) ->
                    FilterChip(selected = type == t, onClick = { type = t; query = text.trim() },
                        label = { Text(label) })
                }
            }
            if (query.isBlank()) {
                Box(Modifier.fillMaxSize().padding(32.dp), Alignment.Center) {
                    Text("Search YouTube Music, then tap a song to play it. Your PC keeps a copy.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                Loaded(vm, "$type:$query", { vm.server.ytSearch(query, type) }) { items ->
                    if (items.isEmpty()) Box(Modifier.fillMaxSize(), Alignment.Center) { Text("No results") }
                    else LazyColumn(Modifier.fillMaxSize()) {
                        items(items, key = { it.type + it.id }) { ItemRow(vm, it, items) }
                    }
                }
            }
        }
    }
}

// --- YouTube album / playlist, similar songs ---------------------------------------------------------

@Composable
fun YtCollectionScreen(vm: AppViewModel, name: String, key: String, load: suspend () -> YtCollection) {
    Page(vm, name) { pad ->
        Box(Modifier.padding(pad)) {
            Loaded(vm, key, load) { c ->
                val missing = c.tracks.count { it.libraryTrackId == null }
                val have = c.tracks.mapNotNull { it.libraryTrackId }
                LazyColumn(Modifier.fillMaxSize()) {
                    item {
                        Column(Modifier.fillMaxWidth().padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Thumb(c.info.thumbnail, 200.dp)
                            Spacer(Modifier.height(12.dp))
                            Text(c.info.title, style = MaterialTheme.typography.titleLarge)
                            Text(subtitleOf(c.info), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(
                                "${c.tracks.size} songs · ${have.size} in your library",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Spacer(Modifier.height(12.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                if (missing > 0) Button(onClick = { vm.download(c.info) }) {
                                    Icon(Icons.Filled.Download, null); Spacer(Modifier.width(4.dp))
                                    Text(if (missing == c.tracks.size) "Download all" else "Download $missing missing")
                                }
                                if (have.isNotEmpty()) Button(onClick = { vm.playLibrary(have) }) {
                                    Icon(Icons.Filled.PlayArrow, null); Text("Play downloaded")
                                }
                            }
                            if (have.isNotEmpty()) {
                                val saved by vm.savedSongs.collectAsStateWithLifecycle()
                                val notSaved = have.filter { it !in saved }
                                Spacer(Modifier.height(8.dp))
                                if (notSaved.isEmpty()) Text("Downloaded songs are all on this phone",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                                else OutlinedButton(onClick = { vm.saveLibraryToPhone(notSaved) }) {
                                    Icon(Icons.Filled.DownloadForOffline, null); Spacer(Modifier.width(8.dp))
                                    Text("Save ${notSaved.size} downloaded on phone")
                                }
                            }
                        }
                    }
                    items(c.tracks, key = { "t" + it.id }) { t ->
                        ItemRow(vm, t, c.tracks)
                    }
                }
            }
        }
    }
}

@Composable
fun SimilarScreen(vm: AppViewModel, page: Screen.SimilarPage) {
    Page(vm, "Like \"${page.name}\"") { pad ->
        Box(Modifier.padding(pad)) {
            Loaded(vm, page.videoId, { vm.server.similar(page.videoId) }) { items ->
                LazyColumn(Modifier.fillMaxSize()) { items(items, key = { it.type + it.id }) { ItemRow(vm, it, items) } }
            }
        }
    }
}

// --- Downloads (the PC's queue) --------------------------------------------------------------------

@Composable
fun DownloadsScreen(vm: AppViewModel) {
    var active by remember { mutableStateOf<DownloadList?>(null) }
    var finished by remember { mutableStateOf<List<Download>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var tick by remember { mutableStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(tick) {
        while (true) {
            try {
                val a = vm.server.activeDownloads()
                active = a
                vm.setDownloadCount(a.activeTotal ?: 0)
                finished = vm.server.finishedDownloads().downloads
                error = null
            } catch (e: ApiError) {
                if (e.code == 401) vm.tokenRejected()
                error = e.message
            }
            delay(if ((active?.activeTotal ?: 0) > 0) 1_500 else 5_000)
        }
    }
    Page(vm, "Downloads", back = false, tabs = true, actions = { TopActions(vm) }) { pad ->
        val a = active
        if (a == null) {
            Box(Modifier.padding(pad).fillMaxSize().padding(32.dp), Alignment.Center) {
                Text(error ?: "Loading…")
            }
            return@Page
        }
        val running = a.downloads.firstOrNull { it.status != "queued" }
        val waiting = a.downloads.filter { it.status == "queued" }
        val total = a.activeTotal ?: a.downloads.size
        val pace = a.secondsPerSong ?: 20.0
        LazyColumn(Modifier.padding(pad).fillMaxSize()) {
            item {
                Text(
                    when {
                        error != null -> error!!
                        total == 0 -> "Nothing downloading. Find music on Discover or Search."
                        else -> "$total to go · about ${minutes(total * pace)} left"
                    },
                    Modifier.padding(16.dp), color = if (error != null) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (running != null) {
                item { Section("Now") }
                item(key = "run${running.id}") {
                    DownloadRow(running, onCancel = { scope.launch { cancel(vm, running) ; tick++ } }) {
                        val label = if (running.status == "processing") "Tagging and saving…"
                        else "${(running.progress * 100).toInt()}%"
                        LinearProgressIndicator(
                            progress = { running.progress.toFloat() },
                            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                        )
                        SmallText(label)
                        running.error?.let { SmallText(it, error = true) }
                    }
                }
            }
            if (waiting.isNotEmpty()) {
                item { Section("Waiting in line") }
                items(waiting, key = { "w${it.id}" }) { d ->
                    val pos = waiting.indexOf(d) + 1
                    DownloadRow(
                        d, onCancel = { scope.launch { cancel(vm, d); tick++ } },
                        onMoveUp = if (pos > 1 && !d.next) ({ scope.launch { moveUp(vm, d); tick++ } }) else null,
                    ) {
                        SmallText("#$pos · in about ${minutes(pos * pace)}" + (if (d.next) " · next" else "") +
                            (d.error?.let { " · $it" } ?: ""))
                    }
                }
                if (total > a.downloads.size + 0) item {
                    SmallText("…and ${total - a.downloads.size} more", Modifier.padding(16.dp))
                }
            }
            if (finished.isNotEmpty()) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Section("Finished")
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = {
                            scope.launch {
                                try { vm.server.clearFinishedDownloads() } catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't clear") }
                                tick++
                            }
                        }, modifier = Modifier.padding(end = 8.dp)) { Text("Clear finished") }
                    }
                }
                items(finished, key = { "f${it.id}" }) { d ->
                    DownloadRow(d, onClick = d.trackId?.let { id -> { vm.playLibrary(listOf(id)) } }) {
                        when (d.status) {
                            "done" -> SmallText("Done · tap to play")
                            "cancelled" -> SmallText("Cancelled")
                            else -> SmallText("Failed: ${d.error ?: "unknown error"}", error = true)
                        }
                    }
                }
            }
        }
    }
}

private suspend fun moveUp(vm: AppViewModel, d: Download) {
    try { vm.server.moveDownloadNext(d.id) } catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't move it") }
}

private suspend fun cancel(vm: AppViewModel, d: Download) {
    try { vm.server.cancelDownload(d.id) } catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't cancel") }
}

private fun minutes(seconds: Double): String {
    val m = (seconds / 60).toInt()
    return when {
        m < 1 -> "a minute"
        m < 60 -> "$m min"
        else -> "${m / 60} h ${m % 60} min"
    }
}

@Composable
private fun Section(title: String) = Text(
    title, style = MaterialTheme.typography.titleMedium,
    modifier = Modifier.padding(start = 16.dp, top = 12.dp, bottom = 4.dp),
)

@Composable
private fun SmallText(text: String, modifier: Modifier = Modifier, error: Boolean = false) = Text(
    text, modifier, style = MaterialTheme.typography.bodySmall,
    color = if (error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
)

@Composable
private fun DownloadRow(
    d: Download,
    onCancel: (() -> Unit)? = null,
    onClick: (() -> Unit)? = null,
    onMoveUp: (() -> Unit)? = null,
    details: @Composable () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().let { if (onClick != null) it.clickable(onClick = onClick) else it }
            .padding(start = 16.dp, top = 6.dp, bottom = 6.dp, end = if (onCancel == null) 16.dp else 0.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            when (d.status) {
                "done" -> Icons.Filled.CheckCircle
                "failed" -> Icons.Filled.ErrorOutline
                else -> Icons.Filled.Download
            },
            null,
            tint = when (d.status) {
                "done" -> MaterialTheme.colorScheme.primary
                "failed" -> MaterialTheme.colorScheme.error
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(d.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
            SmallText(listOfNotNull(d.artist, d.album).joinToString(" · "))
            details()
        }
        if (onMoveUp != null) IconButton(onClick = onMoveUp) { Icon(Icons.Filled.VerticalAlignTop, "Download this next") }
        if (onCancel != null) IconButton(onClick = onCancel) { Icon(Icons.Filled.Close, "Cancel") }
    }
}
