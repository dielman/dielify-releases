package com.dielify.app.tv

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.util.Log
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

/** A Dielify PC announcing itself on the home network (announce.py). */
data class FoundPc(val name: String, val address: String)  // address = "192.168.1.249:4747"

/**
 * Finds Dielify PCs on the home network (mDNS / DNS-SD, service "_dielify._tcp"), so the TV
 * never needs an address typed with a remote. Emits the PCs found so far.
 */
fun findPcs(context: Context): Flow<List<FoundPc>> = callbackFlow {
    val nsd = context.getSystemService(NsdManager::class.java)
    val found = linkedMapOf<String, FoundPc>()

    fun resolved(info: NsdServiceInfo) {
        @Suppress("DEPRECATION")
        val host = (if (Build.VERSION.SDK_INT >= 34) info.hostAddresses.firstOrNull { it.address.size == 4 } else info.host)
            ?.hostAddress ?: return
        val name = info.attributes["name"]?.let { String(it) } ?: info.serviceName.removePrefix("Dielify on ")
        found[info.serviceName] = FoundPc(name, "$host:${info.port}")
        trySend(found.values.toList())
    }

    val listener = object : NsdManager.DiscoveryListener {
        override fun onServiceFound(info: NsdServiceInfo) {
            @Suppress("DEPRECATION")
            nsd.resolveService(info, object : NsdManager.ResolveListener {
                override fun onServiceResolved(r: NsdServiceInfo) = resolved(r)
                override fun onResolveFailed(r: NsdServiceInfo, code: Int) { Log.w(TAG, "Couldn't resolve ${r.serviceName}: $code") }
            })
        }
        override fun onServiceLost(info: NsdServiceInfo) {
            if (found.remove(info.serviceName) != null) trySend(found.values.toList())
        }
        override fun onDiscoveryStarted(type: String) {}
        override fun onDiscoveryStopped(type: String) {}
        override fun onStartDiscoveryFailed(type: String, code: Int) { Log.w(TAG, "Discovery failed: $code") }
        override fun onStopDiscoveryFailed(type: String, code: Int) {}
    }
    nsd.discoverServices("_dielify._tcp", NsdManager.PROTOCOL_DNS_SD, listener)
    awaitClose { runCatching { nsd.stopServiceDiscovery(listener) } }
}

private const val TAG = "Dielify"
