package com.dielify.app.net

import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.Uri
import android.os.Build
import android.util.Log
import com.dielify.app.Account
import com.dielify.app.AccountStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** A message for the user, plus the HTTP status (0 = couldn't reach the PC). */
class ApiError(message: String, val code: Int = 0) : Exception(message)

/** Which of the PC's addresses the phone is using right now. */
sealed interface Link {
    data object Unknown : Link
    data class Up(val address: String, val viaTailscale: Boolean) : Link
    data object Down : Link
}

/**
 * The connection to the Dielify server on the PC.
 *
 * The PC has several addresses (home network, Tailscale). Before talking to it the app
 * asks each one for /api/health and uses the first that answers, in the order typed
 * (home first, so music doesn't go through Tailscale at home). When the phone's network
 * changes, or a call fails, it asks again.
 */
class Server(private val context: Context, private val accounts: AccountStore) {
    @Volatile var account: Account? = accounts.load()
        private set
    @Volatile private var base: HttpUrl? = null
    private val pickLock = Mutex()
    private val _link = MutableStateFlow<Link>(Link.Unknown)
    val link: StateFlow<Link> = _link.asStateFlow()

    /** Adds "Authorization: Bearer <token>" to requests for the server's own addresses only. */
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val req = chain.request()
            val acc = account
            if (acc != null && req.header("Authorization") == null && isServer(req.url, acc.addresses)) {
                chain.proceed(req.newBuilder().header("Authorization", "Bearer ${acc.token}").build())
            } else chain.proceed(req)
        }
        .build()

    private val probeClient = http.newBuilder()
        .connectTimeout(2, TimeUnit.SECONDS).readTimeout(3, TimeUnit.SECONDS)
        .callTimeout(4, TimeUnit.SECONDS).build()

    init {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        cm.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = forgetAddress()
            override fun onLost(network: Network) = forgetAddress()
        })
    }

    /** Android 17+ blocks the home network unless the user allows "local network" access. */
    fun hasLocalNetworkPermission(): Boolean =
        Build.VERSION.SDK_INT < 37 ||
            context.checkSelfPermission(LOCAL_NETWORK) == PackageManager.PERMISSION_GRANTED

    /** Make the next call find the PC again (e.g. after leaving home Wi-Fi). */
    fun forgetAddress() {
        base = null
    }

    // --- choosing an address ------------------------------------------------------------

    private suspend fun probe(url: HttpUrl): Boolean = withContext(Dispatchers.IO) {
        try {
            probeClient.newCall(Request.Builder().url(url.resolve("api/health")!!).build()).execute().use {
                it.isSuccessful && it.body.string().contains("\"status\"")
            }
        } catch (e: IOException) {
            Log.w(TAG, "No answer from ${url.host}:${url.port}: $e")
            false
        }
    }

    private suspend fun pick(addresses: List<String>): HttpUrl = pickLock.withLock {
        base?.takeIf { isServer(it, addresses) }?.let { return it }
        val urls = addresses.mapNotNull(::parseAddress)
        if (urls.isEmpty()) throw ApiError("Enter the PC's address")
        val answered = coroutineScope { urls.map { async { probe(it) } }.awaitAll() }
        val found = urls.zip(answered).firstOrNull { it.second }?.first
        if (found == null) {
            _link.value = Link.Down
            if (!hasLocalNetworkPermission()) throw ApiError(NO_PERMISSION)
            throw ApiError(
                "Can't reach your PC. Check that Dielify is running on it, and that the " +
                    "phone is on home Wi-Fi or connected to Tailscale."
            )
        }
        base = found
        _link.value = Link.Up("${found.host}:${found.port}", isTailscale(found.host))
        found
    }

    private suspend fun current(): HttpUrl {
        val acc = account ?: throw ApiError("Not signed in", 401)
        return base ?: pick(acc.addresses)
    }

    /** Absolute URL for a server path like "/api/library/albums/3/cover", for the UI. */
    fun url(path: String): String? {
        val b = base ?: account?.addresses?.firstNotNullOfOrNull(::parseAddress) ?: return null
        return b.resolve(path.removePrefix("/"))?.toString()
    }

    /**
     * The player and lock-screen art use "dielify://server/<path>" so that queued songs keep
     * working when the phone switches between home Wi-Fi and Tailscale. Turned into a real
     * URL here, at the moment the data is fetched (on a background thread).
     */
    fun resolveMedia(uri: Uri): Uri {
        if (uri.scheme != MEDIA_SCHEME) return uri
        val b = base ?: runBlocking { current() }
        val path = (uri.encodedPath ?: "/").removePrefix("/")
        val query = uri.encodedQuery?.let { "?$it" } ?: ""
        return Uri.parse(b.resolve(path)!!.toString() + query)
    }

    // --- calls -----------------------------------------------------------------------------

    private suspend fun call(build: (HttpUrl) -> Request): String = withContext(Dispatchers.IO) {
        val first = current()
        try {
            run(build(first))
        } catch (e: IOException) {
            forgetAddress()                  // maybe the phone changed network: look again
            val again = current()
            try { run(build(again)) } catch (e2: IOException) {
                forgetAddress()
                throw ApiError("Lost the connection to your PC (${e2.message ?: "network error"})")
            }
        }
    }

    private fun run(req: Request): String = http.newCall(req).execute().use { r ->
        val body = r.body.string()
        if (!r.isSuccessful) throw ApiError(errorMessage(r.code, body), r.code)
        body
    }

    private suspend inline fun <reified T> get(path: String): T =
        json.decodeFromString(call { Request.Builder().url(it.resolve(path)!!).build() })

    private suspend fun send(method: String, path: String, body: String = ""): String = call {
        Request.Builder().url(it.resolve(path)!!)
            .method(method, if (method == "DELETE" && body.isEmpty()) null else body.toRequestBody(JSON_TYPE))
            .build()
    }

    /** Sign in with the phone login made in Dielify on the PC (Settings > Phone logins). */
    suspend fun signIn(addresses: List<String>, username: String, password: String): Account {
        val target = pick(addresses)
        val body = json.encodeToString(LoginRequest.serializer(),
            LoginRequest(username.trim(), password.trim(), "${Build.MANUFACTURER} ${Build.MODEL}".take(60)))
        val text = withContext(Dispatchers.IO) {
            try {
                run(Request.Builder().url(target.resolve("api/auth/login")!!)
                    .post(body.toRequestBody(JSON_TYPE)).build())
            } catch (e: IOException) {
                forgetAddress()
                throw ApiError("Lost the connection to your PC (${e.message ?: "network error"})")
            }
        }
        val result = json.decodeFromString(LoginResult.serializer(), text)
        val acc = Account(addresses, result.username, result.profile, result.deviceId, result.token)
        accounts.save(acc)
        account = acc
        return acc
    }

    /** Sign out: withdraw this phone's token on the PC (if reachable), forget it here. */
    suspend fun signOut() {
        val acc = account ?: return
        runCatching { send("DELETE", "api/auth/device-token/${acc.deviceId}") }
        accounts.clearToken()
        account = null
        base = null
        _link.value = Link.Unknown
    }

    suspend fun albums(): List<Album> = get<AlbumList>("api/library/albums?sort=alphabeticalByArtist&limit=500").albums
    suspend fun recentAlbums(): List<Album> = get<AlbumList>("api/library/albums?sort=newest&limit=500").albums
    suspend fun artists(): List<Artist> = get<ArtistList>("api/library/artists").artists
    suspend fun album(id: Long): AlbumDetail = get("api/library/albums/$id")
    suspend fun artist(id: Long): ArtistDetail = get("api/library/artists/$id")
    suspend fun search(q: String): LibrarySearch =
        get("api/library/search?limit=50&q=" + Uri.encode(q))

    suspend fun played(trackId: Long) {
        send("POST", "api/library/tracks/$trackId/played")
    }

    companion object {
        const val MEDIA_SCHEME = "dielify"
        const val LOCAL_NETWORK = "android.permission.ACCESS_LOCAL_NETWORK"
        const val NO_PERMISSION = "Dielify isn't allowed to use your home network. Allow it: " +
            "Android Settings > Apps > Dielify > Permissions > Nearby devices (local network)."
        private const val TAG = "Dielify"
        const val DEFAULT_PORT = 4747
        private val JSON_TYPE = "application/json".toMediaType()
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

        /** "192.168.1.249", "192.168.1.249:4747" or "http://host:port" -> http://host:port/ */
        fun parseAddress(text: String): HttpUrl? {
            var t = text.trim().trimEnd('/')
            if (t.isEmpty()) return null
            if (!t.contains("://")) t = "http://$t"
            val url = t.toHttpUrlOrNull() ?: return null
            val hostPart = t.substringAfter("://").substringBefore('/')
            val hasPort = Regex(":\\d+$").containsMatchIn(hostPart)
            return url.newBuilder().apply { if (!hasPort) port(DEFAULT_PORT) }.encodedPath("/").build()
        }

        fun isServer(url: HttpUrl, addresses: List<String>): Boolean =
            addresses.mapNotNull(::parseAddress).any { it.host == url.host && it.port == url.port }

        /** Tailscale hands out addresses in 100.64.0.0/10. */
        fun isTailscale(host: String): Boolean {
            val parts = host.split('.').mapNotNull { it.toIntOrNull() }
            return parts.size == 4 && parts[0] == 100 && parts[1] in 64..127 || host.endsWith(".ts.net")
        }

        fun errorMessage(code: Int, body: String): String {
            val detail = runCatching {
                json.parseToJsonElement(body).jsonObject["detail"]?.jsonPrimitive?.content
            }.getOrNull()
            return when {
                code == 401 && detail != null -> detail
                code == 401 -> "This phone's sign-in isn't accepted any more. Sign in again."
                detail != null -> detail
                else -> "The PC answered with an error (HTTP $code)"
            }
        }
    }
}
