package com.dielify.app.saved

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.dielify.app.dielify
import com.dielify.app.net.ApiError
import com.dielify.app.net.Server
import com.dielify.app.net.Track
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/** One song kept on the phone: its details (as the PC described it) and its files. */
@Serializable
data class SavedSong(
    val track: Track,
    val file: String,            // file name inside the saved folder
    val cover: String? = null,   // cover art file name, if the song has one
    val bytes: Long = 0,
    val savedAt: Long = 0,
)

/**
 * Songs saved on the phone, for listening with no connection to the PC.
 *
 * Files live in the app's private storage (no other app can read them; app backups are
 * off). `index.json` lists them. The PC is still the master copy: saving makes a copy,
 * removing only deletes the phone's copy.
 */
class SavedSongs(private val context: Context) {
    private val dir = File(context.filesDir, "saved").apply { mkdirs() }
    private val indexFile = File(dir, "index.json")
    private val lock = Any()
    private val _songs = MutableStateFlow(load())
    val songs: StateFlow<Map<Long, SavedSong>> = _songs.asStateFlow()

    private val work get() = WorkManager.getInstance(context)

    /** Track ids that are waiting to be saved or being saved right now. */
    val pending: Flow<Set<Long>> = work.getWorkInfosByTagFlow(TAG).map { infos ->
        infos.filter { it.state == WorkInfo.State.ENQUEUED || it.state == WorkInfo.State.RUNNING ||
            it.state == WorkInfo.State.BLOCKED }
            .mapNotNull { info -> info.tags.firstOrNull { it.startsWith(TRACK_TAG) }?.removePrefix(TRACK_TAG)?.toLongOrNull() }
            .toSet()
    }

    private fun load(): Map<Long, SavedSong> = runCatching {
        Server.json.decodeFromString(ListSerializer(SavedSong.serializer()), indexFile.readText())
            .filter { File(dir, it.file).exists() }
            .associateBy { it.track.id }
    }.getOrDefault(emptyMap())

    private fun write(songs: Map<Long, SavedSong>) {
        val tmp = File(dir, "index.json.tmp")
        tmp.writeText(Server.json.encodeToString(ListSerializer(SavedSong.serializer()), songs.values.toList()))
        tmp.renameTo(indexFile)
        _songs.value = songs
    }

    fun audioFile(trackId: Long): File? = _songs.value[trackId]?.let { File(dir, it.file) }?.takeIf { it.exists() }
    fun coverFile(trackId: Long): File? = _songs.value[trackId]?.cover?.let { File(dir, it) }?.takeIf { it.exists() }
    fun totalBytes(): Long = _songs.value.values.sumOf { it.bytes }

    /** Queue songs to be copied to the phone (in the background; survives leaving the app). */
    fun save(tracks: List<Track>) {
        for (t in tracks) {
            if (_songs.value.containsKey(t.id)) continue
            val request = OneTimeWorkRequestBuilder<SaveWorker>()
                .setInputData(workDataOf(KEY_TRACK to Server.json.encodeToString(Track.serializer(), t)))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .addTag(TAG).addTag(TRACK_TAG + t.id)
                .build()
            work.enqueueUniqueWork("save-${t.id}", ExistingWorkPolicy.KEEP, request)
        }
    }

    fun remove(trackIds: Collection<Long>) {
        for (id in trackIds) work.cancelUniqueWork("save-$id")
        synchronized(lock) {
            val now = _songs.value.toMutableMap()
            for (id in trackIds) {
                now.remove(id)?.let { s ->
                    File(dir, s.file).delete()
                    s.cover?.let { File(dir, it).delete() }
                }
            }
            write(now)
        }
    }

    fun removeAll() {
        work.cancelAllWorkByTag(TAG)
        remove(_songs.value.keys.toList())
    }

    /** Called by the worker: download the song (and its cover) from the PC, then list it. */
    internal suspend fun download(server: Server, t: Track) = withContext(Dispatchers.IO) {
        val ext = t.suffix.ifEmpty { "audio" }.filter { it.isLetterOrDigit() }
        val audioName = "${t.id}.$ext"
        val audio = File(dir, audioName)
        val tmp = File(dir, "$audioName.part")
        fetch(server, t.streamUrl, tmp)
        if (!tmp.renameTo(audio)) throw IOException("Couldn't store the song on the phone")
        var coverName: String? = null
        t.coverUrl?.let { url ->
            val cover = File(dir, "${t.id}.jpg")
            if (runCatching { fetch(server, "$url?size=600", cover) }.isSuccess) coverName = cover.name
        }
        synchronized(lock) {
            write(_songs.value + (t.id to SavedSong(t, audioName, coverName, audio.length(), System.currentTimeMillis())))
        }
    }

    private fun fetch(server: Server, path: String, into: File) {
        val url = server.url(path) ?: throw IOException("Not signed in")
        server.http.newCall(Request.Builder().url(url).build()).execute().use { r ->
            if (r.code == 401) throw ApiError("Sign-in refused", 401)
            if (!r.isSuccessful) throw IOException("The PC answered HTTP ${r.code}")
            into.outputStream().use { out -> r.body.byteStream().copyTo(out) }
        }
    }

    companion object {
        const val TAG = "save-song"
        const val TRACK_TAG = "track-"
        const val KEY_TRACK = "track"
    }
}

class SaveWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext.dielify
        val track = inputData.getString(SavedSongs.KEY_TRACK)
            ?.let { runCatching { Server.json.decodeFromString(Track.serializer(), it) }.getOrNull() }
            ?: return Result.failure()
        return try {
            app.server.ensureConnected()
            app.saved.download(app.server, track)
            Result.success()
        } catch (e: ApiError) {
            if (e.code == 401 || e.code == 404) Result.failure()
            else if (runAttemptCount < 8) Result.retry() else Result.failure()
        } catch (e: IOException) {
            app.server.forgetAddress()
            if (runAttemptCount < 8) Result.retry() else Result.failure()
        }
    }
}
