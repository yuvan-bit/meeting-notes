package com.meetingnotes.app.data

import android.content.Context

class SettingsStore(context: Context) {

    private val prefs =
        context.applicationContext.getSharedPreferences("meeting_settings", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = prefs.getString(KEY_SERVER_URL, "").orEmpty()
        set(value) {
            prefs.edit().putString(KEY_SERVER_URL, normalizeUrl(value)).apply()
        }

    var token: String
        get() = prefs.getString(KEY_TOKEN, "").orEmpty()
        private set(value) {
            prefs.edit().putString(KEY_TOKEN, value).apply()
        }

    var deviceId: String
        get() = prefs.getString(KEY_DEVICE_ID, "").orEmpty()
        private set(value) {
            prefs.edit().putString(KEY_DEVICE_ID, value).apply()
        }

    var deviceName: String
        get() = prefs.getString(KEY_DEVICE_NAME, "").orEmpty()
        private set(value) {
            prefs.edit().putString(KEY_DEVICE_NAME, value).apply()
        }

    val isPaired: Boolean
        get() = serverUrl.isNotBlank() && token.isNotBlank()

    fun savePairing(serverUrl: String, token: String, deviceId: String, deviceName: String) {
        prefs.edit()
            .putString(KEY_SERVER_URL, normalizeUrl(serverUrl))
            .putString(KEY_TOKEN, token)
            .putString(KEY_DEVICE_ID, deviceId)
            .putString(KEY_DEVICE_NAME, deviceName)
            .apply()
    }

    fun clearPairing() {
        prefs.edit()
            .remove(KEY_TOKEN)
            .remove(KEY_DEVICE_ID)
            .remove(KEY_DEVICE_NAME)
            .apply()
    }

    companion object {
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_TOKEN = "device_token"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_DEVICE_NAME = "device_name"

        fun normalizeUrl(raw: String): String {
            var url = raw.trim()
            if (url.isEmpty()) return ""
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                url = "http://$url"
            }
            return url.trimEnd('/')
        }
    }
}
