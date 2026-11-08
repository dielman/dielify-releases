package com.dielify.app.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ThumbDown
import androidx.compose.material.icons.filled.ThumbUp
import androidx.compose.material.icons.outlined.ThumbDown
import androidx.compose.material.icons.outlined.ThumbUp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.dielify
import com.dielify.app.net.ApiError
import com.dielify.app.net.Ratings
import kotlinx.coroutines.launch

/** A thumbs-down that rates on tap and calls [onHold] on a long press (ban). */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ThumbDownButton(on: Boolean, description: String, onTap: () -> Unit, onHold: () -> Unit) {
    val haptic = LocalHapticFeedback.current
    Box(
        Modifier.size(48.dp).clip(CircleShape).combinedClickable(
            onClick = onTap,
            onLongClick = { haptic.performHapticFeedback(HapticFeedbackType.LongPress); onHold() },
            onClickLabel = description, onLongClickLabel = "Ban",
        ),
        contentAlignment = Alignment.Center,
    ) {
        Icon(if (on) Icons.Filled.ThumbDown else Icons.Outlined.ThumbDown, description,
            tint = if (on) ConnectGreen else MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Thumbs for the song playing now (Now playing screen). Hold thumbs down to ban. */
@Composable
fun SongThumbs(vm: AppViewModel) {
    val p by vm.player.collectAsStateWithLifecycle()
    val ratings = androidx.compose.ui.platform.LocalContext.current.dielify.ratings
    val all by ratings.all.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var choosing by remember { mutableStateOf(false) }
    if (!p.hasItem) return
    val own = all.let { ratings.songValue(p.videoId, p.trackId) }
    val name = listOf(p.title, p.artist).filter { it.isNotEmpty() }.joinToString(" - ")
    fun rate(kind: String, label: String, value: Int, then: () -> Unit = {}) = scope.launch {
        try {
            if (kind == "song") ratings.rate("song", label, value, p.videoId, p.trackId) else ratings.rate("artist", label, value)
            then()
        } catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't save that") }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = { rate("song", name, if (own == Ratings.UP) 0 else Ratings.UP) }) {
            Icon(if (own == Ratings.UP) Icons.Filled.ThumbUp else Icons.Outlined.ThumbUp, "Thumbs up",
                tint = if (own == Ratings.UP) ConnectGreen else MaterialTheme.colorScheme.onSurfaceVariant)
        }
        ThumbDownButton(own == Ratings.DOWN, "Thumbs down (hold to ban)",
            onTap = { rate("song", name, if (own == Ratings.DOWN) 0 else Ratings.DOWN) },
            onHold = { choosing = true })
    }
    if (choosing) AlertDialog(
        onDismissRequest = { choosing = false },
        title = { Text("Never play again?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    choosing = false
                    rate("song", name, Ratings.BAN) { vm.messages.tryEmit("Banned “${p.title}”"); vm.next() }
                }, modifier = Modifier.fillMaxWidth()) { Text("This song: ${p.title}", maxLines = 1) }
                Ratings.splitArtists(p.artist).forEach { a ->
                    OutlinedButton(onClick = {
                        choosing = false
                        rate("artist", a, Ratings.BAN) { vm.messages.tryEmit("Banned $a"); vm.next() }
                    }, modifier = Modifier.fillMaxWidth()) { Text("The artist: $a", maxLines = 1) }
                }
                Text("Banned songs are skipped in every list and left out of discovery and mixes. Undo in Settings.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = { choosing = false }) { Text("Cancel") } },
    )
}

/** Thumbs for an artist (artist page). Hold thumbs down to ban the artist. */
@Composable
fun ArtistThumbs(vm: AppViewModel, name: String) {
    val ratings = androidx.compose.ui.platform.LocalContext.current.dielify.ratings
    val all by ratings.all.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    val v = all.let { ratings.artistValue(name) }
    fun rate(value: Int, msg: String? = null) = scope.launch {
        try { ratings.rate("artist", name, value); msg?.let { vm.messages.tryEmit(it) } }
        catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't save that") }
    }
    Row(Modifier.padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = { rate(if (v == Ratings.UP) 0 else Ratings.UP) }) {
            Icon(if (v == Ratings.UP) Icons.Filled.ThumbUp else Icons.Outlined.ThumbUp, "Like this artist",
                tint = if (v == Ratings.UP) ConnectGreen else MaterialTheme.colorScheme.onSurfaceVariant)
        }
        ThumbDownButton(v == Ratings.DOWN, "Less of this artist (hold to ban)",
            onTap = { rate(if (v == Ratings.DOWN) 0 else Ratings.DOWN) },
            onHold = { rate(Ratings.BAN, "Banned $name") })
        if (v == Ratings.BAN) TextButton(onClick = { rate(0, "Unbanned $name") }) { Text("Banned · unban") }
    }
}

/** Settings: what's banned, with Unban. */
@Composable
fun BannedList(vm: AppViewModel) {
    val ratings = androidx.compose.ui.platform.LocalContext.current.dielify.ratings
    val all by ratings.all.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    val bans = all.filter { it.value == Ratings.BAN }
    val ups = all.count { it.value == Ratings.UP }
    val downs = all.count { it.value == Ratings.DOWN }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Ratings", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text("$ups thumbs up · $downs thumbs down · ${bans.size} banned")
        bans.forEach { r ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${if (r.kind == "artist") "Artist" else "Song"}: ${r.name}", Modifier.weight(1f), maxLines = 2)
                TextButton(onClick = {
                    scope.launch {
                        try {
                            if (r.kind == "artist") ratings.rate("artist", r.name, 0)
                            else ratings.rate("song", r.name, 0, r.key.takeUnless { it.startsWith("tr-") },
                                r.key.removePrefix("tr-").toLongOrNull()?.takeIf { r.key.startsWith("tr-") })
                            vm.messages.tryEmit("Unbanned ${r.name}")
                        } catch (e: ApiError) { vm.messages.tryEmit(e.message ?: "Couldn't unban") }
                    }
                }) { Text("Unban") }
            }
        }
    }
}
