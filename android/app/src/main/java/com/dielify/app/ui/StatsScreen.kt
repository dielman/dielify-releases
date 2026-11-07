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
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.dielify.app.net.Item
import com.dielify.app.net.Stats
import java.text.DateFormat
import java.util.Date

private val periods = listOf("week" to "This week", "month" to "This month", "year" to "This year", "all" to "All time")

@Composable
fun StatsScreen(vm: AppViewModel) {
    var period by rememberSaveable { mutableStateOf("month") }
    Page(vm, "Your stats") { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            Row(
                Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                periods.forEach { (p, label) ->
                    FilterChip(selected = period == p, onClick = { period = p }, label = { Text(label) })
                }
            }
            Loaded(vm, period, { vm.server.stats(period) }) { st -> StatsBody(vm, st) }
        }
    }
}

@Composable
private fun StatsBody(vm: AppViewModel, st: Stats) {
    if (st.plays == 0) {
        Box(Modifier.fillMaxSize().padding(32.dp), Alignment.Center) {
            Text(
                if (st.historyStarts == null) "No plays recorded yet. Your history starts with the next song you play."
                else "Nothing played in this period.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Big(Modifier.weight(1f), hours(st.minutes), "listened")
                Big(Modifier.weight(1f), st.plays.toString(), "plays")
                Big(Modifier.weight(1f), st.songs.toString(), "songs")
                Big(Modifier.weight(1f), st.artists.toString(), "artists")
            }
        }
        item { HourChart(st.byHour) }
        item { Heading("Top songs") }
        itemsIndexed(st.topSongs, key = { i, s -> "s$i" + s.title }) { i, s ->
            StatRow(vm, i + 1, s.coverUrl, s.thumbnail, s.title, listOfNotNull(s.artist, s.album).joinToString(" · "),
                "${s.plays}×") {
                // play from here: library songs from the file, others straight from YouTube
                val items = st.topSongs.mapNotNull { x ->
                    x.videoId?.let { Item("song", it, x.title, listOfNotNull(x.artist), x.album, thumbnail = x.thumbnail,
                        libraryTrackId = x.trackId) }
                }
                val first = items.firstOrNull { it.id == s.videoId }
                if (first != null) vm.openItem(first, items)
                else s.trackId?.let { vm.playLibrary(listOf(it)) }
            }
        }
        item { Heading("Top artists") }
        itemsIndexed(st.topArtists, key = { i, a -> "a$i" + a.name }) { i, a ->
            StatRow(vm, i + 1, a.coverUrl, null, a.name, "${a.minutes} min", "${a.plays}×") {
                a.artistId?.let { vm.open(Screen.ArtistPage(it, a.name)) }
            }
        }
        item { Heading("Top albums") }
        itemsIndexed(st.topAlbums, key = { i, a -> "al$i" + a.name }) { i, a ->
            StatRow(vm, i + 1, a.coverUrl, null, a.name, a.artist ?: "", "${a.plays}×") {
                a.albumId?.let { vm.open(Screen.AlbumPage(it, a.name)) }
            }
        }
        item {
            Text(
                listOfNotNull(
                    "${st.skips} skipped (under half a song) not counted.",
                    st.historyStarts?.let { "History since " + DateFormat.getDateInstance().format(Date((it * 1000).toLong())) + "." },
                ).joinToString(" "),
                Modifier.padding(16.dp), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private fun hours(minutes: Int) = if (minutes < 120) "$minutes min" else "${minutes / 60} h"

@Composable
private fun Big(modifier: Modifier, value: String, label: String) {
    Column(
        modifier.clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.surfaceContainerHigh).padding(10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, maxLines = 1)
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun HourChart(byHour: List<Int>) {
    val max = (byHour.maxOrNull() ?: 0).coerceAtLeast(1)
    Column(Modifier.padding(horizontal = 16.dp)) {
        Text("When you listen", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth().height(80.dp), verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(2.dp)) {
            byHour.forEach { n ->
                Box(
                    Modifier.weight(1f).fillMaxHeight(fraction = (n.toFloat() / max).coerceAtLeast(0.02f))
                        .clip(RoundedCornerShape(topStart = 2.dp, topEnd = 2.dp))
                        .background(if (n > 0) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant)
                )
            }
        }
        Row(Modifier.fillMaxWidth()) {
            listOf("12am", "6am", "12pm", "6pm").forEach {
                Text(it, Modifier.weight(1f), style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun Heading(text: String) = Text(
    text, style = MaterialTheme.typography.titleMedium,
    modifier = Modifier.padding(start = 16.dp, top = 20.dp, bottom = 4.dp),
)

@Composable
private fun StatRow(
    vm: AppViewModel, rank: Int, cover: String?, thumbnail: String?, title: String, subtitle: String,
    count: String, onClick: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("$rank", Modifier.width(28.dp), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (cover != null || thumbnail == null) Cover(vm, cover, 44.dp, pixels = 150) else Thumb(thumbnail, 44.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (subtitle.isNotEmpty()) Text(subtitle, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Text(count, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
    }
}
