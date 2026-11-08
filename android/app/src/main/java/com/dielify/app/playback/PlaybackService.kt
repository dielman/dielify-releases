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
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.CacheBitmapLoader
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaLibraryService.MediaLibrarySession
import androidx.media3.session.MediaSession
import com.dielify.app.R
import com.dielify.app.dielify
import com.dielify.app.net.Album
import com.dielify.app.net.Item
import com.dielify.app.net.Server
import com.dielify.app.net.Track
import com.dielify.app.saved.SavedSongs
import com.dielify.app.saved.groupAlbums
import com.dielify.app.ui.MainActivity
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.MoreExecutors
import com.google.common.util.concurrent.SettableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/** Builds player items for library tracks. */
object MediaItems {
    private const val PREFIX = "tr-"

    private fun mediaUri(path: String): Uri = Uri.parse("${Server.MEDIA_SCHEME}://server$path")

    private const val YT_PREFIX = "yt-"
    const val VIDEO_ID = "video_id"

    fun videoId(item: MediaItem?): String? =
        item?.mediaMetadata?.extras?.getString(VIDEO_ID) ?: item?.mediaId?.takeIf { it.startsWith(YT_PREFIX) }?.removePrefix(YT_PREFIX)

    fun streamUri(trackId: Long) = mediaUri("/api/library/tracks/$trackId/stream")

    /** Any YouTube song: the PC relays it (and downloads it next in line). */
    fun ytStreamUri(videoId: String) = mediaUri("/api/yt/stream/$videoId")

    /** A song from YouTube Music lists (Discover, search, playlists, similar). */
    fun fromItem(i: Item): MediaItem {
        val id = i.libraryTrackId
        return MediaItem.Builder()
            .setMediaId(if (id != null) PREFIX + id else YT_PREFIX + i.id)
            .setUri(if (id != null) streamUri(id) else ytStreamUri(i.id))
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(i.title)
                    .setArtist(i.artistText.ifEmpty { null })
                    .setAlbumTitle(i.album)
                    .setDurationMs(i.durationS?.let { it * 1000L })
                    .setArtworkUri(if (id != null) ArtProvider.trackArt(id) else i.thumbnail?.let(Uri::parse))
                    .setExtras(android.os.Bundle().apply { putString(VIDEO_ID, i.id) })
                    .setIsPlayable(true)
                    .setIsBrowsable(false)
                    .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
                    .build()
            )
            .build()
    }

    fun fromTrack(t: Track): MediaItem = MediaItem.Builder()
        .setMediaId(PREFIX + t.id)
        .setUri(streamUri(t.id))
        .setMediaMetadata(
            MediaMetadata.Builder()
                .setTitle(t.title)
                .setArtist(t.artist)
                .setAlbumTitle(t.album)
                .setAlbumArtist(t.albumArtist.ifEmpty { null })
                .setExtras(android.os.Bundle().apply { t.videoId?.let { putString(VIDEO_ID, it) } })
                .setTrackNumber(t.trackNo)
                .setReleaseYear(t.year)
                .setDurationMs(t.durationS?.let { it * 1000L })
                .setArtworkUri(t.coverUrl?.let { ArtProvider.trackArt(t.id) })
                .setIsPlayable(true)
                .setIsBrowsable(false)
                .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
                .build()
        )
        .build()

    private val pathPattern = Regex("""^/api/library/tracks/(\d+)/(stream|cover)$""")

    /** The phone's own copy of a song or its cover, if it has been saved. */
    fun localFile(uri: Uri, saved: SavedSongs): java.io.File? {
        if (uri.scheme != Server.MEDIA_SCHEME) return null
        val m = pathPattern.find(uri.path ?: return null) ?: return null
        val id = m.groupValues[1].toLong()
        return if (m.groupValues[2] == "stream") saved.audioFile(id) else saved.coverFile(id)
    }

    fun trackId(item: MediaItem?): Long? = item?.mediaId?.removePrefix(PREFIX)?.toLongOrNull()

    /** Items sent from the app's screens (or the car) arrive without their URI; put it back. */
    fun restore(item: MediaItem, known: MediaItem? = null): MediaItem {
        val base = if (item.mediaMetadata.title == null && known != null) known else item
        if (base.localConfiguration != null) return base
        if (base.mediaId.startsWith(YT_PREFIX)) {
            return base.buildUpon().setUri(ytStreamUri(base.mediaId.removePrefix(YT_PREFIX))).build()
        }
        val id = trackId(base) ?: return base
        return base.buildUpon().setUri(streamUri(id)).build()
    }
}

