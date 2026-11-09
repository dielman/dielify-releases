package com.dielify.app.tv

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.AsyncImage
import com.dielify.app.dielify
import com.dielify.app.ui.AppViewModel
import com.dielify.app.ui.Bg
import com.dielify.app.ui.hexColor
import kotlinx.coroutines.delay

// 0.9.10 step 3: the TV with other people. The Jam (one queue everyone adds to from their
// phone or the PC, this TV plays it), "Playing on <phone>" with Play here, and the slow cover
// display when nobody has touched the remote for a while.

@Composable
fun TvJam(vm: AppViewModel) {
    val jam by vm.jam.collectAsStateWithLifecycle()
    val account by vm.account.collectAsStateWithLifecycle()
    val first = remember { FocusRequester() }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = TvPadH, vertical = TvPadV),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        val j = jam
        if (j == null) {
            item { Text("Jam", style = MaterialTheme.typography.headlineLarge) }
            item {
                Text("One queue for everyone in the shed. This TV plays the music; everyone at home adds songs " +
                    "from their phone (any song's ⋮ menu: Add to Jam) or the PC.",
                    style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.width(560.dp))
            }
            item { TvButton("Start a Jam on this TV", Icons.Filled.Groups, Modifier.focusRequester(first), primary = true) { vm.startJam() } }
        } else {
            item { Text(if (j.youHost) "Your Jam" else "${j.host}'s Jam", style = MaterialTheme.typography.headlineLarge) }
            item {
                Text("Playing on ${j.device} · ${j.members.joinToString(", ")}", style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            item {
                TvActions {
                    val me = account?.profile
                    if (!j.youHost && j.members.none { it.equals(me, true) }) {
                        TvButton("Join", modifier = Modifier.focusRequester(first), primary = true) { vm.joinJam() }
                        TvButton("Leave") { vm.leaveJam(false) }
                    } else {
                        TvButton(if (j.youHost) "End the Jam" else "Leave", modifier = Modifier.focusRequester(first)) { vm.leaveJam(j.youHost) }
                    }
                }
            }
            item { Spacer(Modifier.height(6.dp)) }
            val coming = j.songs.drop(j.index.coerceAtLeast(0))
            if (coming.isEmpty()) item { Text("Nothing queued yet. Add songs from a phone or the PC.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            itemsIndexed(coming, key = { _, s -> s.id }) { i, s ->
                Row(Modifier.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(if (i == 0) "Now" else "$i", Modifier.width(48.dp),
                        color = if (i == 0) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    Column(Modifier.weight(1f)) {
                        Text(s.item.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("${s.item.artistText} · added by ${s.addedBy}", style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                    }
                }
            }
        }
    }
    LaunchedEffect(jam == null) { delay(100); runCatching { first.requestFocus() } }
}

/** On Now playing: the music is on another device right now (Spotify-Connect style). */
@Composable
fun PlayingElsewhere(vm: AppViewModel) {
    val on by vm.playingOn.collectAsStateWithLifecycle()
    val name = on ?: return
    val remote = LocalContext.current.dielify.remote
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Playing on $name", style = MaterialTheme.typography.titleSmall, color = Color(0xFF7CE38B))
        TvButton("Play here") { remote.select(remote.deviceId) }
    }
}

/** The slow cover display: big blurred colour, the cover drifting, the song's name. Any key closes it. */
@Composable
fun TvIdle(vm: AppViewModel) {
    val p by vm.player.collectAsStateWithLifecycle()
    val upNext by vm.upNext.collectAsStateWithLifecycle()
    val t = rememberInfiniteTransition(label = "idle")
    val drift by t.animateFloat(-1f, 1f, infiniteRepeatable(tween(40_000, easing = LinearEasing), RepeatMode.Reverse), label = "drift")
    val zoom by t.animateFloat(1f, 1.08f, infiniteRepeatable(tween(26_000, easing = LinearEasing), RepeatMode.Reverse), label = "zoom")
    val tint = hexColor(p.colorBg, Color(0xFF2A2230))
    Box(Modifier.fillMaxSize().background(Bg)) {
        AsyncImage(upNext.now?.art, null, Modifier.fillMaxSize().blur(60.dp).alpha(0.55f), contentScale = ContentScale.Crop)
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(tint.copy(alpha = 0.35f), Bg.copy(alpha = 0.85f)))))
        Box(
            Modifier.align(Alignment.Center).size(300.dp)
                .graphicsLayer { translationX = drift * 120f; translationY = -drift * 40f; scaleX = zoom; scaleY = zoom }
                .shadow(50.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)),
        ) { AsyncImage(upNext.now?.art, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop) }
        Column(Modifier.align(Alignment.BottomStart).padding(horizontal = TvPadH * 1.5f, vertical = TvPadV * 1.5f)) {
            Text(p.title, style = MaterialTheme.typography.headlineLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(listOf(p.artist, p.album).filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.titleMedium,
                color = Color.White.copy(alpha = 0.75f), maxLines = 1)
        }
    }
}
