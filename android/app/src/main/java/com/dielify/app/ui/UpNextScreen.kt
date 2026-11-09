package com.dielify.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.PlaylistPlay
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DragHandle
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.zIndex
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Radio
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/** The Up next button (Now playing). */
@Composable
fun UpNextButton(vm: AppViewModel) {
    IconButton(onClick = { vm.showUpNext.value = true }) {
        Icon(Icons.AutoMirrored.Filled.QueueMusic, "Up next")
    }
}

/** Play next / Add to queue (and Start radio), for a song's ⋮ menu. */
@Composable
fun QueueMenuItems(close: () -> Unit, radio: (() -> Unit)? = null, add: (next: Boolean) -> Unit) {
    DropdownMenuItem(text = { Text("Play next") }, leadingIcon = { Icon(Icons.AutoMirrored.Filled.PlaylistPlay, null) },
        onClick = { close(); add(true) })
    DropdownMenuItem(text = { Text("Add to queue") }, leadingIcon = { Icon(Icons.AutoMirrored.Filled.QueueMusic, null) },
        onClick = { close(); add(false) })
    if (radio != null) DropdownMenuItem(text = { Text("Start radio") },
        leadingIcon = { Icon(Icons.Filled.Radio, null) },
        onClick = { close(); radio() })
}

/** Up next: the song playing now and the ones coming up. Tap one to play it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UpNextSheet(vm: AppViewModel) {
    val open by vm.showUpNext.collectAsStateWithLifecycle()
    if (!open) return
    val q by vm.upNext.collectAsStateWithLifecycle()
    val playingOn by vm.playingOn.collectAsStateWithLifecycle()
    val drag = remember { DragState() }
    ModalBottomSheet(onDismissRequest = { vm.showUpNext.value = false },
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxHeight(0.9f).navigationBarsPadding()) {
            Row(Modifier.fillMaxWidth().padding(start = 24.dp, end = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Up next", style = MaterialTheme.typography.titleLarge)
                    if (playingOn != null) Text("On $playingOn", style = MaterialTheme.typography.bodySmall, color = ConnectGreen)
                }
                if (q.next.isNotEmpty()) TextButton(onClick = { vm.queueClear() }) { Text("Clear") }
            }
            LazyColumn(Modifier.fillMaxWidth()) {
                q.now?.let { now ->
                    item(key = "label-now") { Label("Now playing") }
                    item(key = "now") { Entry(vm, now, isNow = true) }
                }
                if (q.next.isNotEmpty()) {
                    item(key = "label-next") {
                        Label("Next · ${q.next.size} ${if (q.next.size == 1) "song" else "songs"}${if (q.shuffled) " · shuffled" else ""}")
                    }
                    itemsIndexed(q.next, key = { i, e -> "n$i-${e.index}" }) { i, e ->
                        val dragged = drag.from == i
                        val target = drag.target(q.next.size)
                        Box(
                            Modifier.zIndex(if (dragged) 1f else 0f).graphicsLayer {
                                translationY = when {
                                    dragged -> drag.offset
                                    drag.from in 0 until i && i <= target -> -drag.rowPx
                                    drag.from > i && i >= target && drag.from >= 0 -> drag.rowPx
                                    else -> 0f
                                }
                            }.background(if (dragged) MaterialTheme.colorScheme.surfaceVariant else Color.Transparent)
                                .onSizeChanged { if (it.height > 0) drag.rowPx = it.height.toFloat() },
                        ) {
                            Entry(vm, e, isNow = false, handle = Modifier.pointerInput(e.index, i) {
                                detectDragGestures(
                                    onDragStart = { drag.from = i; drag.offset = 0f },
                                    onDrag = { change, amount -> change.consume(); drag.offset += amount.y },
                                    onDragEnd = { val t = drag.target(q.next.size); val f = drag.from; drag.reset(); vm.queueMove(f, t) },
                                    onDragCancel = { drag.reset() },
                                )
                            })
                        }
                    }
                } else if (q.now != null) item(key = "empty") {
                    Text("Nothing after this song. Use Play next or Add to queue in any song's ⋮ menu.",
                        Modifier.padding(24.dp), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (q.now == null) item(key = "nothing") {
                    Text("Nothing playing.", Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun Label(text: String) {
    Text(text.uppercase(), Modifier.padding(start = 24.dp, top = 12.dp, bottom = 4.dp),
        style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

/** A row being dragged in Up next: where it started and how far it has moved. */
private class DragState {
    var from by mutableIntStateOf(-1)
    var offset by mutableFloatStateOf(0f)
    var rowPx = 1f
    fun target(size: Int) = if (from < 0) -1 else (from + Math.round(offset / rowPx)).coerceIn(0, size - 1)
    fun reset() { from = -1; offset = 0f }
}

@Composable
private fun Entry(vm: AppViewModel, e: QueueEntry, isNow: Boolean, handle: Modifier = Modifier) {
    val color = if (isNow) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
    Row(
        Modifier.fillMaxWidth().clickable(enabled = !isNow) { vm.queueJump(e.index) }
            .padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Thumb(e.art, 44.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(e.title, maxLines = 1, overflow = TextOverflow.Ellipsis, color = color)
            Text(e.artist, maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (isNow) {
            Icon(Icons.Filled.GraphicEq, "Playing", Modifier.padding(12.dp), tint = MaterialTheme.colorScheme.primary)
        } else {
            Icon(Icons.Filled.DragHandle, "Drag to move", handle.padding(12.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
            IconButton(onClick = { vm.queuePlayNext(e.index) }) { Icon(Icons.AutoMirrored.Filled.PlaylistPlay, "Play next") }
            IconButton(onClick = { vm.queueRemove(e.index) }) { Icon(Icons.Filled.Close, "Remove from the queue") }
        }
    }
}
