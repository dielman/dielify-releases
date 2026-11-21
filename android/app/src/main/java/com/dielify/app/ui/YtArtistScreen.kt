package com.dielify.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Radio
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.dielify.app.net.RadioIn

/**
 * A YouTube Music artist (Josh, 21 Nov 2026: tapping an artist in search only searched their name
 * again). Top songs, radio, albums, singles, fans also like; like / less / never play; follow.
 */
@Composable
fun YtArtistScreen(vm: AppViewModel, page: Screen.YtArtistPage) {
    Page(vm, page.name) { pad ->
        Box(Modifier.padding(pad)) {
            Loaded(vm, "yt-artist:${page.id}", { vm.server.ytArtist(page.id) }, cacheMs = 5 * 60_000) { a ->
                LazyColumn(Modifier.fillMaxSize()) {
                    item {
                        PageHeader(vm, "Artist", a.name, null, null, thumbnail = a.thumbnail, round = true) {
                            if (a.topSongs.isNotEmpty()) BigPlay(icon = Icons.Filled.PlayArrow, label = "Play top songs") {
                                vm.playItems(a.topSongs, a.topSongs.first())
                            }
                            if (a.hasRadio) BigPlay(icon = Icons.Filled.Radio, label = "Artist radio") {
                                vm.startRadio(RadioIn(artistId = a.id), "${a.name} radio")
                            }
                            FollowButton(vm, a.name)
                        }
                        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            ArtistThumbs(vm, a.name)
                            a.libraryArtistId?.let { id ->
                                OutlinedButton(onClick = { vm.open(Screen.ArtistPage(id, a.name)) }) {
                                    Icon(Icons.Filled.LibraryMusic, null); Text("  In your library")
                                }
                            }
                        }
                        a.description?.let { AboutText(it) }
                    }
                    if (a.topSongs.isNotEmpty()) {
                        item {
                            Row(Modifier.fillMaxWidth().padding(start = 16.dp, top = 16.dp, end = 8.dp),
                                verticalAlignment = Alignment.CenterVertically) {
                                Text("Top songs", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                                a.allSongsPlaylist?.let { pl ->
                                    TextButton(onClick = { vm.open(Screen.YtPlaylistPage(pl, "${a.name}: top songs")) }) { Text("See all") }
                                }
                            }
                        }
                        items(a.topSongs, key = { "s" + it.id }) { ItemRow(vm, it, a.topSongs) }
                    }
                    item {
                        ShelfRow(vm, "Albums", a.albums)
                        ShelfRow(vm, "Singles and EPs", a.singles)
                        ShelfRow(vm, "Fans also like", a.related)
                    }
                }
            }
        }
    }
}

@Composable
private fun AboutText(text: String) {
    var open by remember { mutableStateOf(false) }
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = if (open) Int.MAX_VALUE else 3, overflow = TextOverflow.Ellipsis)
        TextButton(onClick = { open = !open }) { Text(if (open) "Less" else "More") }
    }
}
