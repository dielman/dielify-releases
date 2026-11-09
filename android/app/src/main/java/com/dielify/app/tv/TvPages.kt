package com.dielify.app.tv

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.BuildConfig
import com.dielify.app.net.Album
import com.dielify.app.net.ArtColors
import com.dielify.app.net.Item
import com.dielify.app.net.Link
import com.dielify.app.net.PlaylistSummary
import com.dielify.app.net.Track
import com.dielify.app.net.YtCollection
import com.dielify.app.ui.AppViewModel
import com.dielify.app.ui.Cover
import com.dielify.app.ui.Thumb
import com.dielify.app.ui.UpdateSection
import com.dielify.app.ui.formatDuration
import com.dielify.app.ui.hexColor
import com.dielify.app.ui.tintBrush
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

// 0.9.10: the TV's pages. Same data as the phone (and Josh's rule: no shelves of single
// songs on Home, only albums, playlists and mixes).

/** Loads [load] once per [key]; shows a message while loading or when it fails. */
@Composable
fun <T> TvLoaded(key: Any?, load: suspend () -> T, content: @Composable (T) -> Unit) {
    val state by produceState<Result<T>?>(null, key) { value = runCatching { load() } }
    when (val s = state) {
        null -> TvMessage("Loading…")
        else -> s.fold({ content(it) }, { TvMessage(it.message ?: "Something went wrong") })
    }
}

/** Play, then show Now playing (on a TV the music is the point). */
fun TvNav.playAnd(play: () -> Unit) { play(); open(TvPage.NowPlaying) }

// --- cards ------------------------------------------------------------------------------------

@Composable
fun AlbumCard(vm: AppViewModel, nav: TvNav, a: Album) =
    TvCard(a.name, a.artist, onClick = { nav.open(TvPage.Album(a.id, a.name)) }) { Cover(vm, a.coverUrl, null, pixels = 400) }

@Composable
fun PlaylistCard(vm: AppViewModel, nav: TvNav, p: PlaylistSummary) =
    TvCard(p.name, p.description ?: "${p.count} songs", onClick = { nav.open(TvPage.Playlist(p.id, p.name)) }) {
        if (p.coverUrl != null) Cover(vm, p.coverUrl, null, pixels = 400) else Thumb(p.thumbnail, null, modifier = Modifier.fillMaxSize())
    }

@Composable
fun ItemCard(nav: TvNav, vm: AppViewModel, it: Item) =
    TvCard(it.title, it.subtitle ?: it.artistText.ifEmpty { null }, round = it.type == "artist", onClick = {
        when (it.type) {
            "album" -> nav.open(TvPage.YtAlbum(it.id, it.title))
            "playlist" -> nav.open(TvPage.YtPlaylist(it.id, it.title))
            "artist" -> nav.place(TvPage.Search).also { _ -> vm.searchRequest.value = it.title }
            else -> nav.playAnd { vm.playItems(listOf(it), it) }
        }
    }) { Thumb(it.thumbnail, null, round = it.type == "artist", modifier = Modifier.fillMaxSize()) }

// --- Home -------------------------------------------------------------------------------------

private class HomeData(
    val forYou: com.dielify.app.net.ForYou?,
    val mixes: List<PlaylistSummary>,
    val newFor: List<Item>,
    val recent: List<Album>,
    val playlists: List<PlaylistSummary>,
    val youtube: List<com.dielify.app.net.Shelf>,
)

