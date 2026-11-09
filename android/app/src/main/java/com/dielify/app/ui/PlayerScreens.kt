package com.dielify.app.ui

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

@Composable
fun MiniPlayer(vm: AppViewModel) {
    val p by vm.player.collectAsStateWithLifecycle()
    if (!p.hasItem) return
    Row(
        Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerHigh)
            .clickable { vm.open(Screen.NowPlaying) }
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Cover(vm, coverPath(p.trackId), 44.dp, pixels = 150)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(p.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                p.error ?: p.artist, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall,
                color = if (p.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        DevicesButton(vm)
        PlayPauseIcon(vm, p)
        IconButton(onClick = { vm.next() }, enabled = p.hasNext) { Icon(Icons.Filled.SkipNext, "Next") }
    }
}

@Composable
private fun PlayPauseIcon(vm: AppViewModel, p: PlayerUi) {
    IconButton(onClick = { vm.togglePlay() }) {
        when {
            p.buffering -> CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
            p.isPlaying -> Icon(Icons.Filled.Pause, "Pause")
            else -> Icon(Icons.Filled.PlayArrow, "Play")
        }
    }
}

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
    // No mini player here, and the cover takes only the room that's left: the controls
    // always fit on the screen, whatever its height (the green bar sits in the top bar).
    Page(vm, "Now playing", mini = false, actions = { DevicesButton(vm) }) { pad ->
        Column(
            Modifier.padding(pad).fillMaxSize().navigationBarsPadding().padding(horizontal = 24.dp, vertical = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            if (!p.hasItem) {
                Text("Nothing playing")
                return@Column
            }
            BoxWithConstraints(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Cover(vm, coverPath(p.trackId), minOf(maxWidth, maxHeight), pixels = 900)
            }
            Spacer(Modifier.height(16.dp))
            Text(p.title, style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
            Text(p.artist, color = MaterialTheme.colorScheme.primary, textAlign = TextAlign.Center)
            Text(
                p.album, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                SongThumbs(vm)
                SleepButton(vm)
                LyricsButton(vm)
                IconButton(onClick = { vm.radioFromCurrent() }) { Icon(Icons.Filled.Radio, "Start radio from this song") }
                UpNextButton(vm)
            }
            p.error?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
            }
            Spacer(Modifier.height(16.dp))
            Slider(
                value = if (dragging) dragValue else if (duration > 0) position.toFloat() / duration else 0f,
                onValueChange = { dragging = true; dragValue = it },
                onValueChangeFinished = {
                    vm.seekTo((dragValue * duration).toLong())
                    position = (dragValue * duration).toLong()
                    dragging = false
                },
                enabled = duration > 0,
            )
            Row(Modifier.fillMaxWidth()) {
                Text(formatDuration(position / 1000), style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.weight(1f))
                Text(formatDuration(duration / 1000), style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(8.dp))
            Row(
                Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = { vm.toggleShuffle() }) {
                    Icon(
                        Icons.Filled.Shuffle, "Shuffle",
                        tint = if (p.shuffle) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                IconButton(onClick = { vm.previous() }) { Icon(Icons.Filled.SkipPrevious, "Previous", Modifier.size(36.dp)) }
                FilledIconButton(onClick = { vm.togglePlay() }, modifier = Modifier.size(72.dp)) {
                    when {
                        p.buffering -> CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
                        p.isPlaying -> Icon(Icons.Filled.Pause, "Pause", Modifier.size(40.dp))
                        else -> Icon(Icons.Filled.PlayArrow, "Play", Modifier.size(40.dp))
                    }
                }
                IconButton(onClick = { vm.next() }, enabled = p.hasNext) {
                    Icon(Icons.Filled.SkipNext, "Next", Modifier.size(36.dp))
                }
                IconButton(onClick = { vm.pickPlaylistForCurrent() }) {
                    Icon(Icons.AutoMirrored.Filled.PlaylistAdd, "Add to playlist")
                }
                IconButton(onClick = { vm.cycleRepeat() }) {
                    Icon(
                        if (p.repeat == Player.REPEAT_MODE_ONE) Icons.Filled.RepeatOne else Icons.Filled.Repeat,
                        "Repeat",
                        tint = if (p.repeat != Player.REPEAT_MODE_OFF) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
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
        Column(Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            val a = account ?: return@Column
            Setting("Signed in as", "${a.username} (music of ${a.profile})")
            Setting("PC addresses", a.addresses.joinToString("\n"))
            Setting("Connected", when (val l = link) {
                is Link.Up -> "${l.address} " + if (l.viaTailscale) "(Tailscale)" else "(home network)"
                Link.Down -> "Can't reach the PC right now"
                Link.Unknown -> "Not yet"
            })
            val songs by vm.savedSongs.collectAsStateWithLifecycle()
            Setting("Saved on this phone", "${songs.size} songs · ${formatBytes(vm.saved.totalBytes())}")
            if (songs.isNotEmpty()) OutlinedButton(onClick = { vm.saved.removeAll() }) {
                Text("Remove all songs from this phone")
            }
            LevelSetting()
            KeepSettings(vm)
            BannedList(vm)
            TasteList(vm)
            NewReleaseSettings(vm)
            val cached = androidx.compose.ui.platform.LocalContext.current.dielify.songCache.cache.cacheSpace
            Setting("Kept from streaming", "${formatBytes(cached)} (up to 500 MB). The next 5 songs " +
                "of whatever is playing are fetched ahead, so short reception drops don't stop the music.")
            Setting("App version", BuildConfig.VERSION_NAME)
            UpdateSection(vm)
            OutlinedButton(
                onClick = { signingOut = true; scope.launch { vm.signOut() } },
                enabled = !signingOut,
            ) { Text("Sign out of this phone") }
            Text(
                "Signing out removes this phone's access on the PC. To sign in again you need the " +
                    "phone login's password (Dielify on the PC: Settings > Phone logins).",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
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
