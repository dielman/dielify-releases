package com.dielify.app.net

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// 0.9.5 Discovery: time-of-day mix, new releases, artist About, follows, leave out of my taste.

@Serializable
data class NowMix(val title: String, val description: String, val tracks: List<Track>)

@Serializable
data class NewReleases(
    val items: List<Item>,
    val watching: Int,
    @SerialName("auto_download") val autoDownload: Boolean,
)

@Serializable
data class NewReleaseSettings(@SerialName("auto_download") val autoDownload: Boolean)

@Serializable
data class WebLink(val label: String, val url: String)

@Serializable
data class ArtistAbout(
    val name: String,
    val description: String? = null,
    val thumbnail: String? = null,
    @SerialName("channel_id") val channelId: String? = null,
    val links: List<WebLink> = emptyList(),
    val followed: Boolean = false,
)

@Serializable
data class FollowIn(val name: String, @SerialName("channel_id") val channelId: String? = null, val follow: Boolean = true)

@Serializable
data class Follow(val name: String, @SerialName("channel_id") val channelId: String? = null)

@Serializable
data class FollowList(val follows: List<Follow>)

@Serializable
data class TasteItem(val kind: String, val key: String, val name: String, @SerialName("added_at") val addedAt: Double? = null)

@Serializable
data class TasteIn(val kind: String, val key: String, val name: String, val out: Boolean = true)

@Serializable
data class TasteList(val items: List<TasteItem>)

/**
 * Songs and playlists left out of your taste (see dielify/taste.py): they still play, but
 * don't shape For you, mixes, the time-of-day mix or new releases. Fetched when the app
 * starts and after each change.
 */
class Taste(private val server: Server) {
    private val _all = MutableStateFlow<List<TasteItem>>(emptyList())
    val all: StateFlow<List<TasteItem>> = _all.asStateFlow()

    suspend fun refresh() {
        runCatching { server.taste() }.onSuccess { _all.value = it }
    }

    fun isOut(kind: String, key: String?): Boolean = key != null && _all.value.any { it.kind == kind && it.key == key }

    /** Throws ApiError if the PC said no. */
    suspend fun set(kind: String, key: String, name: String, out: Boolean) {
        _all.value = server.setTaste(TasteIn(kind, key, name, out))
    }

    companion object {
        fun songKey(videoId: String?, trackId: Long?): String? = videoId ?: trackId?.let { "tr-$it" }
    }
}
