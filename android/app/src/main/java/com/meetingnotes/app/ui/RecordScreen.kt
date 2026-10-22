package com.meetingnotes.app.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.meetingnotes.app.MeetingApp
import com.meetingnotes.app.data.LocalRecording
import com.meetingnotes.app.recording.RecordingService
import com.meetingnotes.app.upload.UploadScheduler
import com.meetingnotes.app.util.formatBytes
import com.meetingnotes.app.util.formatDuration
import kotlinx.coroutines.delay
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecordScreen() {
    val context = LocalContext.current
    val container = (context.applicationContext as MeetingApp).container
    val recordingState by container.recordingController.state.collectAsState()
    val recordings by container.recordings.items.collectAsState()

    var title by rememberSaveable { mutableStateOf("") }
    var contentType by rememberSaveable { mutableStateOf("auto") }
    var notice by remember { mutableStateOf<String?>(null) }
    var elapsedMs by remember { mutableLongStateOf(0L) }

    LaunchedEffect(recordingState.error) {
        val message = recordingState.error
        if (!message.isNullOrBlank()) {
            notice = message
            container.recordingController.clearError()
        }
    }
    LaunchedEffect(recordingState.active, recordingState.startedAtMs) {
        if (!recordingState.active) {
            elapsedMs = 0L
            return@LaunchedEffect
        }
        while (true) {
            elapsedMs = (System.currentTimeMillis() - recordingState.startedAtMs).coerceAtLeast(0)
            delay(500)
        }
    }

    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    val beginRecording: () -> Unit = {
        val finalTitle = title.trim().ifBlank {
            "未命名录音 " + SimpleDateFormat("MM-dd HH:mm", Locale.CHINA).format(Date())
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        RecordingService.start(context, finalTitle, contentType)
    }

    val micPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            beginRecording()
        } else {
            notice = "需要麦克风权限才能录音"
        }
    }

    val onMainButton: () -> Unit = {
        if (recordingState.active) {
            RecordingService.stop(context)
        } else {
            val granted = ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.RECORD_AUDIO,
            ) == PackageManager.PERMISSION_GRANTED
            if (granted) beginRecording() else micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    val host = container.settings.serverUrl
        .removePrefix("https://")
        .removePrefix("http://")
        .substringBefore('/')

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 20.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text(
                        "录音",
                        style = MaterialTheme.typography.headlineMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "声音留在手机，转写交给电脑",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Surface(
                    shape = RoundedCornerShape(50),
                    color = MaterialTheme.colorScheme.primaryContainer,
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            modifier = Modifier
                                .size(7.dp)
                                .background(Color(0xFF2E9E5B), CircleShape)
                        )
                        Spacer(Modifier.size(6.dp))
                        Text(
                            host.ifBlank { "已连接" },
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                    }
                }
            }
        }

        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    OutlinedTextField(
                        value = title,
                        onValueChange = { title = it.take(80) },
                        label = { Text("本次主题（可留空）") },
                        placeholder = { Text("例如：产品评审 / 线性代数第 5 讲") },
                        singleLine = true,
                        enabled = !recordingState.active,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(
                            "auto" to "自动识别",
                            "meeting" to "会议",
                            "course" to "课程",
                        ).forEach { (value, label) ->
                            FilterChip(
                                selected = contentType == value,
                                onClick = { contentType = value },
                                enabled = !recordingState.active,
                                label = { Text(label) },
                            )
                        }
                    }

                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 10.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Box(
                                modifier = Modifier
                                    .size(124.dp)
                                    .background(
                                        if (recordingState.active) MaterialTheme.colorScheme.error
                                        else MaterialTheme.colorScheme.primary,
                                        CircleShape,
                                    )
                                    .clickable { onMainButton() },
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    imageVector = if (recordingState.active) Icons.Filled.Stop else Icons.Filled.Mic,
                                    contentDescription = if (recordingState.active) "停止录音" else "开始录音",
                                    tint = Color.White,
                                    modifier = Modifier.size(52.dp),
                                )
                            }
                            Spacer(Modifier.height(12.dp))
                            if (recordingState.active) {
                                Text(
                                    formatDuration(elapsedMs),
                                    style = MaterialTheme.typography.headlineSmall,
                                    fontWeight = FontWeight.Bold,
                                )
                                Text(
                                    "正在录音 · 已保存在本机",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                TextButton(onClick = { RecordingService.cancel(context) }) {
                                    Text("放弃本次录音", color = MaterialTheme.colorScheme.error)
                                }
                            } else {
                                Text(
                                    "轻触开始录音",
                                    style = MaterialTheme.typography.titleMedium,
                                )
                                Text(
                                    "停止后自动加入上传队列",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
        }

        if (notice != null) {
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer
                    )
                ) {
                    Row(
                        modifier = Modifier.padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            notice.orEmpty(),
                            modifier = Modifier.weight(1f),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onErrorContainer,
                        )
                        TextButton(onClick = { notice = null }) { Text("知道了") }
                    }
                }
            }
        }

        item {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("本机录音", style = MaterialTheme.typography.titleMedium)
                Text(
                    "${recordings.count { it.status != LocalRecording.STATUS_UPLOADED }} 条待同步 / 共 ${recordings.size} 条",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        val sorted = recordings.sortedByDescending { it.createdAtMs }
        if (sorted.isEmpty()) {
            item {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 36.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(
                        "还没有录音",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "会议或上课前，点一下上方按钮",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        } else {
            items(sorted, key = { it.id }) { recording ->
                RecordingCard(
                    recording = recording,
                    onRetry = {
                        container.recordings.markRetry(recording.id, "")
                        UploadScheduler.enqueue(context, recording.id)
                    },
                )
            }
        }

        item {
            Text(
                "音频上传后由家中电脑在长时间空闲时自动拉取并转写；完成后可在“笔记”中查看。服务器仅保留最近 5GB 音频，笔记永久保存。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 12.dp),
            )
        }
    }
}

@Composable
private fun RecordingCard(recording: LocalRecording, onRetry: () -> Unit) {
    val date = remember(recording.createdAtMs) {
        SimpleDateFormat("MM-dd HH:mm", Locale.CHINA).format(Date(recording.createdAtMs))
    }
    val size = remember(recording.filePath) {
        runCatching { File(recording.filePath).length() }.getOrDefault(0L)
    }
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        recording.title,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        "$date · ${formatDuration(recording.durationMs)} · ${formatBytes(size)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                StatusBadge(recording.status)
            }
            if (!recording.error.isNullOrBlank()) {
                Text(
                    recording.error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            if (recording.status == LocalRecording.STATUS_FAILED ||
                (recording.status == LocalRecording.STATUS_RECORDED && !recording.error.isNullOrBlank())
            ) {
                TextButton(onClick = onRetry) { Text("重试上传") }
            }
        }
    }
}

@Composable
private fun StatusBadge(status: String) {
    val (label, background, content) = when (status) {
        LocalRecording.STATUS_UPLOADED -> Triple(
            "已上传",
            MaterialTheme.colorScheme.primaryContainer,
            MaterialTheme.colorScheme.onPrimaryContainer,
        )
        LocalRecording.STATUS_UPLOADING -> Triple(
            "上传中",
            MaterialTheme.colorScheme.secondaryContainer,
            MaterialTheme.colorScheme.onSecondaryContainer,
        )
        LocalRecording.STATUS_FAILED -> Triple(
            "上传失败",
            MaterialTheme.colorScheme.errorContainer,
            MaterialTheme.colorScheme.onErrorContainer,
        )
        else -> Triple("待上传", MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Surface(shape = RoundedCornerShape(50), color = background) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = content,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}
