package com.dielify.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.dielify
import com.dielify.app.net.Lyrics
import com.dielify.app.net.LyricsStore
import kotlinx.coroutines.delay

@Composable
fun LyricsButton(vm: AppViewModel) {
    IconButton(onClick = { vm.showLyrics.value = true }) { Icon(Icons.Filled.Mic, "Lyrics") }
}

/** Lyrics for the song playing, scrolling along with it. Tap a line to jump there. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LyricsSheet(vm: AppViewModel) {
    val open by vm.showLyrics.collectAsStateWithLifecycle()
    if (!open) return
    val p by vm.player.collectAsStateWithLifecycle()
    val store = LocalContext.current.dielify.lyrics
    val song = LyricsStore.Song(p.videoId, p.trackId, p.title, p.artist.ifEmpty { null }, p.album.ifEmpty { null }, vm.durationS())
    var lyrics by remember { mutableStateOf<Lyrics?>(null) }
    var loading by remember { mutableStateOf(true) }
    LaunchedEffect(song.key) {
        loading = true
        lyrics = store.cached(song) ?: store.get(song)
        loading = false
    }
    var pos by remember { mutableLongStateOf(0L) }
    LaunchedEffect(Unit) { while (true) { pos = vm.positionMs(); delay(200) } }
    val lines = lyrics?.lines.orEmpty()
    val current = if (lyrics?.synced == true) lines.indexOfLast { it.ms <= pos + 200 } else -1
    val list = rememberLazyListState()
    val third = with(androidx.compose.ui.platform.LocalDensity.current) { (LocalConfiguration.current.screenHeightDp / 3).dp.roundToPx() }
    LaunchedEffect(current) { if (current >= 0) list.animateScrollToItem(current + 1, -third) }
    ModalBottomSheet(onDismissRequest = { vm.showLyrics.value = false },
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxHeight(0.92f).navigationBarsPadding()) {
            Column(Modifier.padding(horizontal = 24.dp)) {
                Text(p.title, style = MaterialTheme.typography.titleMedium, maxLines = 1)
                Text(p.artist, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
            }
            Box(Modifier.fillMaxWidth()) {
                when {
                    loading -> Text("Looking for lyrics…", Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    lyrics == null -> Text("No lyrics for this song (or your PC can't be reached).", Modifier.padding(24.dp),
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else -> LazyColumn(state = list, contentPadding = PaddingValues(start = 24.dp, end = 24.dp, top = 24.dp, bottom = 300.dp)) {
                        item { }
                        if (lyrics!!.synced) itemsIndexed(lines) { i, l ->
                            Text(
                                l.text.ifEmpty { "♪" },
                                Modifier.fillMaxWidth().clickable { vm.seekTo(l.ms) }.padding(vertical = 8.dp),
                                fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.Bold,
                                color = when {
                                    i == current -> MaterialTheme.colorScheme.onSurface
                                    i < current -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.45f)
                                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                                },
                            )
                        } else item {
                            Text(lyrics!!.text, fontSize = 18.sp, lineHeight = 26.sp)
                        }
                        lyrics!!.source?.let { s ->
                            item { Text("Lyrics: $s", Modifier.padding(top = 24.dp), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        }
                    }
                }
            }
        }
    }
}
