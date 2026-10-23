package com.meetingnotes.app.recording

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import com.meetingnotes.app.MainActivity
import com.meetingnotes.app.MeetingApp
import com.meetingnotes.app.Notifications
import com.meetingnotes.app.R
import com.meetingnotes.app.data.LocalRecording
import com.meetingnotes.app.upload.UploadScheduler
import com.meetingnotes.app.util.formatDuration
import java.io.File
import java.util.UUID

class RecordingService : Service() {

    private var recorder: MediaRecorder? = null
    private var outputFile: File? = null
    private var startedAtEpoch = 0L
    private var accumulatedMs = 0L
    private var segmentStartedElapsed = 0L
    private var paused = false
    private var title = ""
    private var contentType = "auto"
    private var wakeLock: PowerManager.WakeLock? = null

    private val handler = Handler(Looper.getMainLooper())
    private val ticker = object : Runnable {
        override fun run() {
            if (recorder != null) {
                container.recordingController.tick(elapsedMs())
                updateNotification()
                handler.postDelayed(this, 1000)
            }
        }
    }

    private val container get() = (application as MeetingApp).container

    private fun elapsedMs(): Long =
        if (paused) {
            accumulatedMs
        } else {
            accumulatedMs + (SystemClock.elapsedRealtime() - segmentStartedElapsed)
        }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> if (recorder == null) startRecording(intent)
            ACTION_PAUSE -> if (recorder == null) stopSelf() else pauseRecording()
            ACTION_RESUME -> if (recorder == null) stopSelf() else resumeRecording()
            ACTION_STOP -> stopRecording(cancelled = false)
            ACTION_CANCEL -> stopRecording(cancelled = true)
            else -> if (recorder == null) stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun startRecording(intent: Intent) {
        title = intent.getStringExtra(EXTRA_TITLE).orEmpty().ifBlank { "未命名录音" }
        contentType = intent.getStringExtra(EXTRA_TYPE) ?: "auto"
        startedAtEpoch = System.currentTimeMillis()
        segmentStartedElapsed = SystemClock.elapsedRealtime()
        accumulatedMs = 0L
        paused = false

        val directory = File(filesDir, "recordings").apply { mkdirs() }
        val file = File(directory, "rec_${startedAtEpoch}_${UUID.randomUUID().toString().take(6)}.m4a")
        outputFile = file
        startAsForeground()

        try {
            val newRecorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                MediaRecorder(this)
            } else {
                @Suppress("DEPRECATION")
                MediaRecorder()
            }
            newRecorder.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioSamplingRate(16_000)
                setAudioEncodingBitRate(32_000)
                setAudioChannels(1)
                setOutputFile(file.absolutePath)
                prepare()
                start()
            }
            recorder = newRecorder