/**
 * Plays music in the background, with the notification, lock-screen and Android Auto
 * controls. Saved songs play from the phone; the rest streams from the PC.
 *
 * For Android Auto it is also a browsable library:
 *   Recently added / Albums (from the PC) / On this phone (works with no connection).
 */
@OptIn(UnstableApi::class)
class PlaybackService : MediaLibraryService() {
    private var session: MediaLibrarySession? = null
    private var watcher: Watcher? = null
    private var prefetcher: Prefetcher? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    /** Items handed to the car, so a tap (which sends only the id) can be played in full. */
    private val known = ConcurrentHashMap<String, MediaItem>()
    /** The album each song was shown in, so tapping a song in the car plays on through the album. */
    private val siblings = ConcurrentHashMap<String, List<MediaItem>>()

    override fun onCreate() {
        super.onCreate()
        val server = dielify.server
        val saved = dielify.saved
        // Saved songs -> file:// (read by DefaultDataSource itself, like content:// cover art).
        // Everything else goes through the song cache, still as dielify://server/... so a
        // cached song plays with no connection; the PC's real address is looked up only
        // when bytes are missing.
        val network = ResolvingDataSource.Factory(OkHttpDataSource.Factory(server.http)) { spec ->
            spec.withUri(server.resolveMedia(spec.uri))
        }
        val songs = dielify.songCache
        val dataSource = ResolvingDataSource.Factory(DefaultDataSource.Factory(this, songs.forPlayer(network))) { spec ->
            val local = MediaItems.localFile(spec.uri, saved)
            if (local != null) spec.withUri(Uri.fromFile(local)) else spec
        }
        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataSource))
            // Read the whole song as soon as it starts (not just the next 50 s), so it is
            // already on the phone if reception drops halfway through.
            .setLoadControl(
                DefaultLoadControl.Builder()
                    .setBufferDurationsMs(BUFFER_MS, BUFFER_MS, 2_500, 5_000)
                    .setTargetBufferBytes(48 * 1024 * 1024)
                    .setPrioritizeTimeOverSizeThresholds(true)
                    .build()
            )
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(C.USAGE_MEDIA)
                    .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(),
                /* handleAudioFocus = */ true,
            )
            .setHandleAudioBecomingNoisy(true)  // pause when headphones are unplugged
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .build()
        watcher = Watcher(player, server)
        player.addListener(watcher!!)
        prefetcher = Prefetcher(player, songs, songs.forPrefetch(network), saved, scope)
        player.addListener(prefetcher!!)

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
        session = MediaLibrarySession.Builder(this, player, Callback())
            .setBitmapLoader(bitmaps)
            .setSessionActivity(open)
            .build()
        setMediaNotificationProvider(
            DefaultMediaNotificationProvider.Builder(this).build().apply { setSmallIcon(R.drawable.ic_notification) }
        )
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Swiping the app away keeps music playing; if nothing is playing, stop.
        val player = session?.player
        if (player == null || !player.playWhenReady || player.mediaItemCount == 0) stopSelf()
    }

    override fun onDestroy() {
        watcher?.finish()
        prefetcher?.stop()
        scope.cancel()
        session?.run {
            player.release()
            release()
        }
        session = null
        super.onDestroy()
    }

    // --- the browse tree (Android Auto) ---------------------------------------------------------

    private fun folder(id: String, title: String): MediaItem = MediaItem.Builder()
        .setMediaId(id)
        .setMediaMetadata(
            MediaMetadata.Builder().setTitle(title).setIsBrowsable(true).setIsPlayable(false)
                .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_ALBUMS).build()
        ).build()

    private fun albumItem(a: Album): MediaItem = MediaItem.Builder()
        .setMediaId("$ALBUM${a.id}")
        .setMediaMetadata(
            MediaMetadata.Builder().setTitle(a.name).setArtist(a.artist).setAlbumTitle(a.name)
                .setIsBrowsable(true).setIsPlayable(false)
                .setMediaType(MediaMetadata.MEDIA_TYPE_ALBUM)
                .setArtworkUri(a.coverUrl?.let { ArtProvider.albumArt(a.id) })
                .build()
        ).build()

    private fun songs(tracks: List<Track>): List<MediaItem> {
        val items = tracks.map(MediaItems::fromTrack)
        items.forEach { known[it.mediaId] = it; siblings[it.mediaId] = items }
        return items
    }

    private suspend fun children(parentId: String): List<MediaItem> {
        val server = dielify.server
        val saved = dielify.saved
        return when {
            parentId == ROOT -> listOf(
                folder(RECENT, "Recently added"),
                folder(ALBUMS, "Albums"),
                folder(PHONE, "On this phone"),
            )
            parentId == RECENT -> runCatching { server.recentAlbums().take(100).map(::albumItem) }.getOrDefault(emptyList())
            parentId == ALBUMS -> runCatching { server.albums().map(::albumItem) }.getOrDefault(emptyList())
            parentId == PHONE -> groupAlbums(saved.songs.value.values).mapIndexed { i, a ->
                MediaItem.Builder().setMediaId("$PHONE_ALBUM$i")
                    .setMediaMetadata(
                        MediaMetadata.Builder().setTitle(a.album).setArtist(a.artist).setAlbumTitle(a.album)
                            .setIsBrowsable(true).setIsPlayable(false)
                            .setMediaType(MediaMetadata.MEDIA_TYPE_ALBUM)
                            .setArtworkUri(a.tracks.first().coverUrl?.let { ArtProvider.trackArt(a.tracks.first().id) })
                            .build()
                    ).build()
            }
            parentId.startsWith(ALBUM) -> parentId.removePrefix(ALBUM).toLongOrNull()
                ?.let { id -> runCatching { songs(server.album(id).tracks) }.getOrNull() } ?: emptyList()
            parentId.startsWith(PHONE_ALBUM) -> parentId.removePrefix(PHONE_ALBUM).toIntOrNull()
                ?.let { groupAlbums(saved.songs.value.values).getOrNull(it) }
                ?.let { songs(it.tracks) } ?: emptyList()
            else -> emptyList()
        }
    }

    private fun <T> later(block: suspend () -> T): ListenableFuture<T> {
        val f = SettableFuture.create<T>()
        scope.launch {
            try { f.set(block()) } catch (e: Throwable) { f.setException(e) }
        }
        return f
    }

    private inner class Callback : MediaLibrarySession.Callback {
        override fun onGetLibraryRoot(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            params: LibraryParams?,
        ): ListenableFuture<LibraryResult<MediaItem>> =
            Futures.immediateFuture(LibraryResult.ofItem(folder(ROOT, "Dielify"), params))

        override fun onGetChildren(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            parentId: String,
            page: Int,
            pageSize: Int,
            params: LibraryParams?,
        ): ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> = later {
            val all = children(parentId)
            val from = (page.toLong() * pageSize).coerceAtMost(all.size.toLong()).toInt()
            val to = (from.toLong() + pageSize).coerceAtMost(all.size.toLong()).toInt()
            LibraryResult.ofItemList(ImmutableList.copyOf(all.subList(from, to)), params)
        }

        override fun onGetItem(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            mediaId: String,
        ): ListenableFuture<LibraryResult<MediaItem>> {
            val item = known[mediaId]
            return Futures.immediateFuture(
                if (item != null) LibraryResult.ofItem(item, null)
                else LibraryResult.ofError(LibraryResult.RESULT_ERROR_BAD_VALUE)
            )
        }

        override fun onAddMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: MutableList<MediaItem>,
        ): ListenableFuture<MutableList<MediaItem>> =
            Futures.immediateFuture(mediaItems.map { MediaItems.restore(it, known[it.mediaId]) }.toMutableList())

        override fun onSetMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: MutableList<MediaItem>,
            startIndex: Int,
            startPositionMs: Long,
        ): ListenableFuture<MediaSession.MediaItemsWithStartPosition> {
            // One song tapped in the car: play the album it was listed in, starting there.
            if (mediaItems.size == 1 && mediaItems[0].mediaMetadata.title == null) {
                val id = mediaItems[0].mediaId
                val album = siblings[id]
                if (album != null) {
                    val index = album.indexOfFirst { it.mediaId == id }.coerceAtLeast(0)
                    return Futures.immediateFuture(
                        MediaSession.MediaItemsWithStartPosition(album.map { MediaItems.restore(it) }, index, startPositionMs)
                    )
                }
            }
            val items = mediaItems.map { MediaItems.restore(it, known[it.mediaId]) }
            return Futures.immediateFuture(MediaSession.MediaItemsWithStartPosition(items, startIndex, startPositionMs))
        }
    }

    /**
     * - Network trouble: find the PC again (maybe the phone left home Wi-Fi) and carry on
     *   from the same spot, up to 3 times in a row.
     * - Play history: how long each song was actually heard goes to the PC (the PC decides
     *   what counts as a play; skips are kept too).
     */
    private inner class Watcher(private val player: ExoPlayer, private val server: Server) : Player.Listener {
        private var retries = 0
        private var current: MediaItem? = null
        private var startedAt = 0.0
        private var heardMs = 0L
        private var playingSince: Long? = null

        private fun pause() {
            playingSince?.let { heardMs += android.os.SystemClock.elapsedRealtime() - it }
            playingSince = null
        }

        /** The song in `current` is over (finished, skipped or stopped): report it. */
        fun finish() {
            pause()
            val item = current
            val played = (heardMs / 1000).toInt()
            heardMs = 0
            if (item == null || played < 1) return
            val m = item.mediaMetadata
            dielify.plays.add(
                com.dielify.app.net.PlayReport(
                    trackId = MediaItems.trackId(item), videoId = MediaItems.videoId(item),
                    title = m.title?.toString() ?: return, artist = m.artist?.toString(),
                    album = m.albumTitle?.toString(), durationS = m.durationMs?.let { (it / 1000).toInt() },
                    playedS = played, startedAt = startedAt, clientId = java.util.UUID.randomUUID().toString(),
                )
            )
        }

        override fun onPlayerError(error: PlaybackException) {
            val network = error.errorCode in 2000..2999
            if (network && retries < 3) {
                retries++
                server.forgetAddress()
                player.prepare()
            }
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (isPlaying) {
                retries = 0
                if (current == null) { current = player.currentMediaItem; startedAt = System.currentTimeMillis() / 1000.0 }
                if (playingSince == null) playingSince = android.os.SystemClock.elapsedRealtime()
            } else pause()
        }

        override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
            finish()
            current = mediaItem
            startedAt = System.currentTimeMillis() / 1000.0
            if (player.isPlaying) playingSince = android.os.SystemClock.elapsedRealtime()
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            if (playbackState == Player.STATE_ENDED) { finish(); current = null }
        }
    }

    private companion object {
        const val ROOT = "root"
        const val RECENT = "recent"
        const val ALBUMS = "albums"
        const val PHONE = "phone"
        const val ALBUM = "album:"
        const val PHONE_ALBUM = "phone-album:"
        const val BUFFER_MS = 15 * 60_000
    }
}
