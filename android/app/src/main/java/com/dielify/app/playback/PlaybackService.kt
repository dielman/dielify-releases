package com.dielify.app.playback

import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSourceBitmapLoader
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.CacheBitmapLoader
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.dielify.app.R
import com.dielify.app.dielify
import com.dielify.app.net.Server
import com.dielify.app.net.Track
import com.dielify.app.ui.MainActivity
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.MoreExecutors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.util.concurrent.Executors

/** Builds player items for library tracks. */
object MediaItems {
    private const val PREFIX = "tr-"

    private fun mediaUri(path: String): Uri = Uri.parse("${Server.MEDIA_SCHEME}://server$path")

    fun streamUri(trackId: Long) = mediaUri("/api/library/tracks/$trackId/stream")

    fun fromTrack(t: Track): MediaItem = MediaItem.Builder()
        .setMediaId(PREFIX + t.id)
        .setUri(streamUri(t.id))
        .setMediaMetadata(
            MediaMetadata.Builder()
                .setTitle(t.title)
                .setArtist(t.artist)
                .setAlbumTitle(t.album)
                .setAlbumArtist(t.albumArtist.ifEmpty { null })
                .setTrackNumber(t.trackNo)
                .setReleaseYear(t.year)
                .setDurationMs(t.durationS?.let { it * 1000L })
                .setArtworkUri(t.coverUrl?.let { mediaUri("$it?size=600") })
                .setIsPlayable(true)
                .setIsBrowsable(false)
                .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
                .build()
        )
        .build()

    fun trackId(item: MediaItem?): Long? = item?.mediaId?.removePrefix(PREFIX)?.toLongOrNull()

    /** Items sent from the app's screens arrive without their URI; put it back. */
    fun restore(item: MediaItem): MediaItem {
        if (item.localConfiguration != null) return item
        val id = trackId(item) ?: return item
        return item.buildUpon().setUri(streamUri(id)).build()
    }
}

/**
 * Plays music in the background, with the notification and lock-screen controls.
 * Songs are streamed from the PC (no copy is kept on the phone yet).
 */
@OptIn(UnstableApi::class)
class PlaybackService : MediaSessionService() {
    private var session: MediaSession? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreate() {
        super.onCreate()
        val server = dielify.server
        val dataSource = ResolvingDataSource.Factory(OkHttpDataSource.Factory(server.http)) { spec ->
            spec.withUri(server.resolveMedia(spec.uri))
        }
        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataSource))
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(C.USAGE_MEDIA)
                    .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(),
                /* handleAudioFocus = */ true,
            )
            .setHandleAudioBecomingNoisy(true)  // pause when headphones are unplugged
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .build()
        player.addListener(Watcher(player, server))

        val bitmaps = CacheBitmapLoader(
            DataSourceBitmapLoader.Builder(this)
                .setDataSourceFactory(dataSource)
                .setExecutorService(MoreExecutors.listeningDecorator(Executors.newSingleThreadExecutor()))
                .build()
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        session = MediaSession.Builder(this, player)
            .setCallback(Callback())
            .setBitmapLoader(bitmaps)
            .setSessionActivity(open)
            .build()
        setMediaNotificationProvider(
            DefaultMediaNotificationProvider.Builder(this).build().apply { setSmallIcon(R.drawable.ic_notification) }
        )
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Swiping the app away keeps music playing; if nothing is playing, stop.
        val player = session?.player
        if (player == null || !player.playWhenReady || player.mediaItemCount == 0) stopSelf()
    }

    override fun onDestroy() {
        scope.cancel()
        session?.run {
            player.release()
            release()
        }
        session = null
        super.onDestroy()
    }

    private inner class Callback : MediaSession.Callback {
        override fun onAddMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: MutableList<MediaItem>,
        ): ListenableFuture<MutableList<MediaItem>> =
            Futures.immediateFuture(mediaItems.map(MediaItems::restore).toMutableList())
    }

    /**
     * - Network trouble: find the PC again (maybe the phone left home Wi-Fi) and carry on
     *   from the same spot, up to 3 times in a row.
     * - A song that played to the end counts as played on the PC (play counts).
     */
    private inner class Watcher(private val player: ExoPlayer, private val server: Server) : Player.Listener {
        private var retries = 0
        private var current: MediaItem? = null

        override fun onPlayerError(error: PlaybackException) {
            val network = error.errorCode in 2000..2999
            if (network && retries < 3) {
                retries++
                server.forgetAddress()
                player.prepare()
            }
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (isPlaying) retries = 0
        }

        override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
            val finished = current
            if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO ||
                reason == Player.MEDIA_ITEM_TRANSITION_REASON_REPEAT) {
                MediaItems.trackId(finished)?.let { id ->
                    scope.launch { runCatching { server.played(id) } }
                }
            }
            current = mediaItem
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            if (playbackState == Player.STATE_ENDED) {
                MediaItems.trackId(current)?.let { id -> scope.launch { runCatching { server.played(id) } } }
            }
        }
    }
}
