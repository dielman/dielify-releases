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
import com.dielify.app.net.Track
import com.dielify.app.playback.MediaItems
import com.dielify.app.playback.PlaybackService
import com.google.common.util.concurrent.MoreExecutors
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface Screen {
    data object Library : Screen
    data class AlbumPage(val id: Long, val name: String) : Screen
    data class ArtistPage(val id: Long, val name: String) : Screen
    data object NowPlaying : Screen
    data object Settings : Screen
}

data class PlayerUi(
    val hasItem: Boolean = false,
    val title: String = "",
    val artist: String = "",
    val album: String = "",
    val trackId: Long? = null,
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

    private val _account = MutableStateFlow(server.account)
    val account: StateFlow<Account?> = _account.asStateFlow()

    private val _stack = MutableStateFlow<List<Screen>>(listOf(Screen.Library))
    val stack: StateFlow<List<Screen>> = _stack.asStateFlow()

    private val _player = MutableStateFlow(PlayerUi())
    val player: StateFlow<PlayerUi> = _player.asStateFlow()

    var controller: MediaController? = null
        private set

    val lastAddresses: List<String> get() = accounts.lastAddresses()
    val lastUsername: String get() = accounts.lastUsername()

    init {
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

    fun back(): Boolean {
        if (_stack.value.size <= 1) return false
        _stack.value = _stack.value.dropLast(1)
        return true
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
