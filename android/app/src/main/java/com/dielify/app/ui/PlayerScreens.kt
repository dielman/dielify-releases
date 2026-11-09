package com.dielify.app.ui

import kotlin.math.roundToInt
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.draw.clip
import androidx.compose.material3.Surface
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.animation.core.tween
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistAdd
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Radio
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.media3.common.Player
import com.dielify.app.BuildConfig
import com.dielify.app.dielify
import com.dielify.app.net.Link
import com.dielify.app.update.UpdateState
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private fun coverPath(trackId: Long?) = trackId?.let { "/api/library/tracks/$it/cover" }

/** The bar above the tabs: the song in its cover's colour, a progress line, swipe to skip. */
@Composable
fun MiniPlayer(vm: AppViewModel) {
    val p by vm.player.collectAsStateWithLifecycle()
    if (!p.hasItem) return
    var progress by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(Unit) {
        while (true) {
            vm.controller?.let { c -> val d = c.duration; progress = if (d > 0) c.currentPosition.toFloat() / d else 0f }
            delay(500)
        }
    }
    val tint by animateColorAsState(hexColor(p.colorBg, MaterialTheme.colorScheme.surfaceContainerHigh), tween(500), label = "mini")
    var dragX by remember { mutableFloatStateOf(0f) }
    Surface(color = tint, shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp)) {
        Column {
            Row(
                Modifier.fillMaxWidth().clickable { vm.open(Screen.NowPlaying) }
                    .offset { IntOffset(dragX.roundToInt(), 0) }
                    .pointerInput(p.title) {
                        detectHorizontalDragGestures(
                            onDragEnd = { if (dragX < -120) vm.next() else if (dragX > 120) vm.previous(); dragX = 0f },
                            onDragCancel = { dragX = 0f },
                        ) { _, d -> dragX += d }
                    }
                    .padding(start = 8.dp, end = 4.dp, top = 8.dp, bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Cover(vm, coverPath(p.trackId), 44.dp, pixels = 150)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(p.title, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleSmall)
                    Text(
                        p.error ?: p.artist, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (p.error != null) MaterialTheme.colorScheme.error else Color.White.copy(alpha = 0.7f),
                    )
                }
                DevicesButton(vm)
                PlayPauseIcon(vm, p)
                IconButton(onClick = { vm.next() }, enabled = p.hasNext) { Icon(Icons.Filled.SkipNext, "Next") }
            }
            Box(Modifier.fillMaxWidth().padding(horizontal = 12.dp).height(2.dp).clip(RoundedCornerShape(1.dp)).background(Color.White.copy(alpha = 0.18f))) {
                Box(Modifier.fillMaxWidth(progress.coerceIn(0f, 1f)).fillMaxHeight().background(Color.White))
            }
            Spacer(Modifier.height(6.dp))
        }
    }
}

@Composable
private fun PlayPauseIcon(vm: AppViewModel, p: PlayerUi) {
    IconButton(onClick = { vm.togglePlay() }) {
        when {
            p.buffering -> CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = Color.White)
            p.isPlaying -> Icon(Icons.Filled.Pause, "Pause")
            else -> Icon(Icons.Filled.PlayArrow, "Play")
        }
    }
}

/** Now playing: the whole screen in the song's colours. Swipe the cover for the next or
 *  previous song; swipe down (or Back) to close. */
