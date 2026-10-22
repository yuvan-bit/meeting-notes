package com.meetingnotes.app

import android.app.Application
import android.content.Context
import androidx.core.app.NotificationChannelCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.meetingnotes.app.data.ApiClient
import com.meetingnotes.app.data.RecordingStore
import com.meetingnotes.app.data.SettingsStore
import com.meetingnotes.app.recording.RecordingController

class AppContainer(context: Context) {
    val settings = SettingsStore(context)
    val api = ApiClient(settings)
    val recordings = RecordingStore(context)
    val recordingController = RecordingController()
}

class MeetingApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        Notifications.createChannels(this)
    }
}

object Notifications {
    const val CHANNEL_RECORDING = "recording"
    const val CHANNEL_UPLOAD = "upload"
    const val RECORDING_ID = 1001
    const val UPLOAD_ID = 1002

    fun createChannels(context: Context) {
        val manager = NotificationManagerCompat.from(context)
        manager.createNotificationChannel(
            NotificationChannelCompat.Builder(CHANNEL_RECORDING, NotificationManagerCompat.IMPORTANCE_LOW)
                .setName("录音")
                .setDescription("录音进行中的常驻通知")
                .build()
        )
        manager.createNotificationChannel(
            NotificationChannelCompat.Builder(CHANNEL_UPLOAD, NotificationManagerCompat.IMPORTANCE_LOW)
                .setName("上传")
                .setDescription("录音上传与同步状态")
                .build()
        )
    }

    fun uploadStatus(context: Context, title: String, text: String) {
        val notification = NotificationCompat.Builder(context, CHANNEL_UPLOAD)
            .setSmallIcon(R.drawable.ic_mic)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(false)
            .setAutoCancel(true)
            .build()
        runCatching {
            NotificationManagerCompat.from(context)
                .notify(UPLOAD_ID, notification)
        }
    }
}
