package com.meetingnotes.app.ui

import android.content.Context
import android.content.Intent
import android.widget.TextView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.FileProvider
import com.meetingnotes.app.MeetingApp
import com.meetingnotes.app.data.NoteDetail
import com.meetingnotes.app.data.NoteFile
import com.meetingnotes.app.util.formatBytes
import com.meetingnotes.app.util.formatIsoDate
import com.meetingnotes.app.util.formatSeconds
import io.noties.markwon.Markwon
import io.noties.markwon.ext.tables.TablePlugin
import kotlinx.coroutines.launch
import java.io.File
import android.os.Environment

@Composable
fun NoteDetailScreen(jobId: String, onBack: () -> Unit) {
    val context = LocalContext.current
    val container = (context.applicationContext as MeetingApp).container
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }

    val cached = remember(jobId) { container.noteCache.loadDetail(jobId) }
    var detail by remember(jobId) { mutableStateOf(cached) }
    var loading by remember(jobId) { mutableStateOf(cached == null) }
    var error by remember(jobId) { mutableStateOf<String?>(null) }
    var stale by remember(jobId) { mutableStateOf(false) }
    var reloadKey by remember { mutableStateOf(0) }
    var downloading by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(jobId, reloadKey) {
        if (detail == null) loading = true
        error = null
        stale = false
        try {
            val fresh = container.api.noteDetail(jobId)
            detail = fresh
            container.noteCache.saveDetail(fresh)
            stale = false
        } catch (e: Exception) {
            if (detail == null) {
                error = e.message ?: "加载笔记失败"
            } else {
                stale = true
            }
        } finally {
            loading = false
        }
    }

    fun download(file: NoteFile) {
        if (downloading != null) return
        downloading = file.name
        scope.launch {
            try {
                val bytes = container.api.downloadNoteFile(jobId, file.name)
                val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
                    ?: File(context.filesDir, "downloads")
                dir.mkdirs()
                val target = File(dir, file.name)
                target.writeBytes(bytes)
                val result = snackbarHostState.showSnackbar(
                    message = "已保存 ${file.name}（${formatBytes(bytes.size.toLong())}）",
                    actionLabel = "分享",
                    withDismissAction = true,
                )
                if (result == SnackbarResult.ActionPerformed) {
                    shareFile(context, target)
                }
            } catch (e: Exception) {
                snackbarHostState.showSnackbar(e.message ?: "下载失败")
            } finally {
                downloading = null
            }
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
                Text(
                    "笔记详情",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                )
            }

            when {
                loading -> Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }

                error != null -> Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(
                        error.orEmpty(),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                    )
                    Spacer(Modifier.size(8.dp))
                    TextButton(onClick = { reloadKey += 1 }) { Text("重试") }
                }

                detail != null -> {
                    val note = detail!!
                    val markwon = remember {
                        Markwon.builder(context)
                            .usePlugin(TablePlugin.create(context))
                            .build()
                    }
                    val textColor = MaterialTheme.colorScheme.onSurface.toArgb()
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 32.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        item {
                            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    TypeBadge(note.contentType)
                                    Spacer(Modifier.size(8.dp))
                                    Text(
                                        formatIsoDate(note.createdAt),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    val duration = formatSeconds(note.durationS)
                                    if (duration.isNotBlank()) {
                                        Text(
                                            " · $duration",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                                Text(
                                    note.topic.ifBlank { note.title.ifBlank { "未命名" } },
                                    style = MaterialTheme.typography.headlineSmall,
                                    fontWeight = FontWeight.Bold,
                                )
                                if (note.summary.isNotBlank()) {
                                    Text(
                                        note.summary,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }

                        if (stale) {
                            item {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        "网络较慢，当前显示上次缓存",
                                        modifier = Modifier.weight(1f),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    TextButton(onClick = { reloadKey += 1 }) { Text("刷新") }
                                }
                            }
                        }

                        item {
                            Card(
                                colors = CardDefaults.cardColors(
                                    containerColor = MaterialTheme.colorScheme.surface
                                ),
                                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
                            ) {
                                if (note.minutesMarkdown.isBlank()) {
                                    Text(
                                        "这条笔记暂无正文",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.padding(16.dp),
                                    )
                                } else {
                                    AndroidView(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(16.dp),
                                        factory = { ctx ->
                                            TextView(ctx).apply {
                                                setTextIsSelectable(true)
                                                textSize = 15f
                                                setLineSpacing(4f, 1f)
                                                setTextColor(textColor)
                                                markwon.setMarkdown(this, note.minutesMarkdown)
                                            }
                                        },
                                        update = { view ->
                                            view.setTextColor(textColor)
                                            markwon.setMarkdown(view, note.minutesMarkdown)
                                        },
                                    )
                                }
                            }
                        }

                        if (note.files.isNotEmpty()) {
                            item {
                                Text(
                                    "附件",
                                    style = MaterialTheme.typography.titleMedium,
                                    modifier = Modifier.padding(top = 4.dp),
                                )
                            }
                            item {
                                Card(
                                    colors = CardDefaults.cardColors(
                                        containerColor = MaterialTheme.colorScheme.surface
                                    ),
                                    elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
                                ) {
                                    Column {
                                        note.files.forEachIndexed { index, file ->
                                            FileRow(
                                                file = file,
                                                downloading = downloading == file.name,
                                                onDownload = { download(file) },
                                            )
                                            if (index < note.files.lastIndex) {
                                                HorizontalDivider()
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        item {
                            Text(
                                "音频由服务器保留最近 30 天或 5GB；纪要、转写和元数据永久保存。",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(top = 8.dp),
                            )
                        }
                    }
                }
            }
        }

        SnackbarHost(
            hostState = snackbarHostState,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(16.dp),
        )
    }
}

@Composable
private fun FileRow(file: NoteFile, downloading: Boolean, onDownload: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 8.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(friendlyFileName(file.name), style = MaterialTheme.typography.bodyMedium)
            Text(
                "${file.name} · ${formatBytes(file.sizeBytes)}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (downloading) {
            CircularProgressIndicator(
                modifier = Modifier
                    .padding(12.dp)
                    .size(18.dp),
                strokeWidth = 2.dp,
            )
        } else {
            IconButton(onClick = onDownload) {
                Icon(Icons.Filled.Download, contentDescription = "下载")
            }
        }
    }
}

private fun friendlyFileName(name: String): String = when (name) {
    "minutes.md" -> "纪要全文"
    "transcript.md" -> "完整转写（Markdown）"
    "transcript.txt" -> "完整转写（纯文本）"
    "transcript.srt" -> "字幕（SRT）"
    "transcript.json" -> "转写数据（JSON）"
    "meta.json" -> "元数据"
    else -> name
}

private fun mimeType(name: String): String = when {
    name.endsWith(".md") -> "text/markdown"
    name.endsWith(".json") -> "application/json"
    name.endsWith(".srt") || name.endsWith(".txt") -> "text/plain"
    else -> "application/octet-stream"
}

private fun shareFile(context: Context, file: File) {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = mimeType(file.name)
        putExtra(Intent.EXTRA_STREAM, uri)
        putExtra(Intent.EXTRA_SUBJECT, file.name)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    runCatching {
        context.startActivity(
            Intent.createChooser(intent, "分享 ${file.name}")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }
}