@Composable
fun NowPlayingScreen(vm: AppViewModel) {
    val p by vm.player.collectAsStateWithLifecycle()
    var position by remember { mutableLongStateOf(0L) }
    var duration by remember { mutableLongStateOf(0L) }
    var dragging by remember { mutableStateOf(false) }
    var dragValue by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(Unit) {
        while (true) {
            vm.controller?.let { c ->
                if (!dragging) position = c.currentPosition
                duration = c.duration.takeIf { it > 0 } ?: 0L
            }
            delay(500)
        }
    }
    val tint by animateColorAsState(hexColor(p.colorBg, Color(0xFF23262C)), tween(600), label = "np-bg")
    val hue by animateColorAsState(hexColor(p.colorAccent, Accent), tween(600), label = "np-hue")
    var dragY by remember { mutableFloatStateOf(0f) }
    Box(
        Modifier.fillMaxSize().background(Bg)
            .offset { IntOffset(0, dragY.roundToInt()) }
            .background(Brush.verticalGradient(listOf(lerp(tint, hue, 0.35f), tint, Bg)))
            .pointerInput(Unit) {
                detectVerticalDragGestures(
                    onDragEnd = { if (dragY > 240) vm.back(); dragY = 0f },
                    onDragCancel = { dragY = 0f },
                ) { _, d -> dragY = (dragY + d).coerceAtLeast(0f) }
            },
    ) {
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 24.dp)) {
            Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { vm.back() }) { Icon(Icons.Filled.KeyboardArrowDown, "Close", Modifier.size(30.dp)) }
                Text("NOW PLAYING", Modifier.weight(1f), textAlign = TextAlign.Center, style = MaterialTheme.typography.labelSmall,
                    color = Color.White.copy(alpha = 0.75f))
                CastButton()
                DevicesButton(vm)
            }
            PlayingOnStrip(vm)
            if (!p.hasItem) {
                Text("Nothing playing", Modifier.padding(top = 40.dp))
                return@Column
            }
            var dragX by remember { mutableFloatStateOf(0f) }
            BoxWithConstraints(Modifier.weight(1f).fillMaxWidth().padding(vertical = 16.dp), contentAlignment = Alignment.Center) {
                val side = minOf(maxWidth, maxHeight)
                Box(
                    Modifier.size(side)
                        .offset { IntOffset(dragX.roundToInt(), 0) }
                        .graphicsLayer { rotationZ = dragX / 80f; alpha = 1f - (kotlin.math.abs(dragX) / 1200f).coerceAtMost(0.4f) }
                        .pointerInput(p.title) {
                            detectHorizontalDragGestures(
                                onDragEnd = { if (dragX < -160) vm.next() else if (dragX > 160) vm.previous(); dragX = 0f },
                                onDragCancel = { dragX = 0f },
                            ) { _, d -> dragX += d }
                        }
                        .shadow(32.dp, RoundedCornerShape(16.dp)).clip(RoundedCornerShape(16.dp)),
                ) { Cover(vm, coverPath(p.trackId), side, pixels = 900) }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(p.title, style = MaterialTheme.typography.headlineSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(listOf(p.artist, p.album).filter { it.isNotBlank() }.joinToString(" · "), maxLines = 1,
                        overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyLarge, color = Color.White.copy(alpha = 0.72f))
                }
                SongThumbs(vm)
            }
            p.error?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.height(12.dp))
            ThinSeek(
                value = if (dragging) dragValue else if (duration > 0) position.toFloat() / duration else 0f,
                enabled = duration > 0,
                onChange = { dragging = true; dragValue = it },
                onDone = {
                    vm.seekTo((dragValue * duration).toLong())
                    position = (dragValue * duration).toLong()
                    dragging = false
                },
            )
            Row(Modifier.fillMaxWidth()) {
                Text(formatDuration(position / 1000), style = MaterialTheme.typography.bodySmall, color = Color.White.copy(alpha = 0.7f))
                Spacer(Modifier.weight(1f))
                Text(formatDuration(duration / 1000), style = MaterialTheme.typography.bodySmall, color = Color.White.copy(alpha = 0.7f))
            }
            Row(
                Modifier.fillMaxWidth().padding(vertical = 8.dp), horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = { vm.toggleShuffle() }) {
                    Icon(Icons.Filled.Shuffle, "Shuffle", tint = if (p.shuffle) hue else Color.White.copy(alpha = 0.7f))
                }
                IconButton(onClick = { vm.previous() }, Modifier.size(56.dp)) { Icon(Icons.Filled.SkipPrevious, "Previous", Modifier.size(40.dp)) }
                FilledIconButton(
                    onClick = { vm.togglePlay() }, modifier = Modifier.size(76.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(containerColor = Color.White, contentColor = Bg),
                ) {
                    when {
                        p.buffering -> CircularProgressIndicator(Modifier.size(30.dp), strokeWidth = 3.dp, color = Bg)
                        p.isPlaying -> Icon(Icons.Filled.Pause, "Pause", Modifier.size(42.dp))
                        else -> Icon(Icons.Filled.PlayArrow, "Play", Modifier.size(42.dp))
                    }
                }
                IconButton(onClick = { vm.next() }, enabled = p.hasNext, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Filled.SkipNext, "Next", Modifier.size(40.dp))
                }
                IconButton(onClick = { vm.cycleRepeat() }) {
                    Icon(
                        if (p.repeat == Player.REPEAT_MODE_ONE) Icons.Filled.RepeatOne else Icons.Filled.Repeat, "Repeat",
                        tint = if (p.repeat != Player.REPEAT_MODE_OFF) hue else Color.White.copy(alpha = 0.7f),
                    )
                }
            }
            Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically) {
                SleepButton(vm)
                IconButton(onClick = { vm.radioFromCurrent() }) { Icon(Icons.Filled.Radio, "Start radio from this song") }
                IconButton(onClick = { vm.pickPlaylistForCurrent() }) { Icon(Icons.AutoMirrored.Filled.PlaylistAdd, "Add to playlist") }
                UpNextButton(vm)
            }
        }
    }
}