@Composable
fun TvHome(vm: AppViewModel, nav: TvNav) {
    TvLoaded("home", {
        coroutineScope {
            val forYou = async { runCatching { vm.server.forYou() }.getOrNull() }
            val mixes = async { runCatching { vm.server.mixes().mixes }.getOrDefault(emptyList()) }
            val newFor = async { runCatching { vm.server.newReleases().items }.getOrDefault(emptyList()) }
            val recent = async { runCatching { vm.server.recentAlbums().take(24) }.getOrDefault(emptyList()) }
            val lists = async { runCatching { vm.server.playlists() }.getOrDefault(emptyList()) }
            val yt = async { runCatching { vm.server.home().shelves }.getOrDefault(emptyList()) }
            HomeData(forYou.await(), mixes.await(), newFor.await(), recent.await(),
                lists.await().filter { it.kind == "user" }, yt.await())
        }
    }) { d ->
        LazyColumn(contentPadding = PaddingValues(top = TvPadV, bottom = TvPadV * 2)) {
            d.forYou?.nowMix?.takeIf { it.tracks.isNotEmpty() }?.let { mix ->
                item {
                    val colors = mix.tracks.firstNotNullOfOrNull { it.colors }
                    Row(
                        Modifier.padding(horizontal = TvPadH).padding(bottom = 22.dp).fillMaxWidth().clip(RoundedCornerShape(18.dp))
                            .background(Brush.horizontalGradient(listOf(hexColor(colors?.bg), hexColor(colors?.bg).copy(alpha = 0.3f))))
                            .padding(24.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("MADE FOR RIGHT NOW", style = MaterialTheme.typography.labelSmall)
                            Text(mix.title, style = MaterialTheme.typography.headlineLarge, maxLines = 1)
                            Text(mix.description, style = MaterialTheme.typography.bodyMedium, maxLines = 2)
                            Spacer(Modifier.height(6.dp))
                            val first = remember { FocusRequester() }
                            TvActions {
                                TvButton("Play", Icons.Filled.PlayArrow, Modifier.focusRequester(first), primary = true) {
                                    nav.playAnd { vm.play(mix.tracks) }
                                }
                                TvButton("Shuffle", Icons.Filled.Shuffle) { nav.playAnd { vm.play(mix.tracks, shuffle = true) } }
                            }
                            LaunchedEffect(Unit) { delay(100); runCatching { first.requestFocus() } }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            mix.tracks.distinctBy { it.album }.take(3).forEach { t -> Cover(vm, t.coverUrl, 92.dp, pixels = 200) }
                        }
                    }
                }
            }
            item { TvShelf("Made for you", d.mixes, { it.id }) { PlaylistCard(vm, nav, it) } }
            item { TvShelf("New for you", d.newFor, { it.id }) { ItemCard(nav, vm, it) } }
            item { TvShelf("Recently added", d.recent, { it.id }) { AlbumCard(vm, nav, it) } }
            item { TvShelf("More like your top songs", d.forYou?.moreLike.orEmpty(), { it.id }) { ItemCard(nav, vm, it) } }
            item { TvShelf("Your playlists", d.playlists, { it.id }) { PlaylistCard(vm, nav, it) } }
            d.youtube.forEach { shelf ->
                val noSongs = shelf.items.filter { !it.isSong }
                item { TvShelf(shelf.title, noSongs, { it.id }) { ItemCard(nav, vm, it) } }
            }
        }
    }
}

// --- Library ----------------------------------------------------------------------------------

