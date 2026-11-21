package com.dielify.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.dielify.app.net.Notice
import kotlinx.coroutines.launch

/** The bell in the top bar: a dot while something is unread. */
@Composable
fun NoticeBell(vm: AppViewModel) {
    val unread by vm.unreadNotices.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { vm.refreshNotices() }
    IconButton(onClick = { vm.open(Screen.NotificationsPage) }) {
        if (unread > 0) BadgedBox(badge = { Badge { Text(unread.toString()) } }) { Icon(Icons.Filled.Notifications, "Notifications") }
        else Icon(Icons.Filled.Notifications, "Notifications")
    }
}

/** Things the household should know (Josh, 21 Nov 2026), e.g. YouTube Music Premium lapsed. */
@Composable
fun NotificationsScreen(vm: AppViewModel) {
    val scope = rememberCoroutineScope()
    var version by remember { mutableIntStateOf(0) }
    Page(vm, "Notifications") { pad ->
        Loaded(vm, "notices-$version", {
            val n = vm.server.notifications()
            if (n.unread > 0) runCatching { vm.server.readNotifications() }
            vm.unreadNotices.value = 0
            n
        }) { n ->
            if (n.notifications.isEmpty()) {
                Text("Nothing to tell you right now.", Modifier.padding(pad).padding(20.dp),
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else LazyColumn(Modifier.padding(pad), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(n.notifications, key = { it.key }) { item ->
                    NoticeCard(item) {
                        scope.launch {
                            runCatching { vm.server.dismissNotification(item.key) }
                                .onFailure { vm.messages.tryEmit(it.message ?: "Couldn't dismiss it") }
                            version++
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun NoticeCard(n: Notice, onDismiss: () -> Unit) {
    val warning = n.level == "warning"
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (warning) {
                    Icon(Icons.Filled.Warning, null, tint = androidx.compose.ui.graphics.Color(0xFFE8A33D))
                    Spacer(Modifier.width(8.dp))
                }
                Text(n.title, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)
            }
            Text(n.body, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface)
            Text(android.text.format.DateUtils.getRelativeTimeSpanString((n.createdAt * 1000).toLong()).toString(),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (n.canDismiss) TextButton(onClick = onDismiss) { Text("Dismiss") }
            else Text("This stays here while it's true.", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