@Composable
fun SettingsScreen(vm: AppViewModel) {
    val account by vm.account.collectAsStateWithLifecycle()
    val link by vm.server.link.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var signingOut by remember { mutableStateOf(false) }
    Page(vm, "Settings") { pad ->
        // scrolls: the playlist list under "Keep on this phone" pushes the rest (Update) far down
        Column(Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(22.dp)) {
            val a = account ?: return@Column
            SettingsSection("Playback") {
                LevelSetting()
                EqSetting()
                val cached = androidx.compose.ui.platform.LocalContext.current.dielify.songCache.cache.cacheSpace
                Setting("Kept from streaming", "${formatBytes(cached)} of 500 MB. The next 5 songs are fetched ahead, " +
                    "so short drops in reception don't stop the music.")
            }
            SettingsSection("On this phone") {
                val songs by vm.savedSongs.collectAsStateWithLifecycle()
                Setting("Saved", "${songs.size} songs \u00b7 ${formatBytes(vm.saved.totalBytes())}")
                if (songs.isNotEmpty()) OutlinedButton(onClick = { vm.saved.removeAll() }) { Text("Remove all songs from this phone") }
                KeepSettings(vm)
            }
            SettingsSection("Your taste") {
                BannedList(vm)
                TasteList(vm)
                NewReleaseSettings(vm)
            }
            SettingsSection("Your PC") {
                Setting("Signed in as", "${a.username} (music of ${a.profile})")
                Setting("Connected", when (val l = link) {
                    is Link.Up -> "${l.address} " + if (l.viaTailscale) "(Tailscale)" else "(home network)"
                    Link.Down -> "Can't reach the PC right now"
                    Link.Unknown -> "Not yet"
                })
                Setting("PC addresses", a.addresses.joinToString("\n"))
            }
            SettingsSection("About") {
                Setting("App version", BuildConfig.VERSION_NAME)
                UpdateSection(vm)
                OutlinedButton(onClick = { signingOut = true; scope.launch { vm.signOut() } }, enabled = !signingOut) {
                    Text("Sign out of this phone")
                }
                Text("Signing in again needs this phone login's password (on the PC: Settings > People & phones).",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun UpdateSection(vm: AppViewModel) {
    val state by vm.updater.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    when (val s = state) {
        UpdateState.NotSetUp -> Text(
            "Test build: updates come over USB from the PC.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        is UpdateState.Available -> Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Dielify ${s.release.version} is available (${formatBytes(s.release.size)})",
                color = MaterialTheme.colorScheme.primary)
            s.notes?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Button(onClick = {
                if (!vm.updater.canInstall()) {
                    vm.messages.tryEmit("Allow Dielify to install updates, then come back and tap Update again")
                    context.startActivity(vm.updater.openInstallPermission())
                } else scope.launch {
                    vm.updater.download(s.release)?.let { context.startActivity(it) }
                }
            }) { Text("Update") }
        }
        is UpdateState.Downloading -> Column {
            Text("Downloading ${s.release.version}… ${(s.fraction * 100).toInt()}%")
            LinearProgressIndicator(progress = { s.fraction }, modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
        }
        else -> Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                when (s) {
                    UpdateState.Checking -> "Checking for updates…"
                    UpdateState.UpToDate -> "Up to date"
                    is UpdateState.Failed -> s.message
                    else -> ""
                },
                Modifier.weight(1f), style = MaterialTheme.typography.bodySmall,
                color = if (s is UpdateState.Failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedButton(onClick = { scope.launch { vm.updater.check(force = true) } },
                enabled = s !is UpdateState.Checking) { Text("Check for updates") }
        }
    }
}

@Composable
private fun Setting(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value)
    }
}
