package com.dielify.app.playback

import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.CacheWriter
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import com.dielify.app.saved.SavedSongs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runInterruptible
import java.io.File

/**
 * Songs streamed from the PC are kept on the phone for a while (most recently played
 * first out), and the next few songs in the play list are fetched ahead, so a short
 * loss of reception (a tunnel, a bike ride out of coverage) doesn't stop the music.
 *
 * The cache is keyed by the "dielify://server/..." address, not the real one, so a song
 * cached at home still plays from the cache over Tailscale or with no connection at all:
 * the PC's address is only looked up when a byte is actually missing.
 */
@OptIn(UnstableApi::class)
class SongCache(context: Context) {
    val cache = SimpleCache(
        File(context.cacheDir, "songs"),
        LeastRecentlyUsedCacheEvictor(MAX_BYTES),
        StandaloneDatabaseProvider(context),
    )

    /** For the player: read from the cache, fetch (and keep) what's missing. */
    fun forPlayer(upstream: DataSource.Factory): CacheDataSource.Factory =
        CacheDataSource.Factory().setCache(cache).setUpstreamDataSourceFactory(upstream)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)

    /** For fetching ahead: waits for the player if it is reading the same song. */
    fun forPrefetch(upstream: DataSource.Factory): CacheDataSource.Factory =
        CacheDataSource.Factory().setCache(cache).setUpstreamDataSourceFactory(upstream)
            .setFlags(CacheDataSource.FLAG_BLOCK_ON_CACHE)

    fun isCached(uri: Uri): Boolean {
        val key = uri.toString()
        val length = androidx.media3.datasource.cache.ContentMetadata.getContentLength(cache.getContentMetadata(key))
        return length > 0 && cache.isCached(key, 0, length)
    }

    companion object {
        const val AHEAD = 5
        const val MAX_BYTES = 500L * 1024 * 1024
    }
}

/**
 * Keeps the next [SongCache.AHEAD] songs after the one playing fully on the phone (in
 * play order, following shuffle). Saved songs are skipped (they're on the phone anyway).
 * One song at a time; if the connection is gone, it tries again every 20 seconds.
 */
@OptIn(UnstableApi::class)
class Prefetcher(
    private val player: Player,
    private val songs: SongCache,
    private val writers: CacheDataSource.Factory,
    private val saved: SavedSongs,
    private val scope: CoroutineScope,
) : Player.Listener {
    private var job: Job? = null
    private var wanted: List<Uri> = emptyList()

    private fun upcoming(): List<Uri> {
        val timeline = player.currentTimeline
        if (timeline.isEmpty) return emptyList()
        val repeat = if (player.repeatMode == Player.REPEAT_MODE_ONE) Player.REPEAT_MODE_OFF else player.repeatMode
        val out = mutableListOf<Uri>()
        var index = player.currentMediaItemIndex
        val seen = mutableSetOf(index)
        while (out.size < SongCache.AHEAD) {
            index = timeline.getNextWindowIndex(index, repeat, player.shuffleModeEnabled)
            if (index == androidx.media3.common.C.INDEX_UNSET || !seen.add(index)) break
            val uri = player.getMediaItemAt(index).localConfiguration?.uri ?: continue
            if (MediaItems.localFile(uri, saved) == null) out += uri
        }
        return out
    }

    fun update() {
        val next = upcoming()
        if (next == wanted && job?.isActive == true) return
        wanted = next
        job?.cancel()
        if (next.isEmpty()) return
        job = scope.launch {
            for (uri in next) {
                while (isActive && !songs.isCached(uri)) {
                    try {
                        runInterruptible(Dispatchers.IO) {
                            CacheWriter(writers.createDataSourceForDownloading(), DataSpec(uri), null, null).cache()
                        }
                        break
                    } catch (e: Exception) {
                        if (!isActive) return@launch
                        Log.i(TAG, "Couldn't fetch ahead ($uri): $e")
                        delay(RETRY_MS)
                    }
                }
            }
        }
    }

    fun stop() { job?.cancel() }

    override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) = update()
    override fun onTimelineChanged(timeline: androidx.media3.common.Timeline, reason: Int) = update()
    override fun onShuffleModeEnabledChanged(shuffleModeEnabled: Boolean) = update()
    override fun onRepeatModeChanged(repeatMode: Int) = update()

    private companion object {
        const val TAG = "Prefetcher"
        const val RETRY_MS = 20_000L
    }
}
