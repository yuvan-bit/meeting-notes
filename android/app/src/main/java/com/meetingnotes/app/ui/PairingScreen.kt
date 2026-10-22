package com.meetingnotes.app.ui

import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.meetingnotes.app.MeetingApp
import kotlinx.coroutines.launch

@Composable
fun PairingScreen(
    initialServerUrl: String,
    onPaired: () -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val container = (context.applicationContext as MeetingApp).container
    val scope = rememberCoroutineScope()

    var serverUrl by rememberSaveable { mutableStateOf(initialServerUrl) }
    var code by rememberSaveable { mutableStateOf("") }
    var deviceName by rememberSaveable {
        mutableStateOf(Build.MODEL?.takeIf { it.isNotBlank() } ?: "我的手机")
    }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun submit() {
        if (loading) return
        if (serverUrl.isBlank() || code.isBlank() || deviceName.isBlank()) {
            error = "请填写服务器地址、配对码和设备名称"
            return
        }
        loading = true
        error = null
        scope.launch {
            try {
                val result = container.api.pair(serverUrl, code, deviceName)
                container.settings.savePairing(
                    serverUrl = serverUrl,
                    token = result.token,
                    deviceId = result.deviceId,
                    deviceName = deviceName,
                )
                onPaired()
            } catch (e: Exception) {
                error = e.message ?: "配对失败，请检查地址与配对码"
            } finally {
                loading = false
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(28.dp))
        Box(
            modifier = Modifier
                .size(88.dp)
                .background(MaterialTheme.colorScheme.primary, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Filled.Mic,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimary,
                modifier = Modifier.size(44.dp),
            )
        }
        Spacer(Modifier.height(20.dp))
        Text(
            "会议记录",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "录音上传 · 电脑空闲时自动转写 · 手机随时查看",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(32.dp))

        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
        ) {
            Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text("连接服务器", style = MaterialTheme.typography.titleMedium)
                Text(
                    "在电脑上执行配对码命令，或在服务器上运行 python -m server.cli pair-code --role phone，然后填入下方。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedTextField(
                    value = serverUrl,
                    onValueChange = { serverUrl = it },
                    label = { Text("服务器地址") },
                    placeholder = { Text("https://主机名.tailXXXX.ts.net") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = code,
                    onValueChange = { code = it.uppercase().take(32) },
                    label = { Text("配对码") },
                    placeholder = { Text("例如 7K3M9Q2A") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(
                        capitalization = KeyboardCapitalization.Characters
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = deviceName,
                    onValueChange = { deviceName = it.take(40) },
                    label = { Text("设备名称") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (error != null) {
                    Text(
                        error.orEmpty(),
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Button(
                    onClick = { submit() },
                    enabled = !loading,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(50.dp),
                ) {
                    if (loading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                    } else {
                        Text("配对并开始使用")
                    }
                }
            }
        }

        Spacer(Modifier.height(20.dp))
        Text(
            "手机与电脑需连接到同一个 Tailscale 网络。配对码有效期为 10 分钟，且只能使用一次。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 8.dp),
        )
    }
}
