package com.meetingnotes.app.util

import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

fun formatDuration(ms: Long): String {
    val totalSeconds = (ms / 1000).coerceAtLeast(0)
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) {
        String.format(Locale.US, "%d:%02d:%02d", hours, minutes, seconds)
    } else {
        String.format(Locale.US, "%02d:%02d", minutes, seconds)
    }
}

fun formatSeconds(seconds: Double?): String {
    if (seconds == null) return ""
    return formatDuration((seconds * 1000).toLong())
}

fun formatIsoDate(iso: String): String {
    if (iso.isBlank()) return ""
    return runCatching {
        val parsed = OffsetDateTime.parse(iso)
            .atZoneSameInstant(ZoneId.systemDefault())
        parsed.format(DateTimeFormatter.ofPattern("MM-dd HH:mm", Locale.CHINA))
    }.getOrElse { iso.take(16).replace('T', ' ') }
}

fun formatBytes(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val units = arrayOf("KB", "MB", "GB")
    var value = bytes.toDouble() / 1024
    var index = 0
    while (value >= 1024 && index < units.lastIndex) {
        value /= 1024
        index++
    }
    return String.format(Locale.US, "%.1f %s", value, units[index])
}

fun typeLabel(contentType: String): String = when (contentType) {
    "course" -> "课程"
    "meeting" -> "会议"
    else -> "自动"
}
