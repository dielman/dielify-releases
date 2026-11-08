package com.dielify.app.saved

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.dielify.app.dielify
import com.dielify.app.net.ApiError
import java.util.concurrent.TimeUnit

/**
 * Keep favourites on the phone automatically (Settings): thumbs-up songs, your most played
 * and chosen playlists are saved without tapping Save, and checked twice a day. Songs this
 * put on the phone go again when they stop qualifying (unless you saved them yourself).
 */
class KeepOnPhone(private val context: Context) {
    private val prefs = context.getSharedPreferences("keep", Context.MODE_PRIVATE)

    var liked: Boolean
        get() = prefs.getBoolean("liked", false)
        set(v) { prefs.edit().putBoolean("liked", v).apply(); changed() }
    var top: Int
        get() = prefs.getInt("top", 0)
        set(v) { prefs.edit().putInt("top", v).apply(); changed() }
    var playlists: Set<Long>
        get() = prefs.getStringSet("playlists", emptySet())!!.mapNotNull { it.toLongOrNull() }.toSet()
        set(v) { prefs.edit().putStringSet("playlists", v.map { it.toString() }.toSet()).apply(); changed() }
    var wifiOnly: Boolean
        get() = prefs.getBoolean("wifi_only", true)
        set(v) { prefs.edit().putBoolean("wifi_only", v).apply(); schedule(); changed() }

    /** Track ids this put on the phone (the ones it may take off again). */
    internal var auto: Set<Long>
        get() = prefs.getStringSet("auto", emptySet())!!.mapNotNull { it.toLongOrNull() }.toSet()
        set(v) { prefs.edit().putStringSet("auto", v.map { it.toString() }.toSet()).apply() }

    val enabled get() = liked || top > 0 || playlists.isNotEmpty()

    private fun constraints() = Constraints.Builder()
        .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED).build()

    /** Twice a day (and when the settings change). */
    fun schedule() {
        val req = PeriodicWorkRequestBuilder<KeepWorker>(12, TimeUnit.HOURS).setConstraints(constraints()).build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork("keep", ExistingPeriodicWorkPolicy.UPDATE, req)
    }

    fun runNow() {
        val req = OneTimeWorkRequestBuilder<KeepWorker>().setConstraints(constraints()).build()
        WorkManager.getInstance(context).enqueueUniqueWork("keep-now", ExistingWorkPolicy.REPLACE, req)
    }

    private fun changed() { schedule(); runNow() }
}

class KeepWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext.dielify
        val keep = app.keep
        val saved = app.saved
        return try {
            val wanted = if (keep.enabled) {
                app.server.ensureConnected()
                app.server.keepList(keep.liked, keep.top, keep.playlists)
            } else emptyList()
            val have = saved.songs.value.keys
            val adding = wanted.filter { it.id !in have }
            saved.save(adding, unmetered = keep.wifiOnly)
            val wantedIds = wanted.map { it.id }.toSet()
            val stale = keep.auto - wantedIds
            if (stale.isNotEmpty()) saved.remove(stale)
            keep.auto = (keep.auto - stale) + adding.map { it.id }
            Result.success()
        } catch (e: ApiError) {
            if (runAttemptCount < 3) Result.retry() else Result.failure()
        } catch (e: java.io.IOException) {
            app.server.forgetAddress()
            if (runAttemptCount < 3) Result.retry() else Result.failure()
        }
    }
}
