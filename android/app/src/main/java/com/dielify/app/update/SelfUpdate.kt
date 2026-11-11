package com.dielify.app.update

import android.content.Context
import android.util.Log
import com.dielify.app.dielify

/**
 * The PC asked this TV to update itself (0.9.12, remote "update" message). The PC installs updates on
 * TVs with adb when it can; a TV on a cable can't take that (Android only allows network debugging on
 * Wi-Fi), so it fetches the app from the PC and shows Android's install prompt here instead.
 * Android only lets an app open the prompt while it's on screen: if Dielify isn't, it waits until the
 * TV screen opens again.
 */
object SelfUpdate {
    private const val TAG = "SelfUpdate"
    @Volatile var visible = false      // TvActivity on screen
    @Volatile private var waiting = false

    suspend fun run(context: Context) {
        val app = context.dielify
        app.updater.check(force = true)
        val s = app.updater.state.value
        if (s !is UpdateState.Available) {
            Log.i(TAG, "Asked to update: nothing newer ($s)")
            return
        }
        if (!visible) {
            waiting = true
            Log.i(TAG, "Asked to update: waiting until Dielify is on screen")
            return
        }
        waiting = false
        val intent = if (!app.updater.canInstall()) app.updater.openInstallPermission()
        else app.updater.download(s.release) ?: return
        runCatching { context.startActivity(intent) }.onFailure { waiting = true; Log.w(TAG, "No install prompt: $it") }
    }

    /** TvActivity came on screen: show a prompt that had to wait. */
    suspend fun onScreen(context: Context) {
        visible = true
        if (waiting) run(context)
    }
}
