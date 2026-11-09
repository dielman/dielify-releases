package com.dielify.app.tv

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.dielify.app.ui.Accent
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalFocusManager

// 0.9.10: the TV's building blocks. Everything is reached with the remote's arrows: the
// focused thing grows a little and gets a white outline, so it's clear from the sofa.

/** TV-safe margins (TVs crop the edges). */
val TvPadH = 40.dp
val TvPadV = 24.dp
// A 1080p TV is 960 x 540 dp: everything below is sized for that.

/** Anything that can be selected with the remote. [content] gets whether it's focused. */
@Composable
fun Focusable(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(12.dp),
    grow: Float = 1.06f,
    content: @Composable (focused: Boolean) -> Unit,
) {
    val source = remember { MutableInteractionSource() }
    val focused by source.collectIsFocusedAsState()
    val scale by animateFloatAsState(if (focused) grow else 1f, label = "focus")
    Box(
        modifier
            .scale(scale)
            .then(if (focused) Modifier.shadow(18.dp, shape) else Modifier)
            .clip(shape)
            .border(if (focused) BorderStroke(3.dp, Color.White) else BorderStroke(0.dp, Color.Transparent), shape)
            .clickable(interactionSource = source, indication = null, onClick = onClick),
    ) { content(focused) }
}

/** A button: icon and/or label, filled when focused. */
@Composable
fun TvButton(label: String?, icon: ImageVector? = null, modifier: Modifier = Modifier, primary: Boolean = false, onClick: () -> Unit) {
    Focusable(onClick, modifier, shape = RoundedCornerShape(50), grow = 1.08f) { focused ->
        Row(
            Modifier
                .background(when {
                    focused -> Color.White
                    primary -> Accent
                    else -> Color.White.copy(alpha = 0.12f)
                })
                .padding(horizontal = if (label == null) 12.dp else 20.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            val fg = if (focused) Color.Black else Color.White
            icon?.let { Icon(it, label, tint = fg, modifier = Modifier.size(22.dp)) }
            label?.let { Text(it, color = fg, style = MaterialTheme.typography.labelLarge, maxLines = 1) }
        }
    }
}

/** A round icon button (player controls). */
@Composable
fun TvIconButton(icon: ImageVector, label: String, size: Dp = 64.dp, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Focusable(onClick, modifier, shape = CircleShape, grow = 1.12f) { focused ->
        Box(Modifier.size(size).background(if (focused) Color.White else Color.White.copy(alpha = 0.12f)), Alignment.Center) {
            Icon(icon, label, tint = if (focused) Color.Black else Color.White, modifier = Modifier.size(size * 0.5f))
        }
    }
}

/** A cover with a title and a line under it. */
@Composable
fun TvCard(
    title: String,
    subtitle: String?,
    width: Dp = 132.dp,
    round: Boolean = false,
    onClick: () -> Unit,
    art: @Composable () -> Unit,
) {
    Column(Modifier.width(width)) {
        Focusable(onClick, Modifier.size(width), shape = if (round) CircleShape else RoundedCornerShape(12.dp)) { art() }
        Spacer(Modifier.height(8.dp))
        Text(title, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
        subtitle?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** A titled row of cards that scrolls sideways as the focus moves. */
@Composable
fun <T> TvShelf(title: String, items: List<T>, key: (T) -> Any, card: @Composable (T) -> Unit) {
    if (items.isEmpty()) return
    Column(Modifier.fillMaxWidth().padding(bottom = 18.dp)) {
        Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = TvPadH, bottom = 6.dp))
        LazyRow(
            contentPadding = PaddingValues(horizontal = TvPadH, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(18.dp),
        ) { items(items, key = key) { card(it) } }
    }
}

/** A song row in a list: number, title, artist, length. */
@Composable
fun TvSongRow(n: Int?, title: String, sub: String, length: String, onClick: () -> Unit) {
    Focusable(onClick, Modifier.fillMaxWidth(), shape = RoundedCornerShape(10.dp), grow = 1.02f) { focused ->
        Row(
            Modifier.fillMaxWidth().background(if (focused) Color.White.copy(alpha = 0.14f) else Color.Transparent)
                .padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (n != null) Text("$n", Modifier.width(34.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (sub.isNotEmpty()) Text(sub, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Text(length, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** A row of buttons under a page header. */
@Composable
fun TvActions(content: @Composable RowScope.() -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically, content = content)
}

/** Centered message (loading, nothing here, errors). */
@Composable
fun TvMessage(text: String) {
    Box(Modifier.fillMaxSize().padding(TvPadH), Alignment.Center) {
        Text(text, style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Text boxes keep the arrow keys for the cursor; on a TV, Up and Down must leave them. */
@Composable
fun Modifier.leaveWithArrows(): Modifier {
    val fm = LocalFocusManager.current
    return onPreviewKeyEvent {
        if (it.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
        when (it.key) {
            Key.DirectionDown -> fm.moveFocus(FocusDirection.Down)
            Key.DirectionUp -> fm.moveFocus(FocusDirection.Up)
            else -> false
        }
    }
}
