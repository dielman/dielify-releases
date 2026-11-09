package com.dielify.app.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.dielify.app.R

// 0.9.9: the same look as the PC app (app.css): colours, Inter, type sizes.
val Accent = Color(0xFFFF5A5F)
val Bg = Color(0xFF0E0F12)

private val Colors = darkColorScheme(
    primary = Accent,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF3A1B1D),
    onPrimaryContainer = Color(0xFFFFD9DA),
    secondary = Color(0xFFFF7A7E),
    secondaryContainer = Color(0xFF272B31),
    onSecondaryContainer = Color(0xFFF2F3F5),
    background = Bg,
    surface = Bg,
    surfaceVariant = Color(0xFF1E2126),
    surfaceContainerLowest = Color(0xFF0A0B0D),
    surfaceContainerLow = Color(0xFF121418),
    surfaceContainer = Color(0xFF16181C),
    surfaceContainerHigh = Color(0xFF1E2126),
    surfaceContainerHighest = Color(0xFF272B31),
    onBackground = Color(0xFFF2F3F5),
    onSurface = Color(0xFFF2F3F5),
    onSurfaceVariant = Color(0xFF9AA1AB),
    outline = Color(0xFF3A3F47),
    outlineVariant = Color(0xFF2A2E35),
)

val Inter = FontFamily(
    Font(R.font.inter_400, FontWeight.Normal),
    Font(R.font.inter_500, FontWeight.Medium),
    Font(R.font.inter_600, FontWeight.SemiBold),
    Font(R.font.inter_700, FontWeight.Bold),
    Font(R.font.inter_800, FontWeight.ExtraBold),
)

private fun style(size: Int, weight: FontWeight, tracking: Double = 0.0, line: Int? = null) = TextStyle(
    fontFamily = Inter, fontWeight = weight, fontSize = size.sp, letterSpacing = tracking.em,
    lineHeight = (line ?: (size * 1.3).toInt()).sp,
)

private val Type = Typography(
    displayLarge = style(48, FontWeight.ExtraBold, -0.035),
    displayMedium = style(40, FontWeight.ExtraBold, -0.035),
    displaySmall = style(34, FontWeight.ExtraBold, -0.03),
    headlineLarge = style(30, FontWeight.ExtraBold, -0.03),
    headlineMedium = style(26, FontWeight.ExtraBold, -0.025),
    headlineSmall = style(22, FontWeight.Bold, -0.02),
    titleLarge = style(20, FontWeight.Bold, -0.015),
    titleMedium = style(16, FontWeight.Bold, -0.01),
    titleSmall = style(14, FontWeight.SemiBold),
    bodyLarge = style(16, FontWeight.Normal),
    bodyMedium = style(14, FontWeight.Normal),
    bodySmall = style(12, FontWeight.Normal),
    labelLarge = style(14, FontWeight.SemiBold),
    labelMedium = style(12, FontWeight.SemiBold),
    labelSmall = style(11, FontWeight.SemiBold, 0.02),
)

@Composable
fun DielifyTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Colors, typography = Type, content = content)
}
