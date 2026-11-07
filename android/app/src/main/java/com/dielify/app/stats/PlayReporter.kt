package com.dielify.app.stats

import android.content.Context
import com.dielify.app.net.PlayReport
import com.dielify.app.net.Server
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.ListSerializer
import java.io.File

/**
 * Plays waiting to be sent to the PC. Kept in a small file, so plays from saved songs with
 * no connection are sent later; each has a client_id, so resending never double-counts.
 */
class PlayReporter(context: Context, private val server: Server) {
    private val file = File(context.filesDir, "pending_plays.json")
    private val lock = Mutex()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val serializer = ListSerializer(PlayReport.serializer())

    private fun read(): List<PlayReport> =
        runCatching { Server.json.decodeFromString(serializer, file.readText()) }.getOrDefault(emptyList())

    private fun write(list: List<PlayReport>) {
        val tmp = File(file.path + ".tmp")
        tmp.writeText(Server.json.encodeToString(serializer, list.takeLast(MAX_KEPT)))
        tmp.renameTo(file)
    }

    fun add(play: PlayReport) {
        scope.launch {
            lock.withLock { write(read() + play) }
            flush()
        }
    }

    /** Send what's waiting (quietly does nothing if the PC can't be reached). */
    fun flush() {
        scope.launch {
            lock.withLock {
                val pending = read()
                if (pending.isEmpty() || server.account == null) return@withLock
                for (batch in pending.chunked(200)) {
                    if (runCatching { server.reportPlays(batch) }.isFailure) return@withLock
                    write(read().drop(batch.size))
                }
            }
        }
    }

    private companion object {
        const val MAX_KEPT = 5000
    }
}