            acquireWakeLock()
            container.recordingController.started(title, contentType, startedAtEpoch)
            handler.post(ticker)
        } catch (e: Exception) {
            file.delete()
            cleanup()
            container.recordingController.setError("无法开始录音：${e.message ?: "未知错误"}")
            stopForegroundNow()
            stopSelf()
        }
    }

    private fun stopRecording(cancelled: Boolean) {
        val activeRecorder = recorder
        if (activeRecorder == null) {
            stopSelf()
            return
        }
        val duration = elapsedMs()
        val file = outputFile
        var saved = false
        try {
            if (paused) {
                runCatching { activeRecorder.resume() }
                paused = false
            }
            activeRecorder.stop()
            if (!cancelled && file != null && file.length() > 0) {
                val recording = LocalRecording(
                    id = UUID.randomUUID().toString(),
                    title = title,
                    contentType = contentType,
                    filePath = file.absolutePath,
                    durationMs = duration,
                    createdAtMs = startedAtEpoch,
                    status = LocalRecording.STATUS_RECORDED,
                )
                container.recordings.add(recording)
                UploadScheduler.enqueue(this, recording.id)
                saved = true
            }
        } catch (e: RuntimeException) {
            if (!cancelled) {
                container.recordingController.setError("录音时间过短或编码失败，本次未保存")
            }
        } finally {
            runCatching { activeRecorder.release() }
            recorder = null
            paused = false
            if (cancelled || !saved) {
                file?.delete()
            }
            finishService()
        }
    }

    private fun pauseRecording() {
        val active = recorder ?: return
        if (paused) return
        val elapsed = elapsedMs()
        try {
            active.pause()
        } catch (e: RuntimeException) {
            container.recordingController.setNotice("此设备暂不支持暂停录音，已继续录制")
            return
        }
        accumulatedMs = elapsed
        paused = true
        releaseWakeLock()
        container.recordingController.setPaused(true, accumulatedMs)
        updateNotification()
    }

    private fun resumeRecording() {
        val active = recorder ?: return
        if (!paused) return
        try {
            active.resume()
        } catch (e: RuntimeException) {
            container.recordingController.setNotice("恢复录音失败，请停止后重新录制")
            return
        }
        segmentStartedElapsed = SystemClock.elapsedRealtime()
        paused = false
        acquireWakeLock()
        container.recordingController.setPaused(false, accumulatedMs)
        updateNotification()
    }

    private fun finishService() {
        handler.removeCallbacks(ticker)
        container.recordingController.finished()
        cleanup()
        stopForegroundNow()
        stopSelf()
    }

    override fun onDestroy() {
        val active = recorder
        if (active != null) {
            val duration = elapsedMs()
            if (paused) {
                runCatching { active.resume() }
                paused = false
            }
            runCatching { active.stop() }
            runCatching { active.release() }
            recorder = null
            paused = false
            val file = outputFile
            if (file != null && file.length() > 0) {
                val recording = LocalRecording(
                    id = UUID.randomUUID().toString(),
                    title = title,
                    contentType = contentType,
                    filePath = file.absolutePath,
                    durationMs = duration,
                    createdAtMs = startedAtEpoch,
                    status = LocalRecording.STATUS_RECORDED,
                    error = "录音被系统中断，已保存到本地",
                )
                container.recordings.add(recording)
                UploadScheduler.enqueue(this, recording.id)
            }
            container.recordingController.finished()
        }
        handler.removeCallbacks(ticker)
        cleanup()
        super.onDestroy()
    }

    private fun startAsForeground() {
        val openApp = PendingIntent.getActivity(
            this,
            1,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            2,
            Intent(this, RecordingService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = buildNotification(title, "00:00:00", openApp, stop)
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        } else {
            0
        }
        ServiceCompat.startForeground(this, Notifications.RECORDING_ID, notification, type)
    }

    private fun updateNotification() {
        val openApp = PendingIntent.getActivity(
            this,
            1,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            2,
            Intent(this, RecordingService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val elapsed = formatDuration(elapsedMs())
        val notification = buildNotification(title, elapsed, openApp, stop)
        runCatching {
            NotificationManagerCompat.from(this)
                .notify(Notifications.RECORDING_ID, notification)
        }
    }

    private fun buildNotification(
        titleText: String,
        text: String,
        openApp: PendingIntent,
        stop: PendingIntent,
    ): Notification {
        val toggle = PendingIntent.getService(
            this,
            if (paused) 4 else 3,
            Intent(this, RecordingService::class.java)
                .setAction(if (paused) ACTION_RESUME else ACTION_PAUSE),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, Notifications.CHANNEL_RECORDING)
            .setSmallIcon(R.drawable.ic_mic)
            .setContentTitle(titleText)
            .setContentText(if (paused) "已暂停 · $text" else text)
            .setContentIntent(openApp)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .addAction(0, if (paused) "继续" else "暂停", toggle)
            .addAction(0, "停止", stop)
            .build()
    }

    private fun stopForegroundNow() {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
    }

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MeetingNotes:recording").apply {
            setReferenceCounted(false)
            acquire(6 * 60 * 60 * 1000L)
        }
    }

    private fun releaseWakeLock() {
        runCatching {
            if (wakeLock?.isHeld == true) wakeLock?.release()
        }
        wakeLock = null
    }

    private fun cleanup() {
        handler.removeCallbacks(ticker)
        releaseWakeLock()
    }

    companion object {
        const val ACTION_START = "com.meetingnotes.app.action.START"
        const val ACTION_STOP = "com.meetingnotes.app.action.STOP"
        const val ACTION_CANCEL = "com.meetingnotes.app.action.CANCEL"
        const val ACTION_PAUSE = "com.meetingnotes.app.action.PAUSE"
        const val ACTION_RESUME = "com.meetingnotes.app.action.RESUME"
        const val EXTRA_TITLE = "title"
        const val EXTRA_TYPE = "content_type"

        fun start(context: Context, title: String, contentType: String) {
            val intent = Intent(context, RecordingService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_TITLE, title)
                putExtra(EXTRA_TYPE, contentType)
            }
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) {
            val intent = Intent(context, RecordingService::class.java).setAction(ACTION_STOP)
            context.startService(intent)
        }

        fun pause(context: Context) {
            val intent = Intent(context, RecordingService::class.java).setAction(ACTION_PAUSE)
            context.startService(intent)
        }

        fun resume(context: Context) {
            val intent = Intent(context, RecordingService::class.java).setAction(ACTION_RESUME)
            context.startService(intent)
        }

        fun cancel(context: Context) {
            val intent = Intent(context, RecordingService::class.java).setAction(ACTION_CANCEL)
            context.startService(intent)
        }
    }
}