@Composable
fun TvLibrary(vm: AppViewModel, nav: TvNav) {
    var tab by rememberSaveable { mutableStateOf(0) }
    Column(Modifier.fillMaxSize().padding(top = TvPadV)) {
        Row(Modifier.padding(horizontal = TvPadH).padding(bottom = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            listOf("Albums", "Artists", "Playlists").forEachIndexed { i, label ->
                TvButton(label, primary = tab == i) { tab = i }
            }
        }
        val grid = Modifier.fillMaxSize()
        val pad = PaddingValues(horizontal = TvPadH, vertical = 16.dp)
        val gap = Arrangement.spacedBy(20.dp)
        when (tab) {
            0 -> TvLoaded("albums", { vm.server.albums() }) { list ->
                LazyVerticalGrid(GridCells.Adaptive(132.dp), grid, contentPadding = pad, horizontalArrangement = gap, verticalArrangement = gap) {
                    items(list, key = { it.id }) { AlbumCard(vm, nav, it) }
                }
            }
            1 -> TvLoaded("artists", { vm.server.artists() }) { list ->
                LazyVerticalGrid(GridCells.Adaptive(132.dp), grid, contentPadding = pad, horizontalArrangement = gap, verticalArrangement = gap) {
                    items(list, key = { it.id }) { a ->
                        TvCard(a.name, "${a.albumCount} album${if (a.albumCount == 1) "" else "s"}", round = true,
                            onClick = { nav.open(TvPage.Artist(a.id, a.name)) }) { Cover(vm, a.imageUrl ?: a.coverUrl, null, pixels = 400) }
                    }
                }
            }
            else -> TvLoaded("playlists", { vm.server.playlists() }) { list ->
                LazyVerticalGrid(GridCells.Adaptive(132.dp), grid, contentPadding = pad, horizontalArrangement = gap, verticalArrangement = gap) {
                    items(list, key = { it.id }) { PlaylistCard(vm, nav, it) }
                }
            }
        }
    }
}

// --- pages for one album / artist / playlist --------------------------------------------------

/** Big cover on the cover's colours, title, line, buttons. */
@Composable
fun TvHeader(title: String, sub: String, colors: ArtColors?, art: @Composable () -> Unit, actions: @Composable () -> Unit) {
    Row(
        Modifier.fillMaxWidth().background(tintBrush(colors, 700f)).padding(horizontal = TvPadH, vertical = TvPadV),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(150.dp).clip(RoundedCornerShape(12.dp))) { art() }
        Spacer(Modifier.width(26.dp))
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.headlineLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(sub, style = MaterialTheme.typography.bodyLarge)
            Spacer(Modifier.height(6.dp))
            actions()
        }
    }
}

@Composable
private fun FocusFirst(content: @Composable (Modifier) -> Unit) {
    val first = remember { FocusRequester() }
    content(Modifier.focusRequester(first))
    LaunchedEffect(Unit) { delay(100); runCatching { first.requestFocus() } }
}

@Composable
fun TvAlbum(vm: AppViewModel, nav: TvNav, p: TvPage.Album) {
    TvLoaded(p, { vm.server.album(p.id) }) { d ->
        val tracks = d.tracks
        LazyColumn(contentPadding = PaddingValues(bottom = TvPadV * 2)) {
            item {
                TvHeader(d.album.name, listOfNotNull(d.album.artist, d.album.year?.toString(), "${tracks.size} songs").joinToString(" · "),
                    d.album.colors, { Cover(vm, d.album.coverUrl, null, pixels = 500) }) {
                    TvActions {
                        FocusFirst { m -> TvButton("Play", Icons.Filled.PlayArrow, m, primary = true) { nav.playAnd { vm.play(tracks) } } }
                        TvButton("Shuffle", Icons.Filled.Shuffle) { nav.playAnd { vm.play(tracks, shuffle = true) } }
                        TvButton(d.album.artist) { nav.open(TvPage.Artist(d.album.artistId, d.album.artist)) }
                    }
                }
            }
            itemsIndexed(tracks, key = { _, t -> t.id }) { i, t -> TrackRow(vm, nav, tracks, i, t, showArtist = t.artist != d.album.artist) }
        }
    }
}

@Composable
private fun TrackRow(vm: AppViewModel, nav: TvNav, list: List<Track>, i: Int, t: Track, showArtist: Boolean = true) =
    Box(Modifier.padding(horizontal = TvPadH - 18.dp, vertical = 2.dp)) {
        TvSongRow(t.trackNo ?: (i + 1), t.title, if (showArtist) t.artist else "", formatDuration(t.durationS?.toLong())) {
            nav.playAnd { vm.play(list, i) }
        }
    }

