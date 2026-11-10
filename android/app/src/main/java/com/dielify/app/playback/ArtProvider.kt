package com.dielify.app.playback

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import com.dielify.app.BuildConfig
import com.dielify.app.dielify
import kotlinx.coroutines.runBlocking
import java.io.File
import java.io.FileNotFoundException

/**
 * Cover art for Android Auto and the system media controls, which can only load
 * content:// pictures. Serves the phone's saved cover if there is one, otherwise fetches
 * it from the PC once and keeps it in the app's cache.
 *
 * Read-only, pictures only: content://com.dielify.app.art/track/<id>, /album/<id>, /playlist/<id>,
 * /artist/<id>, or /web/<YouTube picture address, base64> (only YouTube / Google image hosts).
 * Other apps on the phone could ask it for cover pictures, nothing else.
 */
class ArtProvider : ContentProvider() {
    override fun onCreate() = true

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        if (mode != "r") throw FileNotFoundException("read-only")
        val ctx = context ?: throw FileNotFoundException()
        val app = ctx.dielify
        val seg = uri.pathSegments
        val kind = seg.getOrNull(0)
        if (seg.size == 2 && kind == "web") return open(web(ctx, seg[1]))
        val id = seg.getOrNull(1)?.toLongOrNull()
        if (seg.size != 2 || id == null || kind !in setOf("track", "album", "playlist", "artist")) throw FileNotFoundException(uri.toString())

        if (kind == "track") app.saved.coverFile(id)?.let { return open(it) }

        val cached = File(ctx.cacheDir, "art/$kind-$id.jpg")
        if (!cached.exists()) {
            cached.parentFile?.mkdirs()
            val path = when (kind) {
                "track" -> "/api/library/tracks/$id/cover"
                "album" -> "/api/library/albums/$id/cover"
                "playlist" -> "/api/playlists/$id/cover"
                else -> "/api/library/artists/$id/image"
            }
            val tmp = File(cached.path + ".part")
            try {
                runBlocking { app.server.ensureConnected() }
                app.server.fetchTo("$path?size=$SIZE", tmp)
                tmp.renameTo(cached)
            } catch (e: Exception) {
                tmp.delete()
                throw FileNotFoundException("No cover: ${e.message}")
            }
        }
        return open(cached)
    }

    private fun open(f: File) = ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY)

    /** A YouTube picture (album / playlist / song thumbnails), fetched once into the cache. */
    private fun web(ctx: android.content.Context, encoded: String): File {
        val url = runCatching { String(android.util.Base64.decode(encoded, android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP)) }
            .getOrNull() ?: throw FileNotFoundException("bad picture address")
        val host = Uri.parse(url).host ?: ""
        if (!url.startsWith("https://") || WEB_HOSTS.none { host == it || host.endsWith(".$it") })
            throw FileNotFoundException("not a YouTube picture")
        val cached = File(ctx.cacheDir, "art/web-${Integer.toHexString(url.hashCode())}-${url.length}.jpg")
        if (!cached.exists()) {
            cached.parentFile?.mkdirs()
            val tmp = File(cached.path + ".part")
            try {
                ctx.dielify.server.http.newCall(okhttp3.Request.Builder().url(url).build()).execute().use { r ->
                    if (!r.isSuccessful) throw FileNotFoundException("HTTP ${r.code}")
                    tmp.outputStream().use { r.body.byteStream().copyTo(it) }
                }
                tmp.renameTo(cached)
            } catch (e: Exception) {
                tmp.delete()
                throw FileNotFoundException("No picture: ${e.message}")
            }
        }
        return cached
    }

    override fun getType(uri: Uri) = "image/jpeg"
    override fun query(uri: Uri, p: Array<out String>?, s: String?, a: Array<out String>?, o: String?): Cursor? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, s: String?, a: Array<out String>?) = 0
    override fun update(uri: Uri, v: ContentValues?, s: String?, a: Array<out String>?) = 0

    companion object {
        const val AUTHORITY = BuildConfig.APPLICATION_ID + ".art"
        private const val SIZE = 600
        fun trackArt(id: Long): Uri = Uri.parse("content://$AUTHORITY/track/$id")
        fun albumArt(id: Long): Uri = Uri.parse("content://$AUTHORITY/album/$id")
        fun playlistArt(id: Long): Uri = Uri.parse("content://$AUTHORITY/playlist/$id")
        fun artistArt(id: Long): Uri = Uri.parse("content://$AUTHORITY/artist/$id")
        /** The car only loads content:// pictures: YouTube's https thumbnails go through here. */
        fun webArt(url: String): Uri = Uri.parse("content://$AUTHORITY/web/" +
            android.util.Base64.encodeToString(url.toByteArray(), android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP))
        private val WEB_HOSTS = listOf("ytimg.com", "googleusercontent.com", "ggpht.com")
    }
}
