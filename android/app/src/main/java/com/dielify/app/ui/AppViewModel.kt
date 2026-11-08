package com.dielify.app.ui

import android.app.Application
import android.content.ComponentName
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.dielify.app.Account
import com.dielify.app.dielify
import com.dielify.app.net.ApiError
import com.dielify.app.net.Item
import com.dielify.app.net.PlaylistEntry
import com.dielify.app.net.PlaylistSummary
import com.dielify.app.net.SongIn
import com.dielify.app.net.Track
import com.dielify.app.playback.MediaItems
import com.dielify.app.playback.PlaybackService
import com.dielify.app.update.UpdateState
import com.google.common.util.concurrent.MoreExecutors
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

enum class Tab(val label: String) { Library("Library"), Discover("Discover"), Search("Search"), Downloads("Downloads") }

sealed interface Screen {
    data object Library : Screen    // the tabs (Library / Discover / Search / Downloads)
    data class AlbumPage(val id: Long, val name: String) : Screen
    data class ArtistPage(val id: Long, val name: String) : Screen
    data object NowPlaying : Screen
    data object Settings : Screen
    data class YtAlbumPage(val browseId: String, val name: String) : Screen
    data class YtPlaylistPage(val playlistId: String, val name: String) : Screen
    data class SimilarPage(val videoId: String, val name: String) : Screen
    data class SavedAlbumPage(val album: String, val artist: String) : Screen
    data object StatsPage : Screen
    data class PlaylistPage(val id: Long, val name: String) : Screen
}

data class PlayerUi(
    val hasItem: Boolean = false,
    val title: String = "",
    val artist: String = "",
    val album: String = "",
    val trackId: Long? = null,
    val videoId: String? = null,
    val isPlaying: Boolean = false,
    val buffering: Boolean = false,
    val hasNext: Boolean = false,
    val hasPrevious: Boolean = false,
    val shuffle: Boolean = false,
    val repeat: Int = Player.REPEAT_MODE_OFF,
    val error: String? = null,
)

class AppViewModel(app: Application) : AndroidViewModel(app) {
    val server = app.dielify.server
    private val accounts = app.dielify.accounts
    val saved = app.dielify.saved
    val updater = app.dielify.updater

    /** Songs on the phone, and the ones still being copied. */
    val savedSongs = saved.songs
    val savingIds: StateFlow<Set<Long>> = saved.pending.stateIn(viewModelScope, SharingStarted.Eagerly, emptySet())

    private val _account = MutableStateFlow(server.account)
    val account: StateFlow<Account?> = _account.asStateFlow()

    private val _stack = MutableStateFlow<List<Screen>>(listOf(Screen.Library))
    val stack: StateFlow<List<Screen>> = _stack.asStateFlow()

    private val _player = MutableStateFlow(PlayerUi())
    val player: StateFlow<PlayerUi> = _player.asStateFlow()

    private val _tab = MutableStateFlow(Tab.Library)
    val tab: StateFlow<Tab> = _tab.asStateFlow()

    /** Short messages shown at the bottom ("Added to downloads", errors). */
    val messages = MutableSharedFlow<String>(extraBufferCapacity = 4)

    /** Downloads waiting or running on the PC (for the badge on the Downloads tab). */
    private val _activeDownloads = MutableStateFlow(0)
    val activeDownloads: StateFlow<Int> = _activeDownloads.asStateFlow()

    var controller: MediaController? = null
        private set

    /** Spotify Connect: the other device the player controls right now (its name), if any. */
    val playingOn: StateFlow<String?> = kotlinx.coroutines.flow.combine(
        app.dielify.remote.active, app.dielify.remote.devices,
        kotlinx.coroutines.flow.flow { while (true) { emit(Unit); kotlinx.coroutines.delay(30_000) } },
    ) { _, _, _ -> app.dielify.remote.elsewhere()?.name }
        .stateIn(viewModelScope, SharingStarted.Eagerly, null)
    val showDevices = MutableStateFlow(false)

    val lastAddresses: List<String> get() = accounts.lastAddresses()
    val lastUsername: String get() = accounts.lastUsername()

    init {
        app.dielify.plays.flush()
        viewModelScope.launch { app.dielify.ratings.refresh() }
        viewModelScope.launch {
            updater.check()
            val s = updater.state.value
            if (s is UpdateState.Available) messages.tryEmit("Dielify ${s.release.version} is available: Settings > Update")
        }
        val token = SessionToken(app, ComponentName(app, PlaybackService::class.java))
        val future = MediaController.Builder(app, token).buildAsync()
        future.addListener({
            runCatching { future.get() }.getOrNull()?.let { c ->
                controller = c
                c.addListener(object : Player.Listener {
                    override fun onEvents(player: Player, events: Player.Events) = refresh()
                })
                refresh()
            }
        }, MoreExecutors.directExecutor())
    }

