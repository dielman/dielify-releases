package com.dielify.app.ui

import androidx.compose.animation.core.tween
import androidx.compose.animation.togetherWith
import androidx.compose.animation.fadeOut
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.slideInVertically
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.material3.SnackbarHostState
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.net.Server

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        openPairLink(intent)
        setContent {
            DielifyTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    App(vm)
                }
            }
        }
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        openPairLink(intent)
    }

    /** A TV's QR code scanned with the phone's own camera app: dielify://pair/<code>. */
    private fun openPairLink(intent: android.content.Intent?) {
        val uri = intent?.data ?: return
        if (uri.scheme == "dielify" && uri.host == "pair") vm.open(Screen.PairTv(uri.lastPathSegment))
    }
}

@Composable
fun App(vm: AppViewModel) {
    // Android 17+: ask once for local-network access, needed to reach the PC at home.
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        vm.server.forgetAddress()
    }
    LaunchedEffect(Unit) {
        if (!vm.server.hasLocalNetworkPermission()) ask.launch(Server.LOCAL_NETWORK)
    }
    val account by vm.account.collectAsStateWithLifecycle()
    if (account == null) {
        SignInScreen(vm)
        return
    }
    val stack by vm.stack.collectAsStateWithLifecycle()
    val tab by vm.tab.collectAsStateWithLifecycle()
    BackHandler(enabled = stack.size > 1 || tab != Tab.Discover) {
        if (!vm.back()) vm.selectTab(Tab.Discover)
    }
    // Every screen in the back stack keeps its state (search words, results, tab, scroll
    // position), so Back returns to it exactly as it was.
    val saved = androidx.compose.runtime.saveable.rememberSaveableStateHolder()
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.messages.collect { snackbar.showSnackbar(it) } }
    // Keep the Downloads badge current while the app is on screen.
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                vm.refreshDownloadCount()
                delay(if (vm.activeDownloads.value > 0) 3_000 else 15_000)
            }
        }
    }
    AddToPlaylistDialog(vm)
    DevicePicker(vm)
    UpNextSheet(vm)
    CompositionLocalProvider(LocalSnackbar provides snackbar) { Box(Modifier.fillMaxSize()) {
        androidx.compose.animation.AnimatedContent(
            targetState = stack.size to stack.last(),
            transitionSpec = {
                val (from, fromScreen) = initialState
                val (to, toScreen) = targetState
                when {
                    toScreen == Screen.NowPlaying -> (slideInVertically { it } + fadeIn()) togetherWith fadeOut(tween(220))
                    fromScreen == Screen.NowPlaying -> fadeIn(tween(220)) togetherWith (slideOutVertically { it } + fadeOut())
                    to > from -> (slideInHorizontally { it / 5 } + fadeIn(tween(220))) togetherWith fadeOut(tween(160))
                    to < from -> fadeIn(tween(220)) togetherWith (slideOutHorizontally { it / 5 } + fadeOut(tween(160)))
                    else -> fadeIn(tween(180)) togetherWith fadeOut(tween(120))
                }
            },
            label = "screens",
        ) { (size, screen) ->
        saved.SaveableStateProvider("$size:$screen") { when (screen) {
            Screen.Library -> RootScreen(vm)
            is Screen.AlbumPage -> AlbumScreen(vm, screen)
            is Screen.ArtistPage -> ArtistScreen(vm, screen)
            Screen.NowPlaying -> NowPlayingScreen(vm)
            Screen.Settings -> SettingsScreen(vm)
            is Screen.YtAlbumPage -> YtCollectionScreen(vm, screen.name, screen.browseId) { vm.server.ytAlbum(screen.browseId) }
            is Screen.YtPlaylistPage -> YtCollectionScreen(vm, screen.name, screen.playlistId) { vm.server.ytPlaylist(screen.playlistId) }
            is Screen.SimilarPage -> SimilarScreen(vm, screen)
            is Screen.SavedAlbumPage -> SavedAlbumScreen(vm, screen)
            Screen.StatsPage -> StatsScreen(vm)
            is Screen.PlaylistPage -> PlaylistScreen(vm, screen)
            is Screen.JamPage -> JamScreen(vm)
            is Screen.PairTv -> PairTvScreen(vm, screen.code)
        } }
        }
    } }
}
