package com.dielify.app.net

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.text.Normalizer

@Serializable
data class Rating(val kind: String, val key: String, val name: String, val value: Int)

@Serializable data class RatingList(val ratings: List<Rating>, val removed: String? = null)

@Serializable
data class EndlessIn(val seeds: List<String>, val exclude: List<String>, val count: Int = 10)

/** Song radio (videoId) or artist radio (artistId = YouTube channel, or artist = a name);
 *  top-ups send seeds + exclude. */
@Serializable
data class RadioIn(
    @kotlinx.serialization.SerialName("video_id") val videoId: String? = null,
    @kotlinx.serialization.SerialName("artist_id") val artistId: String? = null,
    val artist: String? = null,
    val seeds: List<String> = emptyList(),
    val exclude: List<String> = emptyList(),
    val count: Int = 25,
)

@Serializable
data class Removed(val removed: Int, val deleted: Int)

@Serializable
data class RatingIn(
    val kind: String,
    val name: String,
    @SerialName("video_id") val videoId: String? = null,
    @SerialName("track_id") val trackId: Long? = null,
    val value: Int,
)

/**
 * Thumbs up / down / ban for songs and artists (see dielify/ratings.py). Kept in memory,
 * fetched from the PC when the app starts and after each change. The player skips banned
 * songs; the PC uses the ratings for discovery and mixes.
 */
class Ratings(private val server: Server) {
    private val _all = MutableStateFlow<List<Rating>>(emptyList())
    val all: StateFlow<List<Rating>> = _all.asStateFlow()

    suspend fun refresh() {
        runCatching { server.ratings() }.onSuccess { _all.value = it }
    }

    /** Thumbs up (UP), down (DOWN), ban (BAN) or clear (0). Throws ApiError if the PC said no.
     *  Returns the song's title if the PC deleted it (thumbs down on a discovery-play song). */
    suspend fun rate(kind: String, name: String, value: Int, videoId: String? = null, trackId: Long? = null): String? {
        val r = server.rate(RatingIn(kind, name, videoId, trackId, value))
        _all.value = r.ratings
        return r.removed
    }

    fun songValue(videoId: String?, trackId: Long?): Int {
        val key = songKey(videoId, trackId) ?: return 0
        return _all.value.firstOrNull { it.kind == "song" && it.key == key }?.value ?: 0
    }

    fun artistValue(name: String): Int {
        val key = artistKey(name)
        return _all.value.firstOrNull { it.kind == "artist" && it.key == key }?.value ?: 0
    }

    /** Ban wins; otherwise the song's own rating, else its artists'. */
    fun value(videoId: String?, trackId: Long?, artists: String?): Int {
        val a = splitArtists(artists).map(::artistValue)
        val s = songValue(videoId, trackId)
        if (s == BAN || BAN in a) return BAN
        if (s != 0) return s
        return if (DOWN in a) DOWN else (a.maxOrNull() ?: 0).coerceAtLeast(0)
    }

    fun banned(videoId: String?, trackId: Long?, artists: String?) = value(videoId, trackId, artists) == BAN

    companion object {
        const val UP = 1
        const val DOWN = -1
        const val BAN = -2
        private val SPLIT = Regex(""",|;| & | x | feat\.? | ft\.? | featuring | with """, RegexOption.IGNORE_CASE)
        private val SPACES = Regex("""\s+""")

        /** Same rule as ratings.py artist_key and app.js artistKey. */
        fun artistKey(name: String): String =
            Normalizer.normalize(name, Normalizer.Form.NFKC).lowercase().replace("&", "and").replace(SPACES, " ").trim()

        fun songKey(videoId: String?, trackId: Long?): String? = videoId ?: trackId?.let { "tr-$it" }

        fun splitArtists(text: String?): List<String> =
            (text ?: "").split(SPLIT).map { it.trim() }.filter { it.isNotEmpty() }
    }
}
