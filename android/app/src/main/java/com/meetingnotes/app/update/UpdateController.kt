package com.meetingnotes.app.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import com.meetingnotes.app.BuildConfig
import com.meetingnotes.app.data.ApiClient
import com.meetingnotes.app.data.AppRelease
import com.meetingnotes.app.data.SettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File

data class UpdateState(
    val checking: Boolean = false,
    val checked: Boolean = false,
    val release: AppRelease? = null,
    val downloading: Boolean = false,
    val progress: Float = 0f,
    val apk: File? = null,
    val error: String? = null,
)

class UpdateController(
    private val context: Context,
    private val api: ApiClient,
    private val settings: SettingsStore,
) {
    private val _state = MutableStateFlow(UpdateState())
    val state = _state.asStateFlow()

    suspend fun check() {
        if (!settings.isPaired || _state.value.checking || _state.value.downloading) return
        val previous = _state.value
        _state.value = previous.copy(checking = true, error = null)
        try {
            val release = api.latestApp()
            val newer = release != null && release.versionCode > BuildConfig.VERSION_CODE
            val downloadedSame = release != null && previous.release?.versionCode == release.versionCode
            _state.value = previous.copy(
                checking = false,
                checked = true,
                release = if (newer) release else null,
                apk = if (downloadedSame) previous.apk else null,
                error = null,
            )
        } catch (e: Exception) {
            _state.value = previous.copy(
                checking = false,
                error = e.message ?: "检查更新失败",
            )
        }
    }

    suspend fun download() {
        val release = _state.value.release ?: return
        if (_state.value.downloading || _state.value.checking) return
        _state.value = _state.value.copy(
            downloading = true,
            progress = 0f,
            apk = null,
            error = null,
        )
        try {
            val directory = File(context.cacheDir, "updates")
            val target = File(directory, "meeting-notes-${release.versionCode}.apk")
            val apk = api.downloadApk(
                apkPath = release.apkUrl,
                target = target,
                expectedSha256 = release.sha256,
                expectedSize = release.sizeBytes,
            ) { progress ->
                _state.value = _state.value.copy(progress = progress)
            }
            _state.value = _state.value.copy(downloading = false, progress = 1f, apk = apk)
        } catch (e: Exception) {
            _state.value = _state.value.copy(
                downloading = false,
                progress = 0f,
                error = e.message ?: "下载更新失败",
            )
        }
    }

    fun install(): String? {
        val apk = _state.value.apk ?: return "请先下载更新"
        if (!apk.isFile) return "安装包不存在，请重新下载"
        if (!context.packageManager.canRequestPackageInstalls()) {
            val intent = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}"),
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            return try {
                context.startActivity(intent)
                "请在设置中允许本应用安装未知应用，然后返回重试"
            } catch (e: Exception) {
                "无法打开安装权限设置：${e.message ?: "未知错误"}"
            }
        }
        return try {
            val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", apk)
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
            null
        } catch (e: Exception) {
            "无法启动系统安装器：${e.message ?: "未知错误"}"
        }
    }
}
