package com.dielify.app.tv

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
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
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        val line = when (s) {
            UpdateState.NotSetUp -> "Test build: updates come over USB from the PC."
            UpdateState.Checking -> "Checking for updates…"
            UpdateState.UpToDate -> "Up to date"
            is UpdateState.Available -> "Dielify ${s.release.version} is available" +
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
            TvButton(if (s is UpdateState.Available) "Update" else "Check for updates", Icons.Filled.SystemUpdate,
                Modifier.focusRequester(button), primary = s is UpdateState.Available) {
                hadFocus[0] = true
                when (s) {
                    is UpdateState.Available ->
                        if (!vm.updater.canInstall()) {
                            vm.messages.tryEmit("Allow Dielify to install updates, then come back and press Update again")
                            context.startActivity(vm.updater.openInstallPermission())
                        } else scope.launch { vm.updater.download(s.release)?.let { context.startActivity(it) } }
                    UpdateState.Checking, is UpdateState.Downloading -> {}
                    else -> scope.launch { vm.updater.check(force = true) }
                }
            }
        }
    }
    // keep the remote's selection on the button when its words change
    LaunchedEffect(s) { if (hadFocus[0]) { delay(50); runCatching { button.requestFocus() } } }
}
