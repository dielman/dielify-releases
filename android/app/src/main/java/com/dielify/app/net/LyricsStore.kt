package com.dielify.app.net

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import java.io.File

@Serializable data class LyricLine(val ms: Long, val text: String)

@Serializable
data class Lyrics(val synced: Boolean, val lines: List<LyricLine> = emptyList(), val text: String = "", val source: String? = null)

/**
 * Lyrics from the PC (see dielify/lyrics.py), kept on the phone in filesDir/lyrics so
 * songs played or saved before have them with no connection. Saved songs and the songs
 * about to play get theirs ahead of time. "No lyrics" is remembered for a day.
 */
class LyricsStore(context: Context, private val server: Server) {
    private val dir = File(context.filesDir, "lyrics").apply { mkdirs() }
    private val none = mutableMapOf<String, Long>()

    data class Song(val videoId: String?, val trackId: Long?, val title: String, val artist: String?,
                    val album: String?, val durationS: Int?) {
        val key: String? get() = videoId ?: trackId?.let { "tr-$it" }
    }

    private fun file(key: String) = File(dir, key.replace(Regex("[^A-Za-z0-9_-]"), "_") + ".json")

    /** Lyrics on the phone, without asking the PC. */
    fun cached(song: Song): Lyrics? = song.key?.let { file(it) }?.takeIf { it.exists() }
        ?.let { runCatching { Server.json.decodeFromString(Lyrics.serializer(), it.readText()) }.getOrNull() }

    /** The phone's copy, else the PC's. null: none, or the PC can't be reached. */
    suspend fun get(song: Song): Lyrics? = withContext(Dispatchers.IO) {
        val key = song.key ?: return@withContext null
        cached(song)?.let { return@withContext it }
        if ((none[key] ?: 0) > System.currentTimeMillis() - 86_400_000) return@withContext null
        val q = buildList {
            song.trackId?.let { add("track_id=$it") }
            song.videoId?.let { add("video_id=" + Uri.encode(it)) }
            if (song.trackId == null) {
                add("title=" + Uri.encode(song.title))
                song.artist?.let { add("artist=" + Uri.encode(it)) }
                song.album?.let { add("album=" + Uri.encode(it)) }
            }
            song.durationS?.let { add("duration_s=$it") }
        }.joinToString("&")
        try {
            val l = server.lyrics(q)
            file(key).writeText(Server.json.encodeToString(Lyrics.serializer(), l))
            trim()
            l
        } catch (e: ApiError) {
            if (e.code == 404) none[key] = System.currentTimeMillis()
            null
        } catch (_: Exception) {
            null
        }
    }

    private fun trim() {
        val files = dir.listFiles() ?: return
        if (files.size <= 3000) return
        files.sortedBy { it.lastModified() }.take(files.size - 3000).forEach { it.delete() }
    }
}
