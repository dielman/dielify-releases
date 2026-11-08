package com.dielify.app.playback

import android.os.Looper
import android.os.SystemClock
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.SimpleBasePlayer
import androidx.media3.common.util.UnstableApi
import com.dielify.app.net.RemoteClient
import com.dielify.app.net.RemoteCommand
import com.dielify.app.net.RemoteDevice
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

/**
 * Another device (the PC, another phone) as a Media3 player. While that device is the
 * active one, the playback service hands this to the media session instead of the phone's
 * own player, so the app's player screens, the notification, the lock screen and Bluetooth
 * buttons all show and control the music on that device (Spotify Connect style).
 */
@OptIn(UnstableApi::class)
class RemoteDevicePlayer(private val remote: RemoteClient) : SimpleBasePlayer(Looper.getMainLooper()) {
    private var device: RemoteDevice? = null
    private var items: List<MediaItem> = emptyList()
    // our own guesses until the device reports back (so buttons don't flick back)
    private var playing = false
    private var index = -1
    private var positionMs = 0L
    private var positionAt = SystemClock.elapsedRealtime()
    private var volume = 1f

    /** New report from the device (or a different device became active). */
    fun update(d: RemoteDevice?) {
        device = d
        val st = d?.state
        if (st != null) {
            items = st.queue.mapNotNull(MediaItems::fromSong)
            playing = st.playing
            index = if (st.index in items.indices) st.index else -1
            positionMs = remote.positionOf(d)
            positionAt = SystemClock.elapsedRealtime()
            volume = st.volume
        } else {
            items = emptyList(); playing = false; index = -1; positionMs = 0
        }
        invalidateState()
    }

    val deviceName: String? get() = device?.name

    private fun now(): Long {
        val moved = if (playing) SystemClock.elapsedRealtime() - positionAt else 0
        val dur = device?.state?.durationMs
        return (positionMs + moved).let { if (dur != null && dur > 0) it.coerceAtMost(dur) else it }
    }

    override fun getState(): State {
        val commands = Player.Commands.Builder().addAll(
            COMMAND_PLAY_PAUSE, COMMAND_PREPARE, COMMAND_STOP,
            COMMAND_SEEK_TO_NEXT, COMMAND_SEEK_TO_NEXT_MEDIA_ITEM,
            COMMAND_SEEK_TO_PREVIOUS, COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM,
            COMMAND_SEEK_IN_CURRENT_MEDIA_ITEM, COMMAND_SEEK_TO_MEDIA_ITEM, COMMAND_SEEK_TO_DEFAULT_POSITION,
            COMMAND_SEEK_BACK, COMMAND_SEEK_FORWARD,
            COMMAND_SET_VOLUME, COMMAND_GET_VOLUME,
            COMMAND_SET_MEDIA_ITEM, COMMAND_CHANGE_MEDIA_ITEMS,
            COMMAND_GET_TIMELINE, COMMAND_GET_CURRENT_MEDIA_ITEM, COMMAND_GET_METADATA,
        ).build()
        val durationMs = device?.state?.durationMs
        val playlist = items.mapIndexed { i, item ->
            MediaItemData.Builder("$i:${item.mediaId}")
                .setMediaItem(item)
                .setDurationUs(if (i == index && durationMs != null && durationMs > 0) durationMs * 1000 else C.TIME_UNSET)
                .build()
        }
        val b = State.Builder()
            .setAvailableCommands(commands)
            .setPlaylist(playlist)
            .setPlayWhenReady(playing, PLAY_WHEN_READY_CHANGE_REASON_REMOTE)
            .setPlaybackState(if (playlist.isEmpty()) STATE_IDLE else STATE_READY)
            .setVolume(volume)
        if (index >= 0) {
            b.setCurrentMediaItemIndex(index)
            b.setContentPositionMs { now() }
        }
        return b.build()
    }

    private fun send(c: RemoteCommand): ListenableFuture<*> {
        device?.let { remote.command(it.device, c) }
        invalidateState()
        return Futures.immediateVoidFuture()
    }

