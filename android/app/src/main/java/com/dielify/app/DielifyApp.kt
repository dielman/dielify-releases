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
    /** Streamed songs kept for a while + the next few fetched ahead (one per process). */
    val songCache by lazy { com.dielify.app.playback.SongCache(this) }
    /** Remote control between devices (connected while the playback service runs). */
    val remote by lazy { com.dielify.app.net.RemoteClient(this, server) }
    /** Thumbs up / down / ban (the player skips banned songs). */
    val ratings by lazy { com.dielify.app.net.Ratings(server) }
    val taste by lazy { com.dielify.app.net.Taste(server) }
    /** Never-ending discovery play (Discover). */
    /** Lyrics, kept on the phone once seen (Now playing > lyrics). */
    val lyrics by lazy { com.dielify.app.net.LyricsStore(this, server) }
    /** Sleep timer (Now playing); the playback service pauses. */
    val sleep by lazy { com.dielify.app.playback.SleepTimer() }
    /** "Even out volume" (Settings). */
    val levelPrefs by lazy { getSharedPreferences("playback", MODE_PRIVATE) }
    /** Keep favourites on the phone automatically (Settings). */
    val keep by lazy { com.dielify.app.saved.KeepOnPhone(this) }
    val endless by lazy { com.dielify.app.playback.EndlessPlay(server) }

    override fun onCreate() {
        super.onCreate()
        accounts = AccountStore(this)
        server = Server(this, accounts)
        saved = SavedSongs(this)
        updater = AppUpdater(this)
        plays = PlayReporter(this, server)
        if (keep.enabled) keep.schedule()
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
