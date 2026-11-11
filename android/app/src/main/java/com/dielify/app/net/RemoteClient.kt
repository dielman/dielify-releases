package com.dielify.app.net

import android.content.Context
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.UUID
import java.util.concurrent.TimeUnit

/** A song as devices pass it around: library songs by track id, others by YouTube id. */
@Serializable
data class RemoteSong(
    val trackId: Long? = null,
    val videoId: String? = null,
    val title: String = "",
    val artist: String? = null,
    val album: String? = null,
    val durationS: Int? = null,
    val thumbnail: String? = null,
    val gainDb: Double? = null,
)

@Serializable
data class RemoteState(
    val playing: Boolean = false,
    val positionMs: Long = 0,
    val durationMs: Long? = null,
    val volume: Float = 1f,
    val index: Int = -1,
    val queue: List<RemoteSong> = emptyList(),
) {
    val song: RemoteSong? get() = queue.getOrNull(index)
}

@Serializable
data class RemoteDevice(
    val device: String,
    val name: String,
    val kind: String,
    val state: RemoteState? = null,
    val idleS: Long = 0,
    /** Set on a kid's device in a parent's list (whose it is). */
    val person: String? = null,
)

@Serializable
data class RemoteCommand(
    val action: String,
    val positionMs: Long? = null,
    val value: Float? = null,
    val queue: List<RemoteSong>? = null,
    val index: Int? = null,
    val playing: Boolean? = null,
)

@Serializable private data class DevicesMsg(val you: String, val active: String? = null, val devices: List<RemoteDevice>,
                                             val kids: List<RemoteDevice> = emptyList())
@Serializable private data class CommandMsg(val from: String = "", val command: RemoteCommand)

/** What the phone's player does for remote control (set by the playback service). */
interface RemotePlayer {
    fun state(): RemoteState
    fun run(command: RemoteCommand, from: String)
}

/**
 * The phone's connection to the PC for remote control (see dielify/remote.py). Open while
 * the playback service runs (the app is open, or music is playing / was recently).
 * Reconnects by itself, finding the PC again if the network changed.
 */
class RemoteClient(private val context: Context, private val server: Server) {
    private val tv = context.packageManager.hasSystemFeature(android.content.pm.PackageManager.FEATURE_LEANBACK)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val client = server.http.newBuilder().readTimeout(0, TimeUnit.SECONDS)
        .pingInterval(20, TimeUnit.SECONDS).build()
    val deviceId: String = context.getSharedPreferences("remote", Context.MODE_PRIVATE).let { p ->
        p.getString("device", null) ?: ((if (isTv) "tv-" else "phone-") + UUID.randomUUID()).also { p.edit().putString("device", it).apply() }
    }
    /** A Google TV (0.9.10): it shows in "Play on" lists as a TV, under its own name ("Shed TV"). */
    private val isTv: Boolean get() = tv
    private val name: String = if (tv) android.provider.Settings.Global.getString(context.contentResolver,
        android.provider.Settings.Global.DEVICE_NAME)?.takeIf { it.isNotBlank() } ?: (Build.MODEL ?: "TV") else Build.MODEL ?: "Phone"

    private val _devices = MutableStateFlow<List<RemoteDevice>>(emptyList())
    /** The other devices of this profile (not this phone). */
    val devices: StateFlow<List<RemoteDevice>> = _devices.asStateFlow()
    private val _kids = MutableStateFlow<List<RemoteDevice>>(emptyList())
    /** A parent's view of their kids' devices (play / pause / skip / volume only, remote.py). */
    val kids: StateFlow<List<RemoteDevice>> = _kids.asStateFlow()
    private val _active = MutableStateFlow<String?>(null)
    /** The device that's playing (or last played): Spotify Connect's "active device". */
    val active: StateFlow<String?> = _active.asStateFlow()
    private val _connected = MutableStateFlow(false)
    val connected: StateFlow<Boolean> = _connected.asStateFlow()
    private val _errors = MutableStateFlow<String?>(null)
    val errors: StateFlow<String?> = _errors.asStateFlow()
    /** When the devices list arrived (positions in it are as of then). */
    @Volatile var listedAt = 0L
        private set

    private var player: RemotePlayer? = null
    private var socket: WebSocket? = null
    private var loop: Job? = null
    private var stateJob: Job? = null

    fun start(p: RemotePlayer) {
        player = p
        if (loop?.isActive == true) return
        loop = scope.launch {
            var wait = 2_000L
            while (true) {
                val closed = kotlinx.coroutines.CompletableDeferred<Unit>()
                try {
                    server.ensureConnected()
                    val url = server.url("/api/remote") ?: throw IllegalStateException("Not signed in")
                    socket = client.newWebSocket(Request.Builder().url(url).build(), Listener(closed))
                    closed.await()
                    if (_connected.value) wait = 2_000L
                } catch (e: Exception) {
                    Log.i(TAG, "Remote control not connected: $e")
                }
                _connected.value = false
                _devices.value = emptyList()
                _active.value = null
                socket = null
                delay(wait)
                wait = (wait * 2).coerceAtMost(60_000L)
            }
        }
    }

