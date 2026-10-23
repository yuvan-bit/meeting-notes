package com.meetingnotes.app.data

import com.meetingnotes.app.BuildConfig

object NetworkPolicy {

    val allowsCleartext: Boolean
        get() = BuildConfig.DEBUG

    fun isInsecure(url: String): Boolean =
        url.trim().startsWith("http://", ignoreCase = true)

    fun validate(url: String): String? {
        val trimmed = url.trim()
        if (trimmed.isEmpty()) return "请填写服务器地址"
        if (!trimmed.startsWith("https://", ignoreCase = true) &&
            !trimmed.startsWith("http://", ignoreCase = true)
        ) {
            return "服务器地址必须以 https:// 开头"
        }
        if (isInsecure(trimmed) && !allowsCleartext) {
            return "正式版只允许 HTTPS 服务器地址，请改用 https:// 地址"
        }
        return null
    }

    fun pairingWarning(url: String): String? =
        if (isInsecure(url)) {
            "此地址使用明文 HTTP，配对令牌和录音可能被网络中的其他人窃听。建议改用 https:// 地址；仅在本机调试时可继续。"
        } else {
            null
        }
}
