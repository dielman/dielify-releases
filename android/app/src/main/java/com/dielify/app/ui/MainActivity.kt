package com.dielify.app.ui

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
        setContent {
            DielifyTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    App(vm)
                }
            }
        }
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
    BackHandler(enabled = stack.size > 1 || tab != Tab.Library) {
        if (!vm.back()) vm.selectTab(Tab.Library)
    }
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
    LyricsSheet(vm)
    CompositionLocalProvider(LocalSnackbar provides snackbar) { Box(Modifier.fillMaxSize()) {
        when (val screen = stack.last()) {
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
        }
    } }
}
