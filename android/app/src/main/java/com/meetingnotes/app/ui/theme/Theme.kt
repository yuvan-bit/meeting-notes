package com.meetingnotes.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val LightColors = lightColorScheme(
    primary = Color(0xFF3B5BDB),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDDE3FF),
    onPrimaryContainer = Color(0xFF00174B),
    secondary = Color(0xFF5B5F71),
    background = Color(0xFFF7F8FA),
    surface = Color.White,
    surfaceVariant = Color(0xFFE9EBF2),
    outline = Color(0xFF9AA0AE),
    error = Color(0xFFBA1A1A),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFB4C4FF),
    onPrimary = Color(0xFF06256B),
    primaryContainer = Color(0xFF24408F),
    onPrimaryContainer = Color(0xFFDDE3FF),
    secondary = Color(0xFFC3C6D6),
    background = Color(0xFF101216),
    surface = Color(0xFF181A20),
    surfaceVariant = Color(0xFF23252D),
    outline = Color(0xFF8D919E),
    error = Color(0xFFFFB4AB),
)

@Composable
fun MeetingTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = Typography(),
        content = content,
    )
}
