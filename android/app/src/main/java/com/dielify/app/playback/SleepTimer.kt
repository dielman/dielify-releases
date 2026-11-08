package com.dielify.app.playback

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Sleep timer: pause after some minutes (fading out over the last 15 s) or at the end of
 * the song playing. The playback service does the pausing, so it works with the app
 * closed, and for music on another device too.
 */
class SleepTimer {
    data class State(val endsAt: Long = 0, val songEnd: Boolean = false, val songIndex: Int = -1, val songId: String? = null) {
        val on get() = endsAt > 0 || songEnd
    }

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    fun minutes(m: Int) { _state.value = State(endsAt = System.currentTimeMillis() + m * 60_000L) }
    fun endOfSong(index: Int, mediaId: String?) { _state.value = State(songEnd = true, songIndex = index, songId = mediaId) }
    fun off() { _state.value = State() }

    companion object {
        const val FADE_MS = 15_000L
    }
}