    private fun refresh() {
        val c = controller ?: return
        val m = c.mediaMetadata
        _player.value = PlayerUi(
            hasItem = c.currentMediaItem != null,
            title = m.title?.toString() ?: "",
            artist = m.artist?.toString() ?: "",
            album = m.albumTitle?.toString() ?: "",
            trackId = MediaItems.trackId(c.currentMediaItem),
            videoId = MediaItems.videoId(c.currentMediaItem),
            isPlaying = c.isPlaying,
            buffering = c.playbackState == Player.STATE_BUFFERING,
            hasNext = c.hasNextMediaItem(),
            hasPrevious = c.currentMediaItemIndex > 0 || c.currentPosition > 3000,
            shuffle = c.shuffleModeEnabled,
            repeat = c.repeatMode,
            error = c.playerError?.let { "Can't play this song: ${it.errorCodeName}" },
        )
    }

    // --- navigation ----------------------------------------------------------------------

    fun open(screen: Screen) {
        _stack.value = _stack.value + screen
    }

    fun selectTab(t: Tab) {
        _tab.value = t
        _stack.value = listOf(Screen.Library)
    }

    fun back(): Boolean {
        if (_stack.value.size <= 1) return false
        _stack.value = _stack.value.dropLast(1)
        return true
    }

    // --- YouTube Music: open, download, play ----------------------------------------------

    /** Tap on a YouTube item: songs play straight away (then the rest of `queue`), and the
     *  PC keeps a copy of anything it didn't have; albums/playlists open; artists search. */
    fun openItem(item: Item, queue: List<Item> = listOf(item)) {
        when {
            item.isSong -> playItems(queue, item)
            item.type == "album" -> open(Screen.YtAlbumPage(item.id, item.title))
            item.type == "playlist" -> open(Screen.YtPlaylistPage(item.id, item.title))
            item.type == "artist" -> { searchRequest.value = item.title; selectTab(Tab.Search) }
        }
    }

    fun playItems(queue: List<Item>, first: Item) {
        val c = controller ?: return
        val songs = queue.filter { it.isSong }.ifEmpty { listOf(first) }
        val start = songs.indexOfFirst { it.type == first.type && it.id == first.id }.coerceAtLeast(0)
        c.shuffleModeEnabled = false
        c.setMediaItems(songs.map(MediaItems::fromItem), start, 0L)
        c.prepare()
        c.play()
        if (first.libraryTrackId == null) messages.tryEmit("Playing \"${first.title}\", and saving it on your PC")
    }

    // --- playlists --------------------------------------------------------------------------

    /** Songs waiting for the "Add to playlist" picker (shown over any screen). */
    val addToPlaylist = MutableStateFlow<List<SongIn>?>(null)

    /** Bumped when playlists change, so open lists reload. */
    val playlistsVersion = MutableStateFlow(0)

    fun pickPlaylistFor(items: List<Item>) {
        addToPlaylist.value = items.filter { it.isSong }.map {
            SongIn(it.id, if (it.type == "video") "video" else "song", it.title, it.artists, it.album, it.durationS, it.thumbnail)
        }.ifEmpty { null }
    }

    /** The song playing now (library or YouTube), for "Add to playlist" on Now playing. */
    fun pickPlaylistForCurrent() {
        val c = controller ?: return
        val m = c.mediaMetadata
        val vid = MediaItems.videoId(c.currentMediaItem)
        if (vid == null) { messages.tryEmit("This song can't go in a YouTube playlist (no YouTube id)"); return }
        addToPlaylist.value = listOf(SongIn(vid, "song", m.title?.toString() ?: vid,
            listOfNotNull(m.artist?.toString()), m.albumTitle?.toString(), m.durationMs?.let { (it / 1000).toInt() }))
    }

    private fun playlistJob(done: String?, block: suspend () -> Unit) = viewModelScope.launch {
        try {
            block()
            done?.let { messages.tryEmit(it) }
            playlistsVersion.value++
        } catch (e: ApiError) {
            if (e.code == 401) tokenRejected()
            messages.tryEmit(e.message ?: "That didn't work")
        }
    }

    fun addSongsTo(p: PlaylistSummary, songs: List<SongIn>) = playlistJob(
        if (songs.size == 1) "Added to ${p.name}" else "${songs.size} songs added to ${p.name}",
    ) { server.addToPlaylist(p.id, songs) }

    fun newPlaylistWith(name: String, onYoutube: Boolean, songs: List<SongIn>) = playlistJob("Created \"$name\"") {
        val d = server.createPlaylist(name, onYoutube)
        if (songs.isNotEmpty()) server.addToPlaylist(d.playlist.id, songs)
    }

    fun importPlaylist(item: Item) = playlistJob("Syncing \"${item.title}\": its songs will download to your PC") {
        server.importPlaylist(item.id)
    }

    fun removeEntry(p: PlaylistSummary, entry: PlaylistEntry) = playlistJob("Removed from ${p.name}") {
        server.removeFromPlaylist(p.id, entry.entryId, onYoutube = p.ytId != null)
    }

