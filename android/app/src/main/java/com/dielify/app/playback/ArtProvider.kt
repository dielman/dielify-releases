package com.dielify.app.playback

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import com.dielify.app.dielify
import kotlinx.coroutines.runBlocking
import java.io.File
import java.io.FileNotFoundException

/**
 * Cover art for Android Auto and the system media controls, which can only load
 * content:// pictures. Serves the phone's saved cover if there is one, otherwise fetches
 * it from the PC once and keeps it in the app's cache.
 *
 * Read-only, pictures only: content://com.dielify.app.art/track/<id> or /album/<id>.
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
        val id = seg.getOrNull(1)?.toLongOrNull()
        if (seg.size != 2 || id == null || kind !in setOf("track", "album")) throw FileNotFoundException(uri.toString())

        if (kind == "track") app.saved.coverFile(id)?.let { return open(it) }

        val cached = File(ctx.cacheDir, "art/$kind-$id.jpg")
        if (!cached.exists()) {
            cached.parentFile?.mkdirs()
            val path = if (kind == "track") "/api/library/tracks/$id/cover" else "/api/library/albums/$id/cover"
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

    override fun getType(uri: Uri) = "image/jpeg"
    override fun query(uri: Uri, p: Array<out String>?, s: String?, a: Array<out String>?, o: String?): Cursor? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, s: String?, a: Array<out String>?) = 0
    override fun update(uri: Uri, v: ContentValues?, s: String?, a: Array<out String>?) = 0

    companion object {
        const val AUTHORITY = "com.dielify.app.art"
        private const val SIZE = 600
        fun trackArt(id: Long): Uri = Uri.parse("content://$AUTHORITY/track/$id")
        fun albumArt(id: Long): Uri = Uri.parse("content://$AUTHORITY/album/$id")
    }
}
