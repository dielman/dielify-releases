package com.dielify.app.playback

import android.util.Log
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import com.dielify.app.net.Jam
import com.dielify.app.net.JamPlaying
import com.dielify.app.net.Server
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * This phone hosting a Jam: the player plays the Jam's songs, picks up songs people add (it
 * asks the PC every few seconds) and tells the PC which song is playing. Lives in the playback
 * service, so it keeps going with the screen off (e.g. in the car).
 */
class JamHost(private val server: Server) {
    private var player: Player? = null
    private var scope: CoroutineScope? = null
    private var loop: Job? = null
    @Volatile var hosting = false
        private set
    private var version = -1
    private var reported = -2

    /** The playback service hands over its player. */
    fun attach(p: Player, s: CoroutineScope) {
        player = p
        scope = s
        p.addListener(object : Player.Listener {
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) = report()
        })
        if (hosting) run()
    }

    /** Called when this phone starts hosting a Jam. */
    fun begin(jam: Jam) {
        hosting = true
        version = -1
        sync(jam, start = true)
        run()
    }

    fun stop() {
        hosting = false
        loop?.cancel()
    }

    private fun run() {
        val s = scope ?: return
        loop?.cancel()
        loop = s.launch {
            while (hosting) {
                val j = runCatching { server.jam() }.getOrElse { e -> Log.i("Dielify", "Jam: ${e.message}"); delay(5_000); continue }
                if (j == null || !j.youHost) { hosting = false; break }
                if (j.version != version) sync(j, start = false)
                delay(5_000)
            }
        }
    }

    private fun jamId(m: MediaItem?): Long? = m?.mediaMetadata?.extras?.getLong(JAM_ID, -1)?.takeIf { it >= 0 }

    private fun item(s: com.dielify.app.net.JamSong): MediaItem {
        val base = MediaItems.fromItem(s.item)
        val extras = android.os.Bundle(base.mediaMetadata.extras ?: android.os.Bundle()).apply { putLong(JAM_ID, s.id) }
        return base.buildUpon().setMediaMetadata(base.mediaMetadata.buildUpon().setExtras(extras).build()).build()
    }

    /** Make the player's list the Jam's songs, keeping the song that's playing. */
    private fun sync(j: Jam, start: Boolean) {
        val p = player ?: return
        version = j.version
        val items = j.songs.map(::item)
        if (items.isEmpty()) return
        val cur = jamId(p.currentMediaItem)
        val at = j.songs.indexOfFirst { it.id == cur }
        if (cur != null && at >= 0) {
            // replace what comes after the playing song with the Jam's list from there
            val after = p.currentMediaItemIndex + 1
            if (after < p.mediaItemCount) p.removeMediaItems(after, p.mediaItemCount)
            p.addMediaItems(items.drop(at + 1))
            return
        }
        if (start || !p.isPlaying) {
            p.shuffleModeEnabled = false
            p.setMediaItems(items, maxOf(0, j.index), 0L)
            p.prepare()
            p.play()
        }
    }

    private fun report() {
        if (!hosting) return
        val p = player ?: return
        val id = jamId(p.currentMediaItem) ?: return
        val s = scope ?: return
        s.launch {
            val j = runCatching { server.jam() }.getOrNull() ?: return@launch
            val i = j.songs.indexOfFirst { it.id == id }
            if (i >= 0 && i != reported) {
                reported = i
                runCatching { server.jamPlaying(JamPlaying(i)) }
            }
        }
    }

    companion object {
        const val JAM_ID = "jam_id"
    }
}