    fun stop() {
        loop?.cancel(); loop = null
        socket?.close(1000, "Bye"); socket = null
        player = null
        _connected.value = false
        _devices.value = emptyList()
    }

    /** Tell the other devices what's playing here (soon; several changes become one message). */
    fun stateChanged() {
        stateJob?.cancel()
        stateJob = scope.launch {
            delay(300)
            val st = player?.state() ?: return@launch
            send(buildJsonObject {
                put("type", "state")
                put("state", Server.json.encodeToJsonElement(RemoteState.serializer(), st).let(::snake))
            })
        }
    }

    fun command(to: String, command: RemoteCommand) = send(buildJsonObject {
        put("type", "command"); put("to", to)
        put("command", snake(Server.json.encodeToJsonElement(RemoteCommand.serializer(), command)))
    })

    /** Move the music: [from]'s queue and position go to [to], and [from] pauses. */
    fun transfer(from: String, to: String) = send(buildJsonObject {
        put("type", "transfer"); put("from", from); put("to", to)
    })

    /** Make [device] the active one: the music moves there (same queue and position). */
    fun select(device: String) = send(buildJsonObject { put("type", "select"); put("device", device) })

    /** The active device if it's another one and in use (playing, or paused under 10 minutes ago). */
    fun elsewhere(): RemoteDevice? {
        val id = _active.value ?: return null
        val d = _devices.value.firstOrNull { it.device == id } ?: return null
        val idle = d.idleS + if (d.state?.playing == true) 0 else (android.os.SystemClock.elapsedRealtime() - listedAt) / 1000
        return d.takeIf { idle < IDLE_S }
    }

    /** Where a song is now on [d], from the last list. */
    fun positionOf(d: RemoteDevice): Long {
        val st = d.state ?: return 0
        val moved = if (st.playing) android.os.SystemClock.elapsedRealtime() - listedAt else 0
        val pos = st.positionMs + moved
        return st.durationMs?.let { pos.coerceAtMost(it) } ?: pos
    }

    /** A line for the PC's log (to find out what's going on; no personal data). */
    fun note(text: String) {
        Log.i(TAG, text)
        send(buildJsonObject { put("type", "note"); put("text", text.take(200)) })
    }

    fun clearError() { _errors.value = null }

    private fun send(msg: JsonObject): Boolean = socket?.send(msg.toString()) ?: false

    private inner class Listener(private val closed: kotlinx.coroutines.CompletableDeferred<Unit>) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            webSocket.send(buildJsonObject {
                put("type", "hello"); put("device", deviceId); put("name", name); put("kind", if (tv) "tv" else "phone")
                put("version", com.dielify.app.BuildConfig.VERSION_CODE)
            }.toString())
            _connected.value = true
            stateChanged()  // the player is read on the main thread
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val msg = runCatching { Server.json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
            val camel = camel(msg)
            when (msg["type"]?.jsonPrimitive?.content) {
                "devices" -> runCatching { Server.json.decodeFromJsonElement(DevicesMsg.serializer(), camel) }.getOrNull()?.let { d ->
                    listedAt = android.os.SystemClock.elapsedRealtime()
                    _devices.value = d.devices.filter { it.device != deviceId }
                    _kids.value = d.kids
                    _active.value = d.active
                }
                "command" -> runCatching { Server.json.decodeFromJsonElement(CommandMsg.serializer(), camel) }.getOrNull()?.let { c ->
                    scope.launch { player?.run(c.command, c.from) }
                }
                "error" -> _errors.value = msg["message"]?.jsonPrimitive?.content
                // the PC can't install on this TV (on a cable): it asks the TV to update itself
                "update" -> if (tv) scope.launch { com.dielify.app.update.SelfUpdate.run(context.applicationContext) }
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
            closed.complete(Unit)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { closed.complete(Unit) }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            Log.i(TAG, "Remote control connection dropped: $t")
            server.forgetAddress()
            closed.complete(Unit)
        }
    }

    companion object {
        private const val TAG = "RemoteClient"
        const val IDLE_S = 600

        // The server speaks snake_case; our classes are camelCase.
        fun snakeKey(k: String) = k.replace(Regex("([a-z])([A-Z])")) { "${it.groupValues[1]}_${it.groupValues[2].lowercase()}" }
        fun camelKey(k: String) = k.replace(Regex("_([a-z])")) { it.groupValues[1].uppercase() }

        fun snake(e: kotlinx.serialization.json.JsonElement): kotlinx.serialization.json.JsonElement = convert(e, ::snakeKey)
        fun camel(e: kotlinx.serialization.json.JsonElement): kotlinx.serialization.json.JsonElement = convert(e, ::camelKey)

        fun convert(e: kotlinx.serialization.json.JsonElement, key: (String) -> String): kotlinx.serialization.json.JsonElement = when (e) {
            is JsonObject -> JsonObject(e.mapKeys { key(it.key) }.mapValues { convert(it.value, key) })
            is kotlinx.serialization.json.JsonArray -> kotlinx.serialization.json.JsonArray(e.map { convert(it, key) })
            else -> e
        }
    }
}
