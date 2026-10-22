package com.meetingnotes.app.ui

import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meetingnotes.app.MeetingApp
import com.meetingnotes.app.data.NoteItem
import com.meetingnotes.app.util.formatIsoDate
import com.meetingnotes.app.util.formatSeconds
import com.meetingnotes.app.util.typeLabel
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NotesScreen(onOpenNote: (String) -> Unit) {
    val context = LocalContext.current
    val container = (context.applicationContext as MeetingApp).container

    var query by rememberSaveable { mutableStateOf("") }
    var filter by rememberSaveable { mutableStateOf("") }
    var notes by remember { mutableStateOf<List<NoteItem>>(emptyList()) }
    var total by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }

    LaunchedEffect(query, filter, reloadKey) {
        if (query.isNotBlank()) delay(350)
        loading = true
        error = null
        try {
            val page = container.api.listNotes(
                query = query.trim(),
                contentType = filter,
                limit = 100,
            )
            notes = page.items
            total = page.total
        } catch (e: Exception) {
            error = e.message ?: "加载笔记失败"
        } finally {
            loading = false
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 20.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Column {
                Text(
                    "笔记",
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "电脑转写完成后自动同步到这里",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        item {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it.take(60) },
                placeholder = { Text("搜索主题、摘要或标题") },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                trailingIcon = {
                    if (query.isNotEmpty()) {
                        IconButton(onClick = { query = "" }) {
                            Icon(Icons.Filled.Close, contentDescription = "清空")
                        }
                    }
                },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(
                    "" to "全部",
                    "meeting" to "会议",
                    "course" to "课程",
                ).forEach { (value, label) ->
                    FilterChip(
                        selected = filter == value,
                        onClick = { filter = value },
                        label = { Text(label) },
                    )
                }
            }
        }

        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    if (total > 0) "共 $total 条" else "",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (loading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                        )
                        Spacer(Modifier.size(6.dp))
                    }
                    TextButton(
                        onClick = { reloadKey += 1 },
                        enabled = !loading,
                    ) {
                        Icon(
                            Icons.Filled.Refresh,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.size(4.dp))
                        Text("刷新")
                    }
                }
            }
        }

        val failure = error
        if (failure != null && notes.isEmpty()) {
            item {
                ErrorCard(message = failure, onRetry = { reloadKey += 1 })
            }
        }

        if (!loading && failure == null && notes.isEmpty()) {
            item {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 48.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        if (query.isNotBlank() || filter.isNotEmpty()) "没有符合条件的笔记" else "还没有笔记",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        if (query.isNotBlank() || filter.isNotEmpty()) "换个关键词或筛选条件试试" else "手机上传录音后，等电脑空闲时会自动生成",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        items(notes, key = { it.jobId }) { note ->
            NoteCard(note = note, onClick = { onOpenNote(note.jobId) })
        }
    }
}

@Composable
private fun NoteCard(note: NoteItem, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
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
                Spacer(Modifier.weight(1f))
                if (note.pinned) {
                    Icon(
                        Icons.Filled.PushPin,
                        contentDescription = "已固定",
                        modifier = Modifier.size(14.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Text(
                note.topic.ifBlank { note.title.ifBlank { "未命名" } },
                style = MaterialTheme.typography.titleMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            if (note.summary.isNotBlank()) {
                Text(
                    note.summary,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    buildString {
                        append("${note.files.size} 个文件")
                        if (note.audioAvailable) append(" · 音频可下载")
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "查看",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
fun TypeBadge(contentType: String) {
    val (background, content) = when (contentType) {
        "meeting" -> MaterialTheme.colorScheme.primaryContainer to
            MaterialTheme.colorScheme.onPrimaryContainer
        "course" -> MaterialTheme.colorScheme.tertiaryContainer to
            MaterialTheme.colorScheme.onTertiaryContainer
        else -> MaterialTheme.colorScheme.surfaceVariant to
            MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(shape = RoundedCornerShape(50), color = background) {
        Text(
            typeLabel(contentType),
            style = MaterialTheme.typography.labelSmall,
            color = content,
            modifier = Modifier.padding(horizontal = 9.dp, vertical = 3.dp),
        )
    }
}

@Composable
private fun ErrorCard(message: String, onRetry: () -> Unit) {
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
                message,
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
            TextButton(onClick = onRetry) { Text("重试") }
        }
    }
}
