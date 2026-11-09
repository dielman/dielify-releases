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

/** A song in Up next: [index] is its place in the player's list. */
data class QueueEntry(val index: Int, val title: String, val artist: String, val art: String?)

data class UpNext(val now: QueueEntry? = null, val next: List<QueueEntry> = emptyList(), val shuffled: Boolean = false)

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

    private val _tab = MutableStateFlow(Tab.Discover)  // the app opens on Discover
    val tab: StateFlow<Tab> = _tab.asStateFlow()

    /** Results already loaded (searches, albums, Discover), so going back shows them at once. */
    val loadCache = java.util.concurrent.ConcurrentHashMap<String, Pair<Long, Any?>>()

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
    val showUpNext = MutableStateFlow(false)
    val showLyrics = MutableStateFlow(false)
    fun sleepAtSongEnd() {
        val c = controller ?: return
        if (c.currentMediaItem == null) { messages.tryEmit("Nothing playing"); return }
        getApplication<Application>().dielify.sleep.endOfSong(c.currentMediaItemIndex, c.currentMediaItem?.mediaId)
        messages.tryEmit("Sleep timer: stops at the end of this song")
    }
    fun positionMs(): Long = controller?.currentPosition ?: 0L
    fun durationS(): Int? = controller?.duration?.takeIf { it > 0 }?.let { (it / 1000).toInt() }
    private val _upNext = MutableStateFlow(UpNext())
    /** The song playing now and the ones coming up, in play order (shuffle included). */
    val upNext: StateFlow<UpNext> = _upNext

    val lastAddresses: List<String> get() = accounts.lastAddresses()
    val lastUsername: String get() = accounts.lastUsername()

    init {
        app.dielify.plays.flush()
        viewModelScope.launch { app.dielify.ratings.refresh() }
        viewModelScope.launch { app.dielify.taste.refresh() }
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
                    override fun onEvents(player: Player, events: Player.Events) {
                        refresh()
                        if (events.containsAny(Player.EVENT_TIMELINE_CHANGED, Player.EVENT_MEDIA_ITEM_TRANSITION,
                                Player.EVENT_SHUFFLE_MODE_ENABLED_CHANGED, Player.EVENT_REPEAT_MODE_CHANGED)) refreshUpNext()
                    }
                })
                refresh()
                refreshUpNext()
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

    /** Never-ending discovery play: new songs like the one playing (or your top songs). */
    fun startEndless() = viewModelScope.launch {
        val c = controller ?: return@launch
        messages.tryEmit("Finding new songs…")
        val seed = c.currentMediaItem?.takeIf { MediaItems.videoId(it) != null && playingOn.value == null }
        val items = try {
            getApplication<Application>().dielify.endless.batch(listOfNotNull(seed?.let(MediaItems::videoId)), emptyList())
        } catch (e: ApiError) { messages.tryEmit(e.message ?: "Couldn't reach your PC"); return@launch }
        if (items.isEmpty()) { messages.tryEmit("Couldn't find new songs right now"); return@launch }
        val media = items.map(MediaItems::fromItem)
        c.shuffleModeEnabled = false
        if (seed != null) {  // keep the song playing now, then the new ones
            val pos = c.currentPosition
            c.setMediaItems(listOf(seed) + media, 0, pos)
        } else c.setMediaItems(media, 0, 0L)
        getApplication<Application>().dielify.endless.started(media, seed)
        c.prepare()
        c.play()
        messages.tryEmit("Never-ending discovery: thumbs down deletes a song again")
    }

    /** Song radio / artist radio: plays now, then keeps going with songs like it. */
    fun startRadio(source: com.dielify.app.net.RadioIn, label: String, first: MediaItem? = null) = viewModelScope.launch {
        val c = controller ?: return@launch
        messages.tryEmit("Starting $label…")
        val items = try { server.radio(source) } catch (e: ApiError) { messages.tryEmit(e.message ?: "Couldn't reach your PC"); return@launch }
        val media = listOfNotNull(first) + items.map(MediaItems::fromItem).filter { it.mediaId != first?.mediaId }
        if (media.isEmpty()) { messages.tryEmit("Couldn't find songs for this radio right now"); return@launch }
        c.shuffleModeEnabled = false
        c.setMediaItems(media, 0, 0L)
        getApplication<Application>().dielify.endless.started(media, null, asRadio = true)
        c.prepare()
        c.play()
    }

    /** Radio of the song playing now (Now playing). */
    fun radioFromCurrent() {
        val m = controller?.currentMediaItem ?: return
        val vid = MediaItems.videoId(m) ?: return run { messages.tryEmit("No radio for this song (it isn't from YouTube Music)") }
        songRadio(vid, m.mediaMetadata.title?.toString() ?: "this song", m)
    }

    /** Leave a song or playlist out of your taste (or count it again). */
    fun setTaste(kind: String, key: String, name: String, out: Boolean) = viewModelScope.launch {
        try {
            getApplication<Application>().dielify.taste.set(kind, key, name, out)
            messages.tryEmit(if (out) "\u201c$name\u201d won't shape your recommendations" else "\u201c$name\u201d counts in your taste again")
        } catch (e: ApiError) {
            messages.tryEmit(e.message ?: "Couldn't change that")
        }
    }

    fun songRadio(videoId: String, title: String, first: MediaItem? = null) =
        startRadio(com.dielify.app.net.RadioIn(videoId = videoId), "radio: $title", first)

    /** Bumped when songs leave the library, so open library lists load again. */
    val libraryChanged = MutableStateFlow(0)

    fun removeTracks(ids: List<Long>, albumId: Long? = null) = viewModelScope.launch {
        try {
            var removed = 0
            var deleted = 0
            if (albumId != null) server.removeAlbum(albumId).let { removed += it.removed; deleted += it.deleted }
            else ids.forEach { id -> server.removeTrack(id).let { removed += it.removed; deleted += it.deleted } }
            libraryChanged.value++
            messages.tryEmit("Removed $removed ${if (removed == 1) "song" else "songs"} from your library" +
                if (deleted < removed) " (kept on the PC for others in your household)" else "")
            if (albumId != null) back()
        } catch (e: ApiError) {
            messages.tryEmit(e.message ?: "Couldn't remove it")
        }
    }

    // --- Up next (the queue) ---------------------------------------------------------------------

    private fun entry(c: MediaController, i: Int): QueueEntry {
        val m = c.getMediaItemAt(i)
        return QueueEntry(i, m.mediaMetadata.title?.toString() ?: "", m.mediaMetadata.artist?.toString() ?: "",
            m.mediaMetadata.artworkUri?.toString())
    }

    /** Indexes of the songs after the current one, in the order they'll play. */
    private fun comingOrder(c: MediaController, limit: Int = 1000): List<Int> {
        val tl = c.currentTimeline
        if (tl.isEmpty) return emptyList()
        val out = mutableListOf<Int>()
        var i = tl.getNextWindowIndex(c.currentMediaItemIndex, Player.REPEAT_MODE_OFF, c.shuffleModeEnabled)
        while (i != androidx.media3.common.C.INDEX_UNSET && out.size < limit) {
            out += i
            i = tl.getNextWindowIndex(i, Player.REPEAT_MODE_OFF, c.shuffleModeEnabled)
        }
        return out
    }

    private fun refreshUpNext() {
        val c = controller ?: return
        if (c.mediaItemCount == 0) { _upNext.value = UpNext(); return }
        _upNext.value = UpNext(entry(c, c.currentMediaItemIndex), comingOrder(c).map { entry(c, it) }, c.shuffleModeEnabled)
    }

    /**
     * Before changing the order while shuffled: lay the list out in the shuffled order and
     * turn shuffle off, so "Play next" really plays next. Returns where each song moved to.
     */
    private fun flattenShuffle(c: MediaController): IntArray {
        val n = c.mediaItemCount
        val moved = IntArray(n) { it }
        if (!c.shuffleModeEnabled || n < 2) return moved
        val tl = c.currentTimeline
        val order = mutableListOf<Int>()
        var i = tl.getFirstWindowIndex(true)
        while (i != androidx.media3.common.C.INDEX_UNSET && order.size < n) { order += i; i = tl.getNextWindowIndex(i, Player.REPEAT_MODE_OFF, true) }
        c.shuffleModeEnabled = false
        val now = (0 until n).toMutableList()  // now[k] = which original song is at k
        order.forEachIndexed { k, want ->
            val from = now.indexOf(want)
            if (from != k) { c.moveMediaItem(from, k); now.add(k, now.removeAt(from)) }
        }
        now.forEachIndexed { k, orig -> moved[orig] = k }
        messages.tryEmit("Shuffle is off now: the shuffled order is kept, so your changes stick")
        return moved
    }

    fun queueJump(index: Int) = controller?.run { seekTo(index, 0); play() }
    fun queueRemove(index: Int) = controller?.removeMediaItem(index)

    fun queuePlayNext(index: Int) {
        val c = controller ?: return
        val i = flattenShuffle(c)[index]
        val cur = c.currentMediaItemIndex
        if (i == cur) return
        c.moveMediaItem(i, if (i > cur) cur + 1 else cur)
    }

    /** Drag in Up next: move the song at position [from] of the coming songs to [to]. */
    fun queueMove(from: Int, to: Int) {
        val c = controller ?: return
        if (from == to) return
        flattenShuffle(c)
        val base = c.currentMediaItemIndex + 1
        val last = c.mediaItemCount - 1
        val a = (base + from).coerceIn(base, last)
        val b = (base + to).coerceIn(base, last)
        if (a != b) c.moveMediaItem(a, b)
    }

    fun queueClear() {
        val c = controller ?: return
        flattenShuffle(c)
        val cur = c.currentMediaItemIndex
        if (cur + 1 < c.mediaItemCount) c.removeMediaItems(cur + 1, c.mediaItemCount)
    }

    /** Play next / Add to queue. With nothing playing, plays them. */
    private fun addToQueue(items: List<MediaItem>, next: Boolean) {
        val c = controller ?: return
        if (items.isEmpty()) return
        if (c.mediaItemCount == 0) { c.setMediaItems(items, 0, 0L); c.prepare(); c.play(); return }
        flattenShuffle(c)
        c.addMediaItems(if (next) c.currentMediaItemIndex + 1 else c.mediaItemCount, items)
        getApplication<Application>().dielify.endless.allow(items)
        val what = if (items.size == 1) "\"${items[0].mediaMetadata.title}\"" else "${items.size} songs"
        messages.tryEmit(if (next) "$what will play next" else "Added $what to the queue")
    }

    fun queueItems(items: List<Item>, next: Boolean) = addToQueue(items.filter { it.isSong }.map(MediaItems::fromItem), next)
    fun queueTracks(tracks: List<Track>, next: Boolean) = addToQueue(tracks.map(MediaItems::fromTrack), next)

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