    fun renamePlaylist(p: PlaylistSummary, name: String) = playlistJob("Renamed") { server.renamePlaylist(p.id, name) }

    fun deletePlaylist(p: PlaylistSummary, onYoutube: Boolean) = playlistJob(
        if (onYoutube) "Deleted here and on YouTube Music" else "Deleted from Dielify",
    ) {
        server.deletePlaylist(p.id, onYoutube)
        back()
    }

    fun syncPlaylist(p: PlaylistSummary) = playlistJob("Synced") { server.syncPlaylist(p.id) }

    /** Set by "artist" taps so the Search tab opens with that name filled in. */
    val searchRequest = MutableStateFlow<String?>(null)

    /** Single songs download next by default (you usually want to hear them now);
     *  whole albums/playlists join the back of the line unless `next` is set. */
    fun download(item: Item, next: Boolean = item.isSong) = viewModelScope.launch {
        try {
            val jobs = server.requestDownload(item, next).downloads
            val already = jobs.count { it.status == "done" }
            val queued = jobs.size - already
            messages.tryEmit(
                when {
                    queued == 0 -> "Already in your library"
                    item.isSong -> "Downloading \"${item.title}\" on the PC" + if (next) " (next in line)" else ""
                    else -> "$queued ${if (queued == 1) "song" else "songs"} added to downloads" +
                        if (already > 0) " ($already already in your library)" else ""
                }
            )
            refreshDownloadCount()
        } catch (e: ApiError) {
            if (e.code == 401) tokenRejected()
            messages.tryEmit(e.message ?: "Couldn't start the download")
        }
    }

    /** Play downloaded songs by library id, starting with the first. */
    fun playLibrary(trackIds: List<Long>, startIndex: Int = 0) = viewModelScope.launch {
        try {
            val tracks = coroutineScope { trackIds.map { async { server.track(it) } }.awaitAll() }
            play(tracks, startIndex)
        } catch (e: ApiError) {
            messages.tryEmit(e.message ?: "Couldn't play that")
        }
    }

    // --- saving on the phone ------------------------------------------------------------------

    fun saveToPhone(tracks: List<Track>) {
        val todo = tracks.filter { it.id !in savedSongs.value }
        saved.save(todo)
        messages.tryEmit(if (todo.isEmpty()) "Already on this phone"
            else "Saving ${todo.size} ${if (todo.size == 1) "song" else "songs"} on this phone")
    }

    /** Save downloaded songs (by library id) on the phone, e.g. the downloaded part of a playlist. */
    fun saveLibraryToPhone(trackIds: List<Long>) = viewModelScope.launch {
        try {
            val tracks = coroutineScope { trackIds.map { async { server.track(it) } }.awaitAll() }
            saveToPhone(tracks)
        } catch (e: ApiError) {
            messages.tryEmit(e.message ?: "Couldn't save them")
        }
    }

    fun removeFromPhone(ids: Collection<Long>) {
        saved.remove(ids)
        messages.tryEmit("Removed from this phone")
    }

    suspend fun refreshDownloadCount() {
        runCatching { server.activeDownloads() }.onSuccess { _activeDownloads.value = it.activeTotal ?: 0 }
    }

    fun setDownloadCount(n: Int) {
        _activeDownloads.value = n
    }

    // --- account -----------------------------------------------------------------------------

    fun signedIn(account: Account) {
        _account.value = account
        _stack.value = listOf(Screen.Library)
    }

    fun signOut() = viewModelScope.launch {
        controller?.run { stop(); clearMediaItems() }
        server.signOut()
        _account.value = null
    }

    /** The PC refused this phone's token (removed in Dielify's settings): sign in again. */
    fun tokenRejected() = viewModelScope.launch {
        server.signOut()
        _account.value = null
    }

    // --- playback ---------------------------------------------------------------------------

    fun play(tracks: List<Track>, startIndex: Int = 0, shuffle: Boolean = false) {
        val c = controller ?: return
        val items: List<MediaItem> = tracks.map(MediaItems::fromTrack)
        c.shuffleModeEnabled = shuffle
        c.setMediaItems(items, if (shuffle) (tracks.indices).random() else startIndex, 0L)
        c.prepare()
        c.play()
    }

    fun togglePlay() {
        val c = controller ?: return
        if (c.playerError != null) { c.prepare(); c.play(); return }
        if (c.isPlaying) c.pause() else c.play()
    }

    fun next() = controller?.seekToNextMediaItem()
    fun previous() = controller?.seekToPrevious()
    fun seekTo(ms: Long) = controller?.seekTo(ms)
    fun toggleShuffle() = controller?.let { it.shuffleModeEnabled = !it.shuffleModeEnabled }
    fun cycleRepeat() = controller?.let {
        it.repeatMode = when (it.repeatMode) {
            Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ALL
            Player.REPEAT_MODE_ALL -> Player.REPEAT_MODE_ONE
            else -> Player.REPEAT_MODE_OFF
        }
    }

    override fun onCleared() {
        controller?.release()
        controller = null
    }
}
