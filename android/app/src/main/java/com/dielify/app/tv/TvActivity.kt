package com.dielify.app.tv

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.net.Server
import com.dielify.app.ui.AppViewModel
import com.dielify.app.ui.Bg
import com.dielify.app.ui.DielifyTheme
import com.dielify.app.ui.Accent

/** The Google TV front door (0.9.10). Same app, same engine as the phone; TV screens. */
class TvActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { DielifyTheme { androidx.compose.material3.Surface(Modifier.fillMaxSize(), color = Bg) { TvApp(vm) } } }
    }
}

/** Where the TV is: one of the menu's places, or a page opened from one. */
sealed interface TvPage {
    data object Home : TvPage
    data object Library : TvPage
    data object Search : TvPage
    data object Settings : TvPage
    data object NowPlaying : TvPage
    data class Album(val id: Long, val name: String) : TvPage
    data class Artist(val id: Long, val name: String) : TvPage
    data class Playlist(val id: Long, val name: String) : TvPage
    data class YtAlbum(val id: String, val name: String) : TvPage
    data class YtPlaylist(val id: String, val name: String) : TvPage
}

/** The TV's own little navigation: a stack of pages, Back pops. */
class TvNav {
    var stack by mutableStateOf<List<TvPage>>(listOf(TvPage.Home))
    val top get() = stack.last()
    fun open(p: TvPage) { stack = stack + p }
    fun place(p: TvPage) { stack = listOf(p) }
    fun back(): Boolean = if (stack.size > 1) { stack = stack.dropLast(1); true } else false
}

@Composable
fun TvApp(vm: AppViewModel) {
    // Android 17+: local-network access, to reach the PC (same as the phone).
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { vm.server.forgetAddress() }
    LaunchedEffect(Unit) { if (!vm.server.hasLocalNetworkPermission()) ask.launch(Server.LOCAL_NETWORK) }
    val account by vm.account.collectAsStateWithLifecycle()
    if (account == null) { TvSignIn(vm); return }

    val nav = remember { TvNav() }
    val player by vm.player.collectAsStateWithLifecycle()
    BackHandler(enabled = nav.stack.size > 1 || nav.top != TvPage.Home) { if (!nav.back()) nav.place(TvPage.Home) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.messages.collect { snackbar.showSnackbar(it) } }

    if (nav.top == TvPage.NowPlaying) {
        TvNowPlaying(vm, nav)
        return
    }
    Box(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxSize()) {
            TvMenu(nav, player.hasItem)
            Box(Modifier.weight(1f).fillMaxHeight()) { TvPageContent(vm, nav) }
        }
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).padding(bottom = TvPadV))
    }
}

@Composable
private fun TvMenu(nav: TvNav, playing: Boolean) {
    val first = remember { FocusRequester() }
    val root = nav.stack.first()
    Column(Modifier.width(176.dp).fillMaxHeight().background(Color.Black.copy(alpha = 0.35f)).padding(vertical = TvPadV, horizontal = 12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 8.dp, bottom = 18.dp)) {
            Icon(Icons.Filled.GraphicEq, null, tint = Accent, modifier = Modifier.size(24.dp))
            Spacer(Modifier.width(8.dp))
            Text("Dielify", style = MaterialTheme.typography.titleLarge)
        }
        MenuItem("Home", Icons.Filled.Home, root == TvPage.Home, Modifier.focusRequester(first)) { nav.place(TvPage.Home) }
        MenuItem("Library", Icons.Filled.LibraryMusic, root == TvPage.Library) { nav.place(TvPage.Library) }
        MenuItem("Search", Icons.Filled.Search, root == TvPage.Search) { nav.place(TvPage.Search) }
        if (playing) MenuItem("Now playing", Icons.Filled.GraphicEq, false) { nav.open(TvPage.NowPlaying) }
        Spacer(Modifier.weight(1f))
        MenuItem("Settings", Icons.Filled.Settings, root == TvPage.Settings) { nav.place(TvPage.Settings) }
    }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
}

@Composable
private fun MenuItem(label: String, icon: ImageVector, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Focusable(onClick, modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), grow = 1.03f) { focused ->
        Row(Modifier.fillMaxWidth().background(when {
            focused -> Color.White
            selected -> Color.White.copy(alpha = 0.10f)
            else -> Color.Transparent
        }).padding(horizontal = 12.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
            val fg = if (focused) Color.Black else if (selected) Color.White else Color.White.copy(alpha = 0.7f)
            Icon(icon, null, tint = fg, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(12.dp))
            Text(label, color = fg, style = MaterialTheme.typography.titleSmall)
        }
    }
}

@Composable
private fun TvPageContent(vm: AppViewModel, nav: TvNav) {
    when (val p = nav.top) {
        TvPage.Home -> TvHome(vm, nav)
        TvPage.Library -> TvLibrary(vm, nav)
        TvPage.Search -> TvSearch(vm, nav)
        TvPage.Settings -> TvSettings(vm)
        TvPage.NowPlaying -> {}
        is TvPage.Album -> TvAlbum(vm, nav, p)
        is TvPage.Artist -> TvArtist(vm, nav, p)
        is TvPage.Playlist -> TvPlaylist(vm, nav, p)
        is TvPage.YtAlbum -> TvYtCollection(vm, nav, p.name) { vm.server.ytAlbum(p.id) }
        is TvPage.YtPlaylist -> TvYtCollection(vm, nav, p.name) { vm.server.ytPlaylist(p.id) }
    }
}

