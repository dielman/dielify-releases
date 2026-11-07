package com.dielify.app

import android.app.Application
import android.content.Context
import coil3.ImageLoader
import coil3.PlatformContext
import coil3.SingletonImageLoader
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import coil3.request.crossfade
import com.dielify.app.net.Server
import com.dielify.app.saved.SavedSongs
import com.dielify.app.update.AppUpdater
import com.dielify.app.stats.PlayReporter

class DielifyApp : Application(), SingletonImageLoader.Factory {
    lateinit var accounts: AccountStore
        private set
    lateinit var server: Server
        private set
    lateinit var saved: SavedSongs
        private set
    lateinit var updater: AppUpdater
        private set
    lateinit var plays: PlayReporter
        private set

    override fun onCreate() {
        super.onCreate()
        accounts = AccountStore(this)
        server = Server(this, accounts)
        saved = SavedSongs(this)
        updater = AppUpdater(this)
        plays = PlayReporter(this, server)
    }

    // Cover art goes through the server's HTTP client, which adds the sign-in token
    // (only for the Dielify server's own addresses).
    override fun newImageLoader(context: PlatformContext): ImageLoader =
        ImageLoader.Builder(context)
            .components { add(OkHttpNetworkFetcherFactory(callFactory = { server.http })) }
            .crossfade(true)
            .build()
}

val Context.dielify: DielifyApp get() = applicationContext as DielifyApp
