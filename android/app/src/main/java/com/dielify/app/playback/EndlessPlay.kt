package com.dielify.app.playback

import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import com.dielify.app.net.EndlessIn
import com.dielify.app.net.Item
import com.dielify.app.net.Server
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * Never-ending discovery play (see dielify/explore.py): songs that aren't in the library
 * yet, like the ones heard so far. The PC downloads each one; thumbs down deletes it again.
 * Started from Discover; the playback service tops the list up when 3 or fewer songs are
 * left. Playing any other list ends it.
 */
class EndlessPlay(private val server: Server) {
    @Volatile var active = false
        private set
    private val ids = mutableSetOf<String>()  // media ids this mode put in the list
    @Volatile private var fetching = false

    suspend fun batch(seeds: List<String>, exclude: List<String>, count: Int = 10): List<Item> =
        server.endless(EndlessIn(seeds.takeLast(20), exclude.takeLast(2000), count))

    /** The first songs, for the view model to play. */
    fun started(items: List<MediaItem>, seed: MediaItem?) {
        synchronized(ids) { ids.clear(); seed?.let { ids += it.mediaId }; items.forEach { ids += it.mediaId } }
        active = true
    }

    fun stop() { active = false }

    /** Songs added to the list by hand (Play next / Add to queue) don't end it. */
    fun allow(items: List<MediaItem>) {
        if (active) synchronized(ids) { items.forEach { ids += it.mediaId } }
    }

    /** Called by the playback service on every song change. */
    fun onTransition(player: Player, item: MediaItem?, scope: CoroutineScope) {
        if (!active || item == null) return
        if (synchronized(ids) { item.mediaId !in ids }) { active = false; return }  // another list is playing
        val left = player.mediaItemCount - 1 - player.currentMediaItemIndex
        if (left > 3 || fetching) return
        fetching = true
        val all = (0 until player.mediaItemCount).map { player.getMediaItemAt(it) }
        val heard = all.take(player.currentMediaItemIndex + 1).mapNotNull(MediaItems::videoId)
        scope.launch {
            try {
                val more = batch(heard, all.mapNotNull(MediaItems::videoId)).map(MediaItems::fromItem)
                if (active && more.isNotEmpty()) {
                    synchronized(ids) { more.forEach { ids += it.mediaId } }
                    player.addMediaItems(more)
                }
            } catch (_: Exception) {
                // offline / PC busy: tried again at the next song
            } finally {
                fetching = false
            }
        }
    }
}