@Composable
fun TvArtist(vm: AppViewModel, nav: TvNav, p: TvPage.Artist) {
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    TvLoaded(p, { vm.server.artist(p.id) }) { d ->
        val gap = Arrangement.spacedBy(20.dp)
        LazyVerticalGrid(GridCells.Adaptive(132.dp), Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = TvPadV * 2),
            horizontalArrangement = gap, verticalArrangement = gap) {
            item(span = { androidx.compose.foundation.lazy.grid.GridItemSpan(maxLineSpan) }) {
                TvHeader(d.artist.name, "${d.albums.size} album${if (d.albums.size == 1) "" else "s"} in your library", d.artist.colors,
                    { Cover(vm, d.artist.imageUrl ?: d.artist.coverUrl, null, pixels = 500) }) {
                    TvActions {
                        FocusFirst { m ->
                            TvButton("Play all", Icons.Filled.PlayArrow, m, primary = true) {
                                scope.launch {
                                    val tracks = d.albums.flatMap { a -> runCatching { vm.server.album(a.id).tracks }.getOrDefault(emptyList()) }
                                    if (tracks.isNotEmpty()) nav.playAnd { vm.play(tracks) }
                                }
                            }
                        }
                    }
                }
            }
            items(d.albums, key = { it.id }) { a -> Box(Modifier.padding(horizontal = 6.dp)) { AlbumCard(vm, nav, a) } }
        }
    }
}

@Composable
fun TvPlaylist(vm: AppViewModel, nav: TvNav, p: TvPage.Playlist) {
    TvLoaded(p, { vm.server.playlist(p.id) }) { d ->
        val items = d.entries.map { it.item }.filter { it.isSong }
        LazyColumn(contentPadding = PaddingValues(bottom = TvPadV * 2)) {
            item {
                TvHeader(d.playlist.name, d.playlist.description ?: "${items.size} songs", d.playlist.colors, {
                    if (d.playlist.coverUrl != null) Cover(vm, d.playlist.coverUrl, null, pixels = 500)
                    else Thumb(d.playlist.thumbnail, null, modifier = Modifier.fillMaxSize())
                }) {
                    TvActions {
                        FocusFirst { m ->
                            TvButton("Play", Icons.Filled.PlayArrow, m, primary = true) { if (items.isNotEmpty()) nav.playAnd { vm.playItems(items, items.first()) } }
                        }
                        TvButton("Shuffle", Icons.Filled.Shuffle) {
                            if (items.isNotEmpty()) nav.playAnd { val s = items.shuffled(); vm.playItems(s, s.first()) }
                        }
                    }
                }
            }
            itemsIndexed(items, key = { i, it -> "$i:${it.id}" }) { i, it -> ItemRow(vm, nav, items, i, it) }
        }
    }
}

@Composable
private fun ItemRow(vm: AppViewModel, nav: TvNav, list: List<Item>, i: Int, it: Item) =
    Box(Modifier.padding(horizontal = TvPadH - 18.dp, vertical = 2.dp)) {
        TvSongRow(i + 1, it.title, it.artistText, formatDuration(it.durationS?.toLong())) { nav.playAnd { vm.playItems(list, it) } }
    }

@Composable
fun TvYtCollection(vm: AppViewModel, nav: TvNav, name: String, load: suspend () -> YtCollection) {
    TvLoaded(name, load) { d ->
        val items = d.tracks.filter { it.isSong }
        LazyColumn(contentPadding = PaddingValues(bottom = TvPadV * 2)) {
            item {
                TvHeader(d.info.title, d.info.subtitle ?: d.info.artistText, null, { Thumb(d.info.thumbnail, null, modifier = Modifier.fillMaxSize()) }) {
                    TvActions {
                        FocusFirst { m ->
                            TvButton("Play", Icons.Filled.PlayArrow, m, primary = true) { if (items.isNotEmpty()) nav.playAnd { vm.playItems(items, items.first()) } }
                        }
                        TvButton("Shuffle", Icons.Filled.Shuffle) {
                            if (items.isNotEmpty()) nav.playAnd { val s = items.shuffled(); vm.playItems(s, s.first()) }
                        }
                    }
                }
            }
            itemsIndexed(items, key = { i, it -> "$i:${it.id}" }) { i, it -> ItemRow(vm, nav, items, i, it) }
        }
    }
}

