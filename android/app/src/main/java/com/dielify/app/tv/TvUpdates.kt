package com.dielify.app.tv

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.ui.AppViewModel
import com.dielify.app.update.UpdateState
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Updates on the TV: one button that stays selected while it checks, finds and downloads
 * (the phone's version lost the remote's selection when its button changed). */
@Composable
fun TvUpdates(vm: AppViewModel) {
    val state by vm.updater.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val button = remember { FocusRequester() }
    val hadFocus = remember { booleanArrayOf(false) }
    val s = state
    // whether Dielify may install apps can change in TV Settings while we're away: look again on return
    var resumed by remember { mutableIntStateOf(0) }
    LifecycleResumeEffect(Unit) { resumed++; onPauseOrDispose {} }
    val allowed = remember(s, resumed) { vm.updater.canInstall() }
    val blocked = remember(s, resumed) { vm.updater.installBlocked() }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        val line = when (s) {
            UpdateState.NotSetUp -> "Test build: updates come over USB from the PC."
            UpdateState.Checking -> "Checking for updates…"
            UpdateState.UpToDate -> "Up to date"
            is UpdateState.Available -> if (blocked)
                "Dielify ${s.release.version} is ready, but this TV doesn't let apps install updates (switched off " +
                    "for the whole TV, e.g. by a kids profile). Your PC installs it when the TV is on Wi-Fi " +
                    "(Settings > People & phones > Update TVs now); on a cable, install it from a USB stick."
            else if (!allowed)
                "Dielify ${s.release.version} is ready from your PC. First let Dielify install updates: press " +
                    "Allow updates, switch Dielify on, then press Back."
            else "Dielify ${s.release.version} is available" +
                (if (s.release.fromPc) " from your PC" else "") + " (${s.release.size / 1_000_000} MB)"
            is UpdateState.Downloading -> "Downloading ${s.release.version}… ${(s.fraction * 100).toInt()}%"
            is UpdateState.Failed -> s.message
            UpdateState.Idle -> ""
        }
        if (line.isNotEmpty()) Text(line, style = MaterialTheme.typography.bodyMedium,
            color = when (s) {
                is UpdateState.Failed -> MaterialTheme.colorScheme.error
                is UpdateState.Available -> MaterialTheme.colorScheme.primary
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            })
        if (s != UpdateState.NotSetUp) {
            // Fresh TVs haven't let Dielify install apps yet: the button opens that switch first. Some TVs block it
            // altogether (Josh's TCL: a kids profile); then the PC installs updates (tvupdate.py) and it only checks.
            val available = s is UpdateState.Available && !blocked
            val label = when { !available -> "Check for updates"; allowed -> "Update"; else -> "Allow updates" }
            TvButton(label, Icons.Filled.SystemUpdate, Modifier.focusRequester(button), primary = available) {
                hadFocus[0] = true
                when (s) {
                    is UpdateState.Available ->
                        if (blocked) scope.launch { vm.updater.check(force = true) }
                        else if (vm.updater.canInstall())
                            scope.launch { vm.updater.download(s.release)?.let { context.startActivity(it) } }
                        else runCatching { context.startActivity(vm.updater.openInstallPermission()) }.onFailure {
                            Toast.makeText(context, "Open the TV's Settings > Apps > Security & restrictions > " +
                                "Unknown sources and switch Dielify on", Toast.LENGTH_LONG).show()
                        }
                    UpdateState.Checking, is UpdateState.Downloading -> {}
                    else -> scope.launch { vm.updater.check(force = true) }
                }
            }
        }
    }
    // keep the remote's selection on the button when its words change
    LaunchedEffect(s) { if (hadFocus[0]) { delay(50); runCatching { button.requestFocus() } } }
}
