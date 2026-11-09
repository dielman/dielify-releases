package com.dielify.app.ui

import androidx.compose.foundation.layout.offset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.dielify.app.net.ArtColors

// 0.9.9: the shared look (same as the PC app): cover-tinted page headers, the big round Play
// button, the moving bars on the song that's playing, and Settings sections.

fun hexColor(hex: String?, fallback: Color = Color(0xFF1B1E24)): Color = runCatching {
    Color(android.graphics.Color.parseColor(hex))
}.getOrDefault(fallback)

/** A page's background: the cover's dark colour at the top, fading into the app's black. */
fun tintBrush(colors: ArtColors?, height: Float = 1400f): Brush {
    val tint = hexColor(colors?.bg)
    return Brush.verticalGradient(0f to tint, 0.55f to tint.copy(alpha = 0.55f).compositeOver(Bg), 1f to Bg, endY = height)
}

private fun Color.compositeOver(under: Color): Color {
    val a = alpha
    return Color(red * a + under.red * (1 - a), green * a + under.green * (1 - a), blue * a + under.blue * (1 - a), 1f)
}

/** Big cover, label, title, subtitle and actions, on the cover's colour. */
@Composable
fun PageHeader(
    vm: AppViewModel,
    label: String,
    title: String,
    subtitle: String?,
    colors: ArtColors?,
    cover: String? = null,
    thumbnail: String? = null,
    round: Boolean = false,
    extra: @Composable ColumnScope.() -> Unit = {},
    actions: @Composable RowScope.() -> Unit = {},
) {
    Column(
        Modifier.fillMaxWidth().background(tintBrush(colors, 900f)).padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        val shape = if (round) CircleShape else RoundedCornerShape(12.dp)
        Box(Modifier.size(232.dp).shadow(24.dp, shape).clip(shape)) {
            if (cover != null) Cover(vm, cover, 232.dp, pixels = 700) else Thumb(thumbnail, 232.dp, round = round)
        }
        Spacer(Modifier.height(18.dp))
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = Color.White.copy(alpha = 0.75f))
        Text(title, style = MaterialTheme.typography.headlineLarge, textAlign = TextAlign.Center, maxLines = 3,
            overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 4.dp))
        subtitle?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium, color = Color.White.copy(alpha = 0.75f),
                textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp))
        }
        extra()
        Spacer(Modifier.height(16.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp), content = actions)
    }
}

/** The round accent Play button of page headers. */
@Composable
fun BigPlay(enabled: Boolean = true, icon: ImageVector = Icons.Filled.PlayArrow, label: String = "Play", onClick: () -> Unit) {
    FilledIconButton(
        onClick = onClick, enabled = enabled, modifier = Modifier.size(60.dp),
        colors = IconButtonDefaults.filledIconButtonColors(containerColor = Accent, contentColor = Color.White),
    ) { Icon(icon, label, Modifier.size(32.dp)) }
}

/** Three little bars that move while the song plays (still while it's paused). */
@Composable
fun PlayingBars(playing: Boolean, modifier: Modifier = Modifier, color: Color = Accent, size: Dp = 16.dp) {
    val t = rememberInfiniteTransition(label = "bars")
    val a by t.animateFloat(0.3f, 1f, infiniteRepeatable(tween(420), RepeatMode.Reverse), label = "a")
    val b by t.animateFloat(0.9f, 0.25f, infiniteRepeatable(tween(520), RepeatMode.Reverse), label = "b")
    val c by t.animateFloat(0.5f, 0.95f, infiniteRepeatable(tween(360), RepeatMode.Reverse), label = "c")
    Row(modifier.size(size), horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.Bottom) {
        listOf(if (playing) a else 0.4f, if (playing) b else 0.8f, if (playing) c else 0.6f).forEach { h ->
            Box(Modifier.weight(1f).fillMaxHeight(h).clip(RoundedCornerShape(1.dp)).background(color))
        }
    }
}

/** Settings: a heading and its items on one card. */
@Composable
fun SettingsSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column {
        Text(title.uppercase(), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 4.dp, bottom = 8.dp))
        Surface(color = MaterialTheme.colorScheme.surfaceContainer, shape = RoundedCornerShape(16.dp)) {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp), content = content)
        }
        Spacer(Modifier.width(1.dp))
    }
}


/** A thin seek bar (white on the song's colours): tap or drag anywhere on it. */
@Composable
fun ThinSeek(value: Float, enabled: Boolean, onChange: (Float) -> Unit, onDone: () -> Unit) {
    androidx.compose.foundation.layout.BoxWithConstraints(
        Modifier.fillMaxWidth().height(28.dp)
            .then(if (!enabled) Modifier else Modifier
                .pointerInput(Unit) {
                    detectTapGestures { o -> onChange((o.x / size.width).coerceIn(0f, 1f)); onDone() }
                }
                .pointerInput(Unit) {
                    detectHorizontalDragGestures(onDragEnd = { onDone() }) { ch, _ ->
                        onChange((ch.position.x / size.width).coerceIn(0f, 1f))
                    }
                }),
        contentAlignment = Alignment.CenterStart,
    ) {
        val v = value.coerceIn(0f, 1f)
        Box(Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)).background(Color.White.copy(alpha = 0.22f)))
        Box(Modifier.fillMaxWidth(v).height(4.dp).clip(RoundedCornerShape(2.dp)).background(Color.White))
        Box(Modifier.offset(x = maxWidth * v - 6.dp).size(12.dp).clip(CircleShape).background(Color.White))
    }
}
