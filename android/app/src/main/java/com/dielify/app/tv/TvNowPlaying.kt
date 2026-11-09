package com.dielify.app.tv

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.media3.common.Player
import coil3.compose.AsyncImage
import com.dielify.app.ui.AppViewModel
import com.dielify.app.ui.Bg
import com.dielify.app.ui.formatDuration
import com.dielify.app.ui.hexColor
import kotlinx.coroutines.delay

// 0.9.10: Now playing on the TV: the whole screen in the song's colours, big cover, the
// controls (the remote's play/pause and skip buttons work too) and what plays next.

@Composable
fun TvNowPlaying(vm: AppViewModel, nav: TvNav) {
    val p by vm.player.collectAsStateWithLifecycle()
    val upNext by vm.upNext.collectAsStateWithLifecycle()
    val pos by produceState(0L to 0, p.title) {
        while (true) { value = vm.positionMs() to (vm.durationS() ?: 0); delay(500) }
    }
    val tint = hexColor(p.colorBg, Color(0xFF2A2230))
    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(tint, tint.copy(alpha = 0.55f), Bg)))) {
        if (!p.hasItem) { TvMessage("Nothing playing. Press Back to choose some music."); return@Box }
        Row(Modifier.fillMaxSize().padding(horizontal = TvPadH * 1.5f, vertical = TvPadV * 1.5f),
            horizontalArrangement = Arrangement.spacedBy(40.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.fillMaxHeight(0.8f).aspectRatio(1f).shadow(40.dp, RoundedCornerShape(20.dp)).clip(RoundedCornerShape(20.dp))
                .background(Color.White.copy(alpha = 0.08f))) {
                AsyncImage(upNext.now?.art, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(p.title, style = MaterialTheme.typography.headlineLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(listOf(p.artist, p.album).filter { it.isNotBlank() }.joinToString(" · "),
                    style = MaterialTheme.typography.titleMedium, color = Color.White.copy(alpha = 0.8f), maxLines = 1)
                PlayingElsewhere(vm)
                Spacer(Modifier.height(10.dp))
                val (ms, total) = pos
                val frac = if (total > 0) (ms / 1000f / total).coerceIn(0f, 1f) else 0f
                Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(Color.White.copy(alpha = 0.25f))) {
                    Box(Modifier.fillMaxWidth(frac).fillMaxHeight().background(Color.White))
                }
                Row(Modifier.fillMaxWidth()) {
                    Text(formatDuration(ms / 1000), color = Color.White.copy(alpha = 0.7f))
                    Spacer(Modifier.weight(1f))
                    Text(formatDuration(total.toLong()), color = Color.White.copy(alpha = 0.7f))
                }
                Spacer(Modifier.height(8.dp))
                val playButton = remember { FocusRequester() }
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    TvIconButton(Icons.Filled.Shuffle, "Shuffle", 40.dp) { vm.toggleShuffle() }
                    TvIconButton(Icons.Filled.SkipPrevious, "Previous", 48.dp) { vm.previous() }
                    TvIconButton(if (p.isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (p.isPlaying) "Pause" else "Play",
                        60.dp, Modifier.focusRequester(playButton)) { vm.togglePlay() }
                    TvIconButton(Icons.Filled.SkipNext, "Next", 48.dp) { vm.next() }
                    TvIconButton(if (p.repeat == Player.REPEAT_MODE_ONE) Icons.Filled.RepeatOne else Icons.Filled.Repeat, "Repeat", 40.dp) { vm.cycleRepeat() }
                }
                LaunchedEffect(Unit) { delay(150); runCatching { playButton.requestFocus() } }
                if (p.shuffle || p.repeat != Player.REPEAT_MODE_OFF) {
                    Text(listOfNotNull(if (p.shuffle) "Shuffle on" else null, when (p.repeat) {
                        Player.REPEAT_MODE_ONE -> "Repeating this song"; Player.REPEAT_MODE_ALL -> "Repeating the list"; else -> null
                    }).joinToString(" · "), color = Color.White.copy(alpha = 0.7f))
                }
                val next = upNext.next.take(4)
                if (next.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    Text("UP NEXT", style = MaterialTheme.typography.labelSmall, color = Color.White.copy(alpha = 0.6f))
                    next.forEach { e ->
                        Focusable({ vm.queueJump(e.index) }, Modifier.fillMaxWidth(), RoundedCornerShape(8.dp), 1.02f) { focused ->
                            Row(Modifier.fillMaxWidth().background(if (focused) Color.White.copy(alpha = 0.16f) else Color.Transparent)
                                .padding(horizontal = 10.dp, vertical = 5.dp)) {
                                Text(e.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f))
                                Text(e.artist, color = Color.White.copy(alpha = 0.6f), maxLines = 1, modifier = Modifier.padding(start = 12.dp))
                            }
                        }
                    }
                }
            }
        }
    }
}
