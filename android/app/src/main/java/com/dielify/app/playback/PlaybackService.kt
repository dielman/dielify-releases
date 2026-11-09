package com.dielify.app.playback

import android.content.SharedPreferences
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
import com.dielify.app.net.RemoteCommand
import com.dielify.app.net.RemotePlayer
import com.dielify.app.net.RemoteSong
import com.dielify.app.net.RemoteState
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
    const val GAIN_DB = "gain_db"
    const val COLOR_BG = "color_bg"         // the cover's colours (Now playing, mini player)
    const val COLOR_ACCENT = "color_accent"

    /** Volume levelling (leveller.py on the PC): dB to add, if the song has been measured. */
    fun gainDb(item: MediaItem?): Double? =
        item?.mediaMetadata?.extras?.takeIf { it.containsKey(GAIN_DB) }?.getDouble(GAIN_DB)

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
                .setExtras(android.os.Bundle().apply {
                    t.videoId?.let { putString(VIDEO_ID, it) }
                    t.gainDb?.let { putDouble(GAIN_DB, it) }
                    t.colors?.let { putString(COLOR_BG, it.bg); putString(COLOR_ACCENT, it.accent) }
                })
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

    fun trackId(item: MediaItem?): Long? = item?.mediaId?.takeIf { it.startsWith(PREFIX) }?.removePrefix(PREFIX)?.toLongOrNull()

    /** A song sent by another device (remote control). */
    fun fromSong(s: RemoteSong): MediaItem? {
        val id = s.trackId
        val video = s.videoId
        if (id == null && video == null) return null
        return MediaItem.Builder()
            .setMediaId(if (id != null) PREFIX + id else YT_PREFIX + video)
            .setUri(if (id != null) streamUri(id) else ytStreamUri(video!!))
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(s.title)
                    .setArtist(s.artist)
                    .setAlbumTitle(s.album)
                    .setDurationMs(s.durationS?.let { it * 1000L })
                    .setArtworkUri(if (id != null) ArtProvider.trackArt(id) else s.thumbnail?.let(Uri::parse))
                    .setExtras(android.os.Bundle().apply {
                        video?.let { putString(VIDEO_ID, it) }
                        s.gainDb?.let { putDouble(GAIN_DB, it) }
                    })
                    .setIsPlayable(true)
                    .setIsBrowsable(false)
                    .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
                    .build()
            )
            .build()
    }

    fun toSong(i: MediaItem): RemoteSong {
        val m = i.mediaMetadata
        return RemoteSong(
            trackId = trackId(i), videoId = videoId(i), title = m.title?.toString() ?: "",
            artist = m.artist?.toString(), album = m.albumTitle?.toString(),
            durationS = m.durationMs?.let { (it / 1000).toInt() },
            thumbnail = m.artworkUri?.takeIf { it.scheme == "https" }?.toString(),
            gainDb = gainDb(i),
        )
    }

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
        // the equaliser (Settings), on this player's audio
        soundEq.attach(player.audioSessionId)
        dielify.levelPrefs.registerOnSharedPreferenceChangeListener(eqPrefs)
        player.addListener(object : Player.Listener {
            override fun onAudioSessionIdChanged(audioSessionId: Int) = soundEq.attach(audioSessionId)
        })
        prefetcher = Prefetcher(player, songs, songs.forPrefetch(network), saved, scope)
        player.addListener(prefetcher!!)
        startRemote(player)
        local = player
        startSleepTimer(player)
        player.addListener(object : Player.Listener {
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                dielify.endless.onTransition(player, mediaItem, scope)
                applyVolume()
                val m = mediaItem ?: return
                if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_REPEAT) return
                if (dielify.ratings.banned(MediaItems.videoId(m), MediaItems.trackId(m), m.mediaMetadata.artist?.toString())) {
                    if (player.hasNextMediaItem()) player.seekToNextMediaItem() else player.pause()
                }
            }
        })

        bitmaps = CacheBitmapLoader(
            DataSourceBitmapLoader.Builder(this)
                .setDataSourceFactory(dataSource)
                .setExecutorService(MoreExecutors.listeningDecorator(Executors.newSingleThreadExecutor()))
                .build()
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        // Cast to speakers: the session's player moves the queue to a Chromecast / Nest and back
        // (Media3 Cast); songs reach the speaker through short-lived cast links (CastLinks).
        val shown: Player = runCatching {
            androidx.media3.cast.CastPlayer.Builder(this).setLocalPlayer(player)
                .setRemotePlayer(androidx.media3.cast.RemoteCastPlayer.Builder(this)
                    .setMediaItemConverter(CastLinks(server, scope)).build())
                .build()
        }.getOrElse { android.util.Log.w("Dielify", "No casting: $it"); player }
        session = MediaLibrarySession.Builder(this, shown, Callback())
            .setBitmapLoader(bitmaps!!)
            .setSessionActivity(open)
            .build()
        setMediaNotificationProvider(
            DefaultMediaNotificationProvider.Builder(this).build().apply { setSmallIcon(R.drawable.ic_notification) }
        )
        followActiveDevice(shown)
        // the home-screen widget follows whatever the session shows
        current = this
        dielify.jamHost.attach(shown, scope)  // this phone hosting a Jam
        shown.addListener(widgetListener)
        refreshWidget()
    }

    // --- the home-screen widget (PlayerWidget) ---------------------------------------------

    private var bitmaps: CacheBitmapLoader? = null
    private var coverKey: Any? = null
    private var cover: android.graphics.Bitmap? = null
    private val widgetListener = object : Player.Listener {
        override fun onEvents(player: Player, events: Player.Events) {
            if (events.containsAny(Player.EVENT_MEDIA_METADATA_CHANGED, Player.EVENT_IS_PLAYING_CHANGED,
                    Player.EVENT_MEDIA_ITEM_TRANSITION, Player.EVENT_PLAYBACK_STATE_CHANGED, Player.EVENT_DEVICE_INFO_CHANGED)) refreshWidget()
        }
    }

    /** The player the app, notification and widget control right now (this phone, a speaker or another device). */
    fun shownPlayer(): Player? = session?.player

    private fun refreshWidget() {
        val p = session?.player ?: return
        val meta = p.mediaMetadata
        val title = meta.title?.toString()
        val artist = meta.artist?.toString()
        val subtitle = when {
            p is RemoteDevicePlayer -> "Playing on ${dielify.remote.elsewhere()?.name ?: "another device"}"
            p.deviceInfo.playbackType == androidx.media3.common.DeviceInfo.PLAYBACK_TYPE_REMOTE ->
                listOfNotNull("On a speaker", artist).joinToString(" · ")
            else -> artist
        }
        val key = meta.artworkUri ?: meta.artworkData?.contentHashCode()
        if (key != coverKey) {
            coverKey = key
            cover = null
            val loader = bitmaps
            if (key != null && loader != null) {
                val future = loader.loadBitmapFromMetadata(meta)
                future?.addListener({
                    val b = runCatching { future.get() }.getOrNull()
                    if (b != null && coverKey == key) {
                        val scale = 256f / maxOf(b.width, b.height)
                        cover = if (scale < 1f) android.graphics.Bitmap.createScaledBitmap(b, (b.width * scale).toInt(),
                            (b.height * scale).toInt(), true) else b
                        refreshWidget()
                    }
                }, androidx.core.content.ContextCompat.getMainExecutor(this))
            }
        }
        PlayerWidget.show(this, PlayerWidget.State(title, subtitle.takeIf { title != null }, p.isPlaying, cover, active = true))
    }

    /**
     * Spotify Connect: while another device is the active one, the session (and so the app,
     * notification, lock screen and headphone buttons) controls that device instead.
     */
    private fun followActiveDevice(local: Player) {
        val remote = dielify.remote
        val other = RemoteDevicePlayer(remote)
        other.addListener(widgetListener)
        fun pick() {
            refreshWidget()
            val s = session ?: return
            val d = remote.elsewhere()
            if (d != null) {
                other.update(d)
                if (s.player !== other) {
                    if (local.isPlaying) local.pause()
                    s.player = other
                }
            } else {
                if (s.player !== local) s.player = local
                other.update(null)
            }
        }
        scope.launch { remote.devices.collect { pick() } }
        scope.launch { remote.active.collect { pick() } }
        scope.launch {  // an idle device stops counting as active after a while
            while (true) { kotlinx.coroutines.delay(30_000); pick() }
        }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Swiping the app away keeps music playing; if nothing is playing, stop.
        val player = session?.player
        if (player == null || !player.playWhenReady || player.mediaItemCount == 0) stopSelf()
    }

    private val soundEq by lazy { SoundEq(dielify.levelPrefs) }
    private val eqPrefs = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key != null && key.startsWith("eq_")) soundEq.apply()
    }

    override fun onDestroy() {
        current = null
        PlayerWidget.show(this, PlayerWidget.State())
        dielify.levelPrefs.unregisterOnSharedPreferenceChangeListener(eqPrefs)
        soundEq.release()
        watcher?.finish()
        prefetcher?.stop()
        dielify.remote.stop()
        scope.cancel()
        session?.run {
            player.release()
            release()
        }
        session = null
        super.onDestroy()
    }

    // --- volume: other devices' volume x levelling (only turns loud songs down) x sleep fade ---

    private var local: ExoPlayer? = null
    private var userVolume = 1f
    private var fade = 1f

    private fun applyVolume() {
        val p = local ?: return
        val g = MediaItems.gainDb(p.currentMediaItem)?.takeIf { dielify.levelPrefs.getBoolean("level", true) } ?: 0.0
        val level = Math.pow(10.0, minOf(0.0, g) / 20).toFloat()
        p.volume = (userVolume * level * fade).coerceIn(0f, 1f)
    }

    // --- sleep timer -------------------------------------------------------------------------------

    private fun startSleepTimer(player: ExoPlayer) {
        val timer = dielify.sleep
        player.addListener(object : Player.Listener {
            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
                if (reason == Player.PLAY_WHEN_READY_CHANGE_REASON_END_OF_MEDIA_ITEM && timer.state.value.songEnd) {
                    player.pauseAtEndOfMediaItems = false
                    timer.off()
                }
            }
        })
        scope.launch {
            timer.state.collect { s ->  // end of song on this phone: Media3 stops exactly there
                player.pauseAtEndOfMediaItems = s.songEnd
                if (!s.on && fade != 1f) { fade = 1f; applyVolume() }
            }
        }
        scope.launch {
            while (true) {
                kotlinx.coroutines.delay(1000)
                val s = timer.state.value
                val p = session?.player ?: continue
                val here = p === player
                if (s.songEnd && !here &&
                    (p.currentMediaItemIndex != s.songIndex || p.currentMediaItem?.mediaId != s.songId)) {
                    p.pause(); timer.off()  // another device moved on to the next song
                } else if (s.endsAt > 0) {
                    val left = s.endsAt - System.currentTimeMillis()
                    if (left <= 0) { p.pause(); timer.off(); fade = 1f; applyVolume() }
                    else if (here) {
                        val f = if (left < SleepTimer.FADE_MS) maxOf(0.05f, left.toFloat() / SleepTimer.FADE_MS) else 1f
                        if (f != fade) { fade = f; applyVolume() }
                    }
                }
            }
        }
    }

    // --- remote control: other devices see and control this phone ------------------------------

    private fun startRemote(player: ExoPlayer) {
        val remote = dielify.remote
        remote.start(object : RemotePlayer {
            // The list as the other devices see it: in play order (shuffle included), so their
            // Up next is right; `order` maps their positions back to the player's.
            var order: List<Int> = emptyList()

            override fun state(): RemoteState {
                val count = player.mediaItemCount
                val tl = player.currentTimeline
                val o = mutableListOf<Int>()
                if (!tl.isEmpty) {
                    var i = tl.getFirstWindowIndex(player.shuffleModeEnabled)
                    while (i != C.INDEX_UNSET && o.size < minOf(count, 1000)) {
                        o += i; i = tl.getNextWindowIndex(i, Player.REPEAT_MODE_OFF, player.shuffleModeEnabled)
                    }
                }
                order = o
                val at = o.indexOf(player.currentMediaItemIndex)
                return RemoteState(
                    playing = player.isPlaying || (player.playWhenReady && player.playbackState == Player.STATE_BUFFERING),
                    positionMs = player.currentPosition,
                    durationMs = player.duration.takeIf { it > 0 },
                    volume = userVolume,
                    index = if (count > 0) at else -1,
                    queue = o.map { MediaItems.toSong(player.getMediaItemAt(it)) },
                )
            }

            override fun run(command: RemoteCommand, from: String) {
                when (command.action) {
                    "play" -> { if (player.playbackState == Player.STATE_IDLE) player.prepare(); player.play() }
                    "pause" -> player.pause()
                    "next" -> player.seekToNextMediaItem()
                    "previous" -> player.seekToPrevious()
                    "seek" -> command.positionMs?.let { player.seekTo(it) }
                    "volume" -> command.value?.let { userVolume = it.coerceIn(0f, 1f); applyVolume() }
                    "jump" -> {
                        val i = command.index?.let { order.getOrNull(it) } ?: return
                        player.seekTo(i, command.positionMs ?: 0)
                        if (player.playbackState == Player.STATE_IDLE) player.prepare()
                        player.play()
                    }
                    "queue" -> {  // a new list around the song playing now, which plays on
                        val songs = command.queue.orEmpty().mapNotNull(MediaItems::fromSong)
                        val k = command.index ?: return
                        if (k !in songs.indices || player.mediaItemCount == 0) return
                        player.shuffleModeEnabled = false
                        val cur = player.currentMediaItemIndex
                        if (cur + 1 < player.mediaItemCount) player.removeMediaItems(cur + 1, player.mediaItemCount)
                        if (cur > 0) player.removeMediaItems(0, cur)
                        player.addMediaItems(0, songs.subList(0, k))
                        player.addMediaItems(songs.subList(k + 1, songs.size))
                        dielify.endless.allow(songs)
                    }
                    "load" -> {
                        val items = command.queue.orEmpty().mapNotNull(MediaItems::fromSong)
                        if (items.isEmpty()) return
                        player.setMediaItems(items, (command.index ?: 0).coerceIn(0, items.size - 1), command.positionMs ?: 0)
                        player.prepare()
                        player.playWhenReady = command.playing != false
                    }
                }
            }
        })
        player.addListener(object : Player.Listener {
            override fun onEvents(p: Player, events: Player.Events) {
                if (events.containsAny(
                        Player.EVENT_IS_PLAYING_CHANGED, Player.EVENT_MEDIA_ITEM_TRANSITION, Player.EVENT_TIMELINE_CHANGED,
                        Player.EVENT_POSITION_DISCONTINUITY, Player.EVENT_VOLUME_CHANGED, Player.EVENT_PLAYBACK_STATE_CHANGED,
                    )
                ) remote.stateChanged()
            }
        })
        scope.launch {  // keeps positions right on the other devices, and the connection busy
            while (true) {
                kotlinx.coroutines.delay(15_000)
                remote.stateChanged()
            }
        }
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
        /**
         * While the session controls another device, play/pause/stop only count from this
         * app, the notification / lock screen (System UI) and Android Auto. Anything else
         * (e.g. earbuds or a watch pausing because "music started" while they're not in
         * use) would otherwise pause the PC the moment it starts. Each request is noted in
         * the PC's log with who sent it.
         */
        /**
         * Headphone / Bluetooth / earbud buttons (including automatic "pause" when earbuds
         * come out) only ever control music on this phone. While the session shows another
         * device they're ignored: taking your earbuds out must not stop the PC.
         * The notification's own buttons arrive here too and still work.
         */
        override fun onMediaButtonEvent(
            session: MediaSession,
            controllerInfo: MediaSession.ControllerInfo,
            intent: Intent,
        ): Boolean {
            if (session.player is RemoteDevicePlayer && !session.isMediaNotificationController(controllerInfo)) {
                dielify.remote.note("ignored a headphone/media button for the other device from ${controllerInfo.packageName}")
                return true  // handled: do nothing
            }
            return super.onMediaButtonEvent(session, controllerInfo, intent)
        }

        @Deprecated("Media3 still calls it; used to filter remote play/pause")
        override fun onPlayerCommandRequest(
            session: MediaSession,
            controller: MediaSession.ControllerInfo,
            playerCommand: Int,
        ): Int {
            if (session.player is RemoteDevicePlayer &&
                (playerCommand == Player.COMMAND_PLAY_PAUSE || playerCommand == Player.COMMAND_STOP)
            ) {
                val pkg = controller.packageName
                val ok = pkg == packageName || pkg in TRUSTED_CONTROLLERS
                dielify.remote.note("${if (ok) "accepted" else "ignored"} play/pause/stop for the other device from $pkg")
                if (!ok) return androidx.media3.session.SessionResult.RESULT_ERROR_PERMISSION_DENIED
            }
            return androidx.media3.session.SessionResult.RESULT_SUCCESS
        }

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

    companion object {
        /** The running service, for the home-screen widget's buttons (main thread only). */
        @Volatile var current: PlaybackService? = null

        const val ROOT = "root"
        const val RECENT = "recent"
        const val ALBUMS = "albums"
        const val PHONE = "phone"
        const val ALBUM = "album:"
        const val PHONE_ALBUM = "phone-album:"
        val TRUSTED_CONTROLLERS = setOf("com.android.systemui", "com.google.android.projection.gearhead")
        const val BUFFER_MS = 15 * 60_000
    }
}
