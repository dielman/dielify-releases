package com.dielify.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import coil3.compose.SubcomposeAsyncImage
import com.dielify.app.net.ApiError

sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Done<T>(val value: T) : Load<T>
    data class Failed(val message: String) : Load<Nothing>
}

/**
 * Loads something from the PC and shows a spinner, the result, or the error with a retry
 * button. cacheMs > 0: a result loaded less than that long ago shows at once (going back to
 * a search or an album doesn't load it again).
 */
@Suppress("UNCHECKED_CAST")
@Composable
fun <T> Loaded(
    vm: AppViewModel,
    key: Any?,
    load: suspend () -> T,
    cacheMs: Long = 0,
    content: @Composable (T) -> Unit,
) {
    var attempt by remember { mutableIntStateOf(0) }
    val cacheKey = key.toString()
    var state by remember(key) {
        val hit = if (cacheMs > 0) vm.loadCache[cacheKey] else null
        mutableStateOf<Load<T>>(
            if (hit != null && System.currentTimeMillis() - hit.first < cacheMs) Load.Done(hit.second as T) else Load.Loading,
        )
    }
    // library lists load again when songs leave the library (cached ones don't need to)
    val libraryVersion by vm.libraryChanged.collectAsStateWithLifecycle()
    var loadedVersion by remember(key) { mutableIntStateOf(libraryVersion) }
    LaunchedEffect(key, attempt, if (cacheMs == 0L) libraryVersion else 0) {
        if (attempt == 0 && state is Load.Done && loadedVersion == libraryVersion) return@LaunchedEffect  // from the cache
        loadedVersion = libraryVersion
        if (state !is Load.Done) state = Load.Loading
        state = try {
            Load.Done(load()).also { if (cacheMs > 0) vm.loadCache[cacheKey] = System.currentTimeMillis() to it.value }
        } catch (e: ApiError) {
            if (e.code == 401) vm.tokenRejected()
            Load.Failed(e.message ?: "Something went wrong")
        }
    }
    when (val s = state) {
        Load.Loading -> Box(Modifier.fillMaxSize(), Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> Column(
            Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(s.message, textAlign = TextAlign.Center)
            Button(onClick = { attempt++ }) { Text("Try again") }
        }
        is Load.Done -> content(s.value)
    }
}

/** Cover art from the PC (a music note while loading or when there's none). */
@Composable
fun Cover(vm: AppViewModel, path: String?, size: Dp?, modifier: Modifier = Modifier, pixels: Int = 300) {
    // A song saved on the phone has its cover on the phone too (works with no connection).
    val local = path?.let { Regex("^/api/library/tracks/(\\d+)/cover$").find(it) }
        ?.let { vm.saved.coverFile(it.groupValues[1].toLong()) }
    val url: Any? = local ?: path?.let { vm.server.url("$it?size=$pixels") }
    val shape = RoundedCornerShape(if (size == null || size > 100.dp) 8.dp else 4.dp)
    val sized = if (size == null) modifier.fillMaxWidth().aspectRatio(1f) else modifier.size(size)
    val placeholder = @Composable {
        Box(
            Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceVariant),
            Alignment.Center,
        ) { Icon(Icons.Filled.MusicNote, null, tint = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
    Box(sized.clip(shape)) {
        if (url == null) placeholder()
        else SubcomposeAsyncImage(
            model = url,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(),
            loading = { placeholder() },
            error = { placeholder() },
        )
    }
}

fun formatDuration(seconds: Long?): String {
    if (seconds == null || seconds < 0) return ""
    val h = seconds / 3600
    val m = (seconds % 3600) / 60
    val s = seconds % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}
