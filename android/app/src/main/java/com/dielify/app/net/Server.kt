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

    /** Find a working address now (used by background work before downloading). */
    suspend fun ensureConnected() {
        current()
    }

    /** Download a server path into a file (blocking; call off the main thread). */
    fun fetchTo(path: String, into: java.io.File) {
        val url = url(path) ?: throw IOException("Not signed in")
        http.newCall(Request.Builder().url(url).build()).execute().use { r ->
            if (!r.isSuccessful) throw IOException("The PC answered HTTP ${r.code}")
            into.outputStream().use { out -> r.body.byteStream().copyTo(out) }
        }
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
            .method(method, if (method == "GET" || (method == "DELETE" && body.isEmpty())) null else body.toRequestBody(JSON_TYPE))
            .build()
    }

    /** Sign in with the phone login made in Dielify on the PC (Settings > People & phones). */
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

    // --- 0.9.10: a TV signing itself in (no password: a parent's phone allows it) ---

    /** Ask the PC at [address] for a sign-in code to show as a QR code. */
    suspend fun pairStart(address: String, deviceName: String): PairStart {
        val target = pick(listOf(address))
        val body = json.encodeToString(PairStartIn.serializer(), PairStartIn(deviceName.take(60)))
        return json.decodeFromString(PairStart.serializer(), withContext(Dispatchers.IO) {
            try {
                run(Request.Builder().url(target.resolve("api/pair/start")!!).post(body.toRequestBody(JSON_TYPE)).build())
            } catch (e: IOException) {
                forgetAddress()
                throw ApiError("Lost the connection to your PC (${e.message ?: "network error"})")
            }
        })
    }

    /** Has the code been allowed yet? When it has, this TV is signed in (and remembered). */
    suspend fun pairPoll(address: String, secret: String): PairStatus {
        val target = pick(listOf(address))
        val body = json.encodeToString(PairPollIn.serializer(), PairPollIn(secret))
        val s = json.decodeFromString(PairStatus.serializer(), withContext(Dispatchers.IO) {
            try {
                run(Request.Builder().url(target.resolve("api/pair/poll")!!).post(body.toRequestBody(JSON_TYPE)).build())
            } catch (e: IOException) {
                forgetAddress()
                throw ApiError("Lost the connection to your PC (${e.message ?: "network error"})")
            }
        })
        if (s.status == "approved" && s.token != null) {
            val acc = Account(listOf(address), s.username ?: "", s.profile ?: "", s.deviceId ?: 0, s.token)
            accounts.save(acc)
            account = acc
        }
        return s
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

    suspend fun track(id: Long): Track = get("api/library/tracks/$id")
    suspend fun me(): Me = get("api/me")
    /** Songs already on the PC that someone else in the household has and you don't. */
    suspend fun household(q: String): List<Track> =
        get<TrackList>("api/library/household?limit=300&q=" + Uri.encode(q)).tracks
    suspend fun addToLibrary(ids: List<Long>): Int =
        json.decodeFromString(Added.serializer(), send("POST", "api/library/add", json.encodeToString(AddToLibrary.serializer(), AddToLibrary(ids)))).added

    // YouTube Music (these ask YouTube through the PC, so they need the PC to be online)
    suspend fun home(): HomeFeed = get("api/discover/home?shelves=10")
    suspend fun charts(): Charts = get("api/discover/charts")
    suspend fun similar(videoId: String): List<Item> =
        get<ItemList>("api/discover/similar/" + Uri.encode(videoId) + "?limit=40").items
    suspend fun ytSearch(q: String, type: String): List<Item> =
        get<ItemList>("api/yt/search?limit=40&type=$type&q=" + Uri.encode(q)).items
    suspend fun myPlaylists(): List<Item> = get<ItemList>("api/yt/my-playlists").items

    // Playlists in Dielify (synced with YouTube Music when ytId is set)
    suspend fun playlists(): List<PlaylistSummary> = get<PlaylistList>("api/playlists").playlists
    suspend fun mixes(): MixStatus = get("api/mixes")
    suspend fun outside(): List<OutsideShelf> = get<OutsideDiscovery>("api/discover/outside").shelves
    suspend fun playlist(id: Long): PlaylistDetail = get("api/playlists/$id")
    suspend fun createPlaylist(name: String, onYoutube: Boolean): PlaylistDetail =
        json.decodeFromString(send("POST", "api/playlists",
            json.encodeToString(NewPlaylist.serializer(), NewPlaylist(name, onYoutube))))
    suspend fun importPlaylist(ytId: String): PlaylistDetail =
        json.decodeFromString(send("POST", "api/playlists/import",
            json.encodeToString(ImportPlaylist.serializer(), ImportPlaylist(ytId))))
    suspend fun renamePlaylist(id: Long, name: String): PlaylistDetail =
        json.decodeFromString(send("PATCH", "api/playlists/$id",
            json.encodeToString(RenamePlaylist.serializer(), RenamePlaylist(name))))
    suspend fun deletePlaylist(id: Long, onYoutube: Boolean) {
        send("DELETE", "api/playlists/$id?on_youtube=$onYoutube")
    }
    suspend fun addToPlaylist(id: Long, songs: List<SongIn>): PlaylistDetail =
        json.decodeFromString(send("POST", "api/playlists/$id/songs",
            json.encodeToString(AddSongs.serializer(), AddSongs(songs))))
    suspend fun removeFromPlaylist(id: Long, entryId: Long, onYoutube: Boolean): PlaylistDetail =
        json.decodeFromString(send("DELETE", "api/playlists/$id/entries/$entryId?on_youtube=$onYoutube"))
    suspend fun syncPlaylist(id: Long): PlaylistDetail = json.decodeFromString(send("POST", "api/playlists/$id/sync"))
    suspend fun ytAlbum(browseId: String): YtCollection = get("api/yt/album/" + Uri.encode(browseId))
    suspend fun ytPlaylist(playlistId: String): YtCollection = get("api/yt/playlist/" + Uri.encode(playlistId))

    // Downloads (onto the PC)
    suspend fun requestDownload(item: Item, next: Boolean): DownloadList {
        val type = if (item.type == "video") "video" else item.type
        val body = json.encodeToString(DownloadRequest.serializer(),
            DownloadRequest(type, item.id, item.title, item.artists, item.album, next))
        return json.decodeFromString(send("POST", "api/downloads", body))
    }
    suspend fun activeDownloads(): DownloadList = get("api/downloads?active=true&limit=300")
    suspend fun finishedDownloads(): DownloadList = get("api/downloads?finished=true&limit=60")
    suspend fun moveDownloadNext(id: Long) {
        send("POST", "api/downloads/$id/next")
    }
    suspend fun clearFinishedDownloads() {
        send("POST", "api/downloads/clear-finished")
    }

    suspend fun cancelDownload(id: Long) {
        send("DELETE", "api/downloads/$id")
    }

    suspend fun reportPlays(plays: List<PlayReport>) {
        send("POST", "api/plays", json.encodeToString(PlayBatch.serializer(), PlayBatch(plays)))
    }
    suspend fun stats(period: String): Stats = get("api/stats?limit=25&period=$period")
    suspend fun ratings(): List<Rating> = get<RatingList>("api/ratings").ratings
    suspend fun rate(r: RatingIn): RatingList =
        json.decodeFromString(RatingList.serializer(), send("PUT", "api/ratings", json.encodeToString(RatingIn.serializer(), r)))
    /** Never-ending discovery play: the next new songs (the PC queues their downloads). */
    suspend fun radio(body: RadioIn): List<Item> =
        json.decodeFromString(ItemList.serializer(), send("POST", "api/radio", json.encodeToString(RadioIn.serializer(), body))).items
    /** Take songs out of your library (the PC deletes a file only if nobody else has it). */
    suspend fun removeTrack(id: Long): Removed = json.decodeFromString(Removed.serializer(), send("DELETE", "api/library/tracks/$id"))
    suspend fun removeAlbum(id: Long): Removed = json.decodeFromString(Removed.serializer(), send("DELETE", "api/library/albums/$id"))
    suspend fun endless(body: EndlessIn): List<Item> =
        json.decodeFromString(ItemList.serializer(), send("POST", "api/discover/endless", json.encodeToString(EndlessIn.serializer(), body))).items
    suspend fun forYou(): ForYou = get("api/discover/for-you")
    /** New for you: releases from the artists you follow and play most. */
    suspend fun newReleases(): NewReleases = get("api/discover/new")
    suspend fun setNewReleases(autoDownload: Boolean): NewReleases = json.decodeFromString(NewReleases.serializer(),
        send("PUT", "api/discover/new/settings", json.encodeToString(NewReleaseSettings.serializer(), NewReleaseSettings(autoDownload))))
    suspend fun artistAbout(name: String): ArtistAbout =
        get("api/artists/about?name=" + java.net.URLEncoder.encode(name, "UTF-8"))
    suspend fun follows(): List<Follow> = get<FollowList>("api/follows").follows
    suspend fun follow(body: FollowIn): List<Follow> = json.decodeFromString(FollowList.serializer(),
        send("PUT", "api/follows", json.encodeToString(FollowIn.serializer(), body))).follows
    suspend fun taste(): List<TasteItem> = get<TasteList>("api/taste").items
    /** A 12-hour "play only" key for a speaker (Chromecast / Nest). */
    suspend fun castToken(): CastToken = json.decodeFromString(CastToken.serializer(), send("POST", "api/cast/token"))
    suspend fun recapPeriods(): List<RecapPeriod> = get<RecapPeriods>("api/recap/periods").periods
    suspend fun recap(period: String): Recap = get("api/recap?period=$period")
    // --- 0.9.8 Together ---
    suspend fun sharePlaylist(id: Long, shared: Boolean): PlaylistDetail = json.decodeFromString(PlaylistDetail.serializer(),
        send("PUT", "api/playlists/$id/share", json.encodeToString(ShareIn.serializer(), ShareIn(shared))))
    suspend fun blend(): BlendState = get("api/blend")
    suspend fun setBlend(on: Boolean): BlendState = json.decodeFromString(BlendState.serializer(),
        send("PUT", "api/blend", json.encodeToString(BlendIn.serializer(), BlendIn(on))))
    /** The household's Jam, or null. */
    suspend fun jam(): Jam? {
        val body = send("GET", "api/jam")
        return if (body.isBlank() || body.trim() == "null") null else json.decodeFromString(Jam.serializer(), body)
    }
    private fun jamOf(body: String): Jam = json.decodeFromString(Jam.serializer(), body)
    suspend fun startJam(body: JamStart): Jam = jamOf(send("POST", "api/jam", json.encodeToString(JamStart.serializer(), body)))
    suspend fun joinJam(): Jam = jamOf(send("POST", "api/jam/join"))
    suspend fun addToJam(songs: List<JamSongIn>): Jam =
        jamOf(send("POST", "api/jam/songs", json.encodeToString(JamAdd.serializer(), JamAdd(songs))))
    suspend fun removeFromJam(id: Long): Jam = jamOf(send("DELETE", "api/jam/songs/$id"))
    suspend fun jamPlaying(body: JamPlaying): Jam =
        jamOf(send("POST", "api/jam/playing", json.encodeToString(JamPlaying.serializer(), body)))
    suspend fun leaveJam() { send("POST", "api/jam/leave") }
    suspend fun endJam() { send("DELETE", "api/jam") }
    suspend fun setTaste(body: TasteIn): List<TasteItem> = json.decodeFromString(TasteList.serializer(),
        send("PUT", "api/taste", json.encodeToString(TasteIn.serializer(), body))).items
    // --- 0.9.10: signing a TV in (pair_api.py) ---
    suspend fun pairInfo(code: String): PairInfo = get("api/pair/" + java.net.URLEncoder.encode(code, "UTF-8"))
    suspend fun pairApprove(code: String, person: String): PairApproved = json.decodeFromString(PairApproved.serializer(),
        send("POST", "api/pair/" + java.net.URLEncoder.encode(code, "UTF-8") + "/approve",
            json.encodeToString(PairApproveIn.serializer(), PairApproveIn(person))))
    suspend fun pairRefuse(code: String) { send("POST", "api/pair/" + java.net.URLEncoder.encode(code, "UTF-8") + "/refuse") }
    /** Songs to keep on the phone automatically (Settings). */
    suspend fun keepList(liked: Boolean, top: Int, playlists: Set<Long>): List<Track> =
        get<TrackList>("api/keep?liked=$liked&top=$top&playlists=" + playlists.joinToString(",")).tracks

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
                else -> "Something went wrong on the PC (error $code). Try again."
            }
        }
    }
}