    override fun handleSetPlayWhenReady(playWhenReady: Boolean): ListenableFuture<*> {
        positionMs = now(); positionAt = SystemClock.elapsedRealtime()
        playing = playWhenReady
        return send(RemoteCommand(if (playWhenReady) "play" else "pause"))
    }

    override fun handleSeek(mediaItemIndex: Int, positionMs: Long, seekCommand: Int): ListenableFuture<*> {
        val pos = if (positionMs == C.TIME_UNSET) 0 else positionMs
        val c = when (seekCommand) {
            COMMAND_SEEK_TO_NEXT, COMMAND_SEEK_TO_NEXT_MEDIA_ITEM -> RemoteCommand("next")
            COMMAND_SEEK_TO_PREVIOUS, COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM -> RemoteCommand("previous")
            COMMAND_SEEK_IN_CURRENT_MEDIA_ITEM, COMMAND_SEEK_BACK, COMMAND_SEEK_FORWARD -> RemoteCommand("seek", positionMs = pos)
            else -> RemoteCommand("jump", index = mediaItemIndex, positionMs = pos)
        }
        if (mediaItemIndex in items.indices) index = mediaItemIndex
        this.positionMs = pos; positionAt = SystemClock.elapsedRealtime()
        return send(c)
    }

    override fun handleSetVolume(volume: Float): ListenableFuture<*> {
        this.volume = volume
        return send(RemoteCommand("volume", value = volume))
    }

    override fun handleSetMediaItems(mediaItems: MutableList<MediaItem>, startIndex: Int, startPositionMs: Long): ListenableFuture<*> {
        val songs = mediaItems.map(MediaItems::toSong)
        if (songs.isEmpty()) return Futures.immediateVoidFuture()
        val start = if (startIndex == C.INDEX_UNSET) 0 else startIndex.coerceIn(0, songs.size - 1)
        items = mediaItems.toList(); index = start; playing = true
        positionMs = if (startPositionMs == C.TIME_UNSET) 0 else startPositionMs
        positionAt = SystemClock.elapsedRealtime()
        return send(RemoteCommand("load", queue = songs, index = start, positionMs = positionMs, playing = true))
    }

    // Up next edits: the other device gets the new list around the song it's playing
    // ("queue" command), so that song plays on uninterrupted.
    private fun sendQueue(list: List<MediaItem>, current: MediaItem?): ListenableFuture<*> {
        val at = list.indexOfFirst { it === current }
        if (at < 0) return Futures.immediateVoidFuture()
        items = list; index = at
        return send(RemoteCommand("queue", queue = list.map(MediaItems::toSong), index = at))
    }

    private val current: MediaItem? get() = items.getOrNull(index)

    override fun handleAddMediaItems(index: Int, mediaItems: MutableList<MediaItem>): ListenableFuture<*> {
        if (current == null) return handleSetMediaItems(mediaItems, 0, 0)
        val l = items.toMutableList()
        l.addAll(index.coerceIn(0, l.size), mediaItems)
        return sendQueue(l, current)
    }

    override fun handleRemoveMediaItems(fromIndex: Int, toIndex: Int): ListenableFuture<*> {
        if (index in fromIndex until toIndex) return Futures.immediateVoidFuture()  // not the song playing
        val l = items.toMutableList()
        l.subList(fromIndex.coerceIn(0, l.size), toIndex.coerceIn(0, l.size)).clear()
        return sendQueue(l, current)
    }

    override fun handleMoveMediaItems(fromIndex: Int, toIndex: Int, newIndex: Int): ListenableFuture<*> {
        val l = items.toMutableList()
        val part = l.subList(fromIndex, toIndex).toList()
        l.subList(fromIndex, toIndex).clear()
        l.addAll(newIndex.coerceIn(0, l.size), part)
        return sendQueue(l, current)
    }

    override fun handlePrepare(): ListenableFuture<*> = Futures.immediateVoidFuture()
    override fun handleStop(): ListenableFuture<*> = handleSetPlayWhenReady(false)
}