// --- Search -----------------------------------------------------------------------------------

@Composable
fun TvSearch(vm: AppViewModel, nav: TvNav) {
    val asked by vm.searchRequest.collectAsStateWithLifecycle()
    var q by rememberSaveable { mutableStateOf(asked ?: "") }
    LaunchedEffect(asked) { asked?.let { q = it; vm.searchRequest.value = null } }
    var query by remember { mutableStateOf(q) }
    LaunchedEffect(q) { delay(500); query = q.trim() }
    Column(Modifier.fillMaxSize().padding(top = TvPadV)) {
        val field = remember { FocusRequester() }
        OutlinedTextField(q, { q = it }, singleLine = true, label = { Text("Search your library and YouTube Music") },
            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Search),
            keyboardActions = androidx.compose.foundation.text.KeyboardActions(onSearch = { query = q.trim() }),
            modifier = Modifier.padding(horizontal = TvPadH).width(460.dp).focusRequester(field).leaveWithArrows())
        LaunchedEffect(Unit) { if (q.isEmpty()) runCatching { field.requestFocus() } }
        if (query.length < 2) { TvMessage("Type an artist, album or song."); return@Column }
        TvLoaded(query, {
            coroutineScope {
                val lib = async { vm.server.search(query) }
                val songs = async { runCatching { vm.server.ytSearch(query, "song") }.getOrDefault(emptyList()) }
                val albums = async { runCatching { vm.server.ytSearch(query, "album") }.getOrDefault(emptyList()) }
                Triple(lib.await(), songs.await(), albums.await())
            }
        }) { (lib, songs, albums) ->
            LazyColumn(contentPadding = PaddingValues(top = 20.dp, bottom = TvPadV * 2)) {
                item { TvShelf("Your albums", lib.albums, { it.id }) { AlbumCard(vm, nav, it) } }
                item {
                    TvShelf("Your artists", lib.artists, { it.id }) { a ->
                        TvCard(a.name, null, round = true, onClick = { nav.open(TvPage.Artist(a.id, a.name)) }) {
                            Cover(vm, a.imageUrl ?: a.coverUrl, null, pixels = 400)
                        }
                    }
                }
                if (lib.tracks.isNotEmpty()) item { Text("Your songs", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = TvPadH, bottom = 6.dp)) }
                itemsIndexed(lib.tracks.take(20), key = { _, t -> "t${t.id}" }) { i, t -> TrackRow(vm, nav, lib.tracks, i, t) }
                item { Spacer(Modifier.height(24.dp)) }
                item { TvShelf("Albums on YouTube Music", albums, { it.id }) { ItemCard(nav, vm, it) } }
                if (songs.isNotEmpty()) item { Text("Songs on YouTube Music", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = TvPadH, bottom = 6.dp)) }
                itemsIndexed(songs, key = { i, it -> "y$i${it.id}" }) { i, it -> ItemRow(vm, nav, songs, i, it) }
            }
        }
    }
}

// --- Settings ---------------------------------------------------------------------------------

@Composable
fun TvSettings(vm: AppViewModel) {
    val account by vm.account.collectAsStateWithLifecycle()
    val link by vm.server.link.collectAsStateWithLifecycle()
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = TvPadH, vertical = TvPadV),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("Settings", style = MaterialTheme.typography.headlineLarge) }
        item { Line("Plays the music of", account?.profile ?: "") }
        item { Line("Your PC", when (val l = link) { is Link.Up -> l.address; Link.Down -> "Can't reach it right now"; Link.Unknown -> "…" }) }
        item { Line("App version", BuildConfig.VERSION_NAME) }
        item { Column(Modifier.width(420.dp)) { UpdateSection(vm) } }
        item {
            Text("To sign this TV out (or sign it in for someone else), sign out here, then scan the new code with a parent's phone.",
                color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(560.dp))
        }
        item { TvButton("Sign out of this TV") { vm.signOut() } }
    }
}

@Composable
private fun Line(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.titleMedium)
    }
}
