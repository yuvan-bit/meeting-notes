package com.meetingnotes.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.meetingnotes.app.BuildConfig
import com.meetingnotes.app.MeetingApp
import com.meetingnotes.app.data.MeResponse
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(onUnpaired: () -> Unit) {
    val context = LocalContext.current
    val container = (context.applicationContext as MeetingApp).container
    val updateState by container.updates.state.collectAsState()
    val scope = rememberCoroutineScope()

    var installNotice by remember { mutableStateOf<String?>(null) }
    var me by remember { mutableStateOf<MeResponse?>(null) }
    var checking by remember { mutableStateOf(false) }
    var checkError by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }
    var confirmUnpair by remember { mutableStateOf(false) }

    LaunchedEffect(reloadKey) {
        checking = true
        checkError = null
        try {
            me = container.api.me()
        } catch (e: Exception) {
            me = null
            checkError = e.message ?: "无法连接服务器"
        } finally {
            checking = false
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 20.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Column {
                Text(
                    "设置",
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "连接、设备与数据说明",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("服务器连接", style = MaterialTheme.typography.titleMedium)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        when {
                            checking -> {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(16.dp),
                                    strokeWidth = 2.dp,
                                )
                                Spacer(Modifier.size(8.dp))
                                Text(
                                    "正在检查连接…",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }

                            checkError != null -> {
                                Icon(
                                    Icons.Filled.ErrorOutline,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.error,
                                    modifier = Modifier.size(18.dp),
                                )
                                Spacer(Modifier.size(8.dp))
                                Text(
                                    checkError.orEmpty(),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }

                            else -> {
                                Icon(
                                    Icons.Filled.CheckCircle,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(18.dp),
                                )
                                Spacer(Modifier.size(8.dp))
                                Text(
                                    "连接正常",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }
                    HorizontalDivider()
                    InfoRow("地址", container.settings.serverUrl)
                    InfoRow("设备", container.settings.deviceName.ifBlank { me?.name ?: "未命名" })
                    InfoRow("设备 ID", container.settings.deviceId)
                    InfoRow("角色", roleLabel(me?.role ?: "phone"))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = { reloadKey += 1 },
                            enabled = !checking,
                        ) { Text("测试连接") }
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
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("应用更新", style = MaterialTheme.typography.titleMedium)
                    InfoRow(
                        "当前版本",
                        "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                    )
                    val release = updateState.release
                    when {
                        updateState.downloading -> {
                            Text(
                                "正在下载 ${(updateState.progress * 100).toInt()}%",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            LinearProgressIndicator(
                                progress = { updateState.progress },
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }

                        updateState.apk != null -> {
                            Text(
                                "版本 ${release?.versionName.orEmpty()} 已下载，可以安装。",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Button(onClick = {
                                installNotice = container.updates.install()
                            }) {
                                Text("安装更新")
                            }
                        }

                        release != null -> {
                            Text(
                                "发现新版本 ${release.versionName} (${release.versionCode})",
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            if (release.changelog.isNotBlank()) {
                                Text(
                                    release.changelog,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            OutlinedButton(
                                enabled = !updateState.checking,
                                onClick = {
                                    installNotice = null
                                    scope.launch { container.updates.download() }
                                },
                            ) {
                                Text("下载更新")
                            }
                        }

                        else -> {
                            Text(
                                when {
                                    updateState.checking -> "正在检查更新…"
                                    updateState.checked -> "已是最新版本"
                                    else -> "启动时会自动检查更新"
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    updateState.error?.let {
                        Text(
                            it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    installNotice?.let {
                        Text(
                            it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            enabled = !updateState.checking && !updateState.downloading,
                            onClick = {
                                installNotice = null
                                scope.launch { container.updates.check() }
                            },
                        ) {
                            Text("检查更新")
                        }
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
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("工作方式", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "手机只负责录音和上传。家中电脑在长时间空闲时自动从服务器领取任务，用本地 FunASR 转写、Ollama 生成纪要，再把结果回传。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "服务器只保留最近 5GB 或 30 天内的音频；纪要、逐字稿和元数据永久保留。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "手机与电脑需要连接同一个 Tailscale 网络，手机填写的地址形如 https://主机名.tailXXXX.ts.net。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
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
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("重新配对", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "在服务器执行 python -m server.cli pair-code --role phone 获取一次性配对码，解除配对后重新输入即可。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedButton(onClick = { confirmUnpair = true }) {
                        Text("解除配对", color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        }

        item {
            Text(
                "会议记录 · Android ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }

    if (confirmUnpair) {
        AlertDialog(
            onDismissRequest = { confirmUnpair = false },
            title = { Text("解除配对？") },
            text = {
                Text("解除后本机无法上传或浏览笔记。未上传的录音仍保存在手机上，重新配对后可继续上传。")
            },
            confirmButton = {
                TextButton(onClick = {
                    confirmUnpair = false
                    container.settings.clearPairing()
                    onUnpaired()
                }) {
                    Text("解除", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmUnpair = false }) { Text("取消") }
            },
        )
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            value.ifBlank { "—" },
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(start = 16.dp),
        )
    }
}

private fun roleLabel(role: String): String = when (role) {
    "phone" -> "手机"
    "pc" -> "电脑"
    else -> role
}
