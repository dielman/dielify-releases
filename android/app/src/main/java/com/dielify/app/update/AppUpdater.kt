package com.dielify.app.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import com.dielify.app.BuildConfig
import com.dielify.app.net.Server
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

@Serializable
data class AndroidRelease(
    val version: String,
    @SerialName("version_code") val versionCode: Int,
    val url: String,
    val sha256: String,
    val size: Long,
)

@Serializable
data class ReleaseManifest(val version: String, val notes: String? = null, val android: AndroidRelease? = null)

sealed interface UpdateState {
    data object Idle : UpdateState
    data object Checking : UpdateState
    data object UpToDate : UpdateState
    data class Available(val release: AndroidRelease, val notes: String?) : UpdateState
    data class Downloading(val release: AndroidRelease, val fraction: Float) : UpdateState
    data class Failed(val message: String) : UpdateState
    data object NotSetUp : UpdateState
}

/**
 * Updates for the phone app, from the same GitHub release as the PC app.
 *
 * Safety: the download comes over HTTPS from GitHub, its SHA-256 must match the manifest,
 * and Android itself refuses an update that isn't signed with the same key as the
 * installed app (the key never leaves Josh's PC). You confirm every install.
 */
private val GITHUB_FILE = Regex("""^https://github\.com/([^/]+)/([^/]+)/releases/(?:latest/download|download/([^/]+))/([^/?#]+)$""")

class AppUpdater(private val context: Context) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()
    private val _state = MutableStateFlow<UpdateState>(UpdateState.Idle)
    val state: StateFlow<UpdateState> = _state.asStateFlow()
    private val prefs = context.getSharedPreferences("updates", Context.MODE_PRIVATE)

    /** Test builds (".debug") are installed over USB, not updated. */
    val enabled get() = BuildConfig.MANIFEST_URL.isNotEmpty() && !BuildConfig.APPLICATION_ID.endsWith(".debug")

    /**
     * GET a release file. When GitHub's download link fails (it returned 504 for days in
     * Nov 2026 while the API worked), the same file comes through GitHub's API instead.
     */
    private fun open(url: String): okhttp3.Response {
        var problem: Exception
        try {
            val r = http.newCall(Request.Builder().url(url).build()).execute()
            if (r.isSuccessful || r.code < 500) return r
            r.close()
            problem = IllegalStateException("GitHub answered HTTP ${r.code}")
        } catch (e: java.io.IOException) {
            problem = e
        }
        val m = GITHUB_FILE.find(url) ?: throw problem
        val (owner, repo, tag, name) = m.destructured
        val api = "https://api.github.com/repos/$owner/$repo/releases/" + if (tag.isEmpty()) "latest" else "tags/$tag"
        val asset = http.newCall(Request.Builder().url(api).header("Accept", "application/vnd.github+json").build())
            .execute().use { r ->
                if (!r.isSuccessful) throw problem
                Server.json.parseToJsonElement(r.body.string()).jsonObject["assets"]?.jsonArray
                    ?.map { it.jsonObject }?.firstOrNull { it["name"]?.jsonPrimitive?.content == name }
                    ?.get("url")?.jsonPrimitive?.content ?: throw problem
            }
        return http.newCall(Request.Builder().url(asset).header("Accept", "application/octet-stream").build()).execute()
    }

    /** At most once a day, unless asked. */
    suspend fun check(force: Boolean = false) {
        if (!enabled) { _state.value = UpdateState.NotSetUp; return }
        val now = System.currentTimeMillis()
        if (!force && now - prefs.getLong("last_check", 0) < 24 * 3600_000L && _state.value !is UpdateState.Idle) return
        _state.value = UpdateState.Checking
        _state.value = try {
            val m = withContext(Dispatchers.IO) {
                open(BuildConfig.MANIFEST_URL).use { r ->
                    if (!r.isSuccessful) throw IllegalStateException("GitHub answered HTTP ${r.code}")
                    Server.json.decodeFromString(ReleaseManifest.serializer(), r.body.string())
                }
            }
            prefs.edit().putLong("last_check", now).apply()
            val a = m.android
            if (a != null && a.versionCode > BuildConfig.VERSION_CODE) UpdateState.Available(a, m.notes)
            else UpdateState.UpToDate
        } catch (e: Exception) {
            UpdateState.Failed("Couldn't check for updates (${e.message ?: e.javaClass.simpleName})")
        }
    }

    /** Android asks once whether Dielify may install updates. */
    fun canInstall(): Boolean = context.packageManager.canRequestPackageInstalls()

    fun openInstallPermission(): Intent =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${BuildConfig.APPLICATION_ID}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    /** Download and check the update; returns the intent that opens Android's installer. */
    suspend fun download(release: AndroidRelease): Intent? {
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        val apk = File(dir, "Dielify-${release.version}.apk")
        return try {
            withContext(Dispatchers.IO) {
                open(release.url).use { r ->
                    if (!r.isSuccessful) throw IllegalStateException("GitHub answered HTTP ${r.code}")
                    val digest = MessageDigest.getInstance("SHA-256")
                    var done = 0L
                    r.body.byteStream().use { input ->
                        apk.outputStream().use { out ->
                            val buf = ByteArray(64 * 1024)
                            while (true) {
                                val n = input.read(buf)
                                if (n < 0) break
                                out.write(buf, 0, n)
                                digest.update(buf, 0, n)
                                done += n
                                _state.value = UpdateState.Downloading(release, (done.toFloat() / release.size).coerceIn(0f, 1f))
                            }
                        }
                    }
                    val hex = digest.digest().joinToString("") { "%02x".format(it) }
                    if (!hex.equals(release.sha256, ignoreCase = true) || done != release.size) {
                        apk.delete()
                        throw IllegalStateException("the update didn't download properly: try again")
                    }
                }
            }
            _state.value = UpdateState.Available(release, null)
            val uri = FileProvider.getUriForFile(context, "${BuildConfig.APPLICATION_ID}.updates", apk)
            Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        } catch (e: Exception) {
            apk.delete()
            _state.value = UpdateState.Failed("Update download failed: ${e.message}")
            null
        }
    }
}
