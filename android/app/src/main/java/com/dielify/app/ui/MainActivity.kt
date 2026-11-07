package com.dielify.app.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle

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
    val account by vm.account.collectAsStateWithLifecycle()
    if (account == null) {
        SignInScreen(vm)
        return
    }
    val stack by vm.stack.collectAsStateWithLifecycle()
    BackHandler(enabled = stack.size > 1) { vm.back() }
    Box(Modifier.fillMaxSize()) {
        when (val screen = stack.last()) {
            Screen.Library -> LibraryScreen(vm)
            is Screen.AlbumPage -> AlbumScreen(vm, screen)
            is Screen.ArtistPage -> ArtistScreen(vm, screen)
            Screen.NowPlaying -> NowPlayingScreen(vm)
            Screen.Settings -> SettingsScreen(vm)
        }
    }
}
