package com.dielify.app.playback

import android.net.Uri
import androidx.media3.cast.DefaultMediaItemConverter
import androidx.media3.cast.MediaItemConverter
import androidx.media3.common.MediaItem
import com.dielify.app.net.Server
import com.google.android.gms.cast.MediaQueueItem
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Songs for a speaker (Chromecast / Nest): the speaker fetches each song from the PC itself,
 * so "dielify://server/<path>" becomes "http://<PC's home address>:4747/<path>?token=<cast key>".
 *
 * The cast key comes from POST /api/cast/token: it only plays songs and shows covers and
 * runs out after 12 hours. The phone's own login never goes to the speaker. Keys are fetched
 * ahead (the converter runs on the main thread and can't wait for the network).
 */
class CastLinks(private val server: Server, scope: CoroutineScope) : MediaItemConverter {
    private val default = DefaultMediaItemConverter()
    @Volatile private var key: String? = null
    @Volatile private var keyUntil = 0.0

    init {
        scope.launch {
            while (true) {
                if (System.currentTimeMillis() / 1000.0 > keyUntil - 6 * 3600) refresh()
                delay(if (key == null) 60_000 else 30 * 60_000L)
            }
        }
    }

    suspend fun refresh() {
        runCatching { server.castToken() }.onSuccess { key = it.token; keyUntil = it.expiresAt }
    }

    /** The PC's home-network address: the speaker is on the home network, not on Tailscale. */
    private fun base(): String? {
        val addresses = server.account?.addresses ?: return null
        val home = addresses.firstOrNull { !it.substringBefore(':').startsWith("100.") } ?: addresses.firstOrNull() ?: return null
        val withPort = if (':' in home.removePrefix("http://")) home else "$home:4747"
        return (if (withPort.startsWith("http")) withPort else "http://$withPort").trimEnd('/')
    }

    private fun link(path: String): String? {
        val b = base() ?: return null
        val k = key ?: return null
        return "$b$path${if ('?' in path) '&' else '?'}token=$k"
    }

    override fun toMediaQueueItem(mediaItem: MediaItem): MediaQueueItem {
        val uri = mediaItem.localConfiguration?.uri
        val path = if (uri?.scheme == Server.MEDIA_SCHEME) uri.path + (uri.query?.let { "?$it" } ?: "") else null
        val track = MediaItems.trackId(mediaItem)
        val cast = path?.let(::link) ?: uri?.toString() ?: ""
        val art = track?.let { link("/api/library/tracks/$it/cover?size=600") }
            ?: mediaItem.mediaMetadata.artworkUri?.takeIf { it.scheme == "https" }?.toString()
        val meta = mediaItem.mediaMetadata.buildUpon().setArtworkUri(art?.let(Uri::parse)).build()
        val forSpeaker = mediaItem.buildUpon()
            .setUri(cast)
            // Library songs are mostly Opus in Ogg (Dielify's default); YouTube songs come as WebM
            .setMimeType(mediaItem.localConfiguration?.mimeType ?: if (track != null) "audio/ogg" else "audio/webm")
            .setMediaMetadata(meta)
            .build()
        return default.toMediaQueueItem(forSpeaker)
    }

    /** Back on the phone: the normal dielify:// address again (no cast key in it). */
    override fun toMediaItem(mediaQueueItem: MediaQueueItem): MediaItem {
        val m = default.toMediaItem(mediaQueueItem)
        val bare = m.buildUpon().setUri(null as Uri?).build()
        val back = MediaItems.restore(bare)
        return if (back.localConfiguration != null) back else m
    }
}
