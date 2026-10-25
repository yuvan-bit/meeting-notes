package com.meetingnotes.app.upload

import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.meetingnotes.app.MeetingApp
import com.meetingnotes.app.Notifications
import com.meetingnotes.app.R
import com.meetingnotes.app.data.ApiClient
import com.meetingnotes.app.data.ApiException
import com.meetingnotes.app.data.RecordingCreateRequest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.supervisorScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicInteger

class UploadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    private val container get() = (applicationContext as MeetingApp).container

    override suspend fun doWork(): Result {
        val recordingId = inputData.getString(KEY_RECORDING_ID) ?: return Result.failure()
        val recording = container.recordings.get(recordingId) ?: return Result.failure()
        if (!container.settings.isPaired) {
            container.recordings.markFailed(recordingId, "尚未配对，请先在设置中完成配对")
            return Result.failure()
        }
        val file = File(recording.filePath)
        if (!file.isFile) {
            container.recordings.markFailed(recordingId, "本地录音文件不存在")
            return Result.failure()
        }

        container.recordings.markUploading(recordingId)
        enterForeground(recording.title, 0, 0)

        return try {
            val wholeSha = withContext(Dispatchers.IO) { sha256(file) }
            val created = container.api.createRecording(
                RecordingCreateRequest(
                    title = recording.title,
                    contentType = recording.contentType,
                    filename = file.name,
                    sizeBytes = file.length(),
                    sha256 = wholeSha,
                    durationS = recording.durationMs / 1000.0,
                    clientUploadId = recording.id,
                )
            )
            if (created.status != "uploading") {
                val complete = container.api.completeRecording(created.recordingId)
                container.recordings.markUploaded(recordingId, created.recordingId, complete.jobId)
                notifyDone(recording.title)
                return Result.success()
            }

            val chunkSize = created.chunkSize.coerceAtLeast(1)
            val status = container.api.recordingChunks(created.recordingId)
            val uploaded = status.uploaded.toHashSet()
            val missing = (0 until created.totalChunks).filter { it !in uploaded }
            var done = uploaded.size
            updateProgress(recording.title, done, created.totalChunks)

            if (missing.isNotEmpty()) {
                done = uploadMissingChunks(
                    recordingId = created.recordingId,
                    title = recording.title,
                    file = file,
                    chunkSize = chunkSize,
                    missing = missing,
                    total = created.totalChunks,
                    alreadyDone = done,
                )
                Log.i(TAG, "上传完成 $done/${created.totalChunks} 段")
            }

            val complete = container.api.completeRecording(created.recordingId)
            container.recordings.markUploaded(recordingId, created.recordingId, complete.jobId)
            notifyDone(recording.title)
            Result.success()
        } catch (e: CancellationException) {
            throw e
        } catch (e: ApiException) {
            handleApiError(recordingId, e)
        } catch (e: IOException) {
            notifyRetry(recording.title, e.message)
            container.recordings.markRetry(recordingId, "网络异常，等待重试：${e.message ?: ""}")
            Result.retry()
        } catch (e: Exception) {
            container.recordings.markFailed(recordingId, "上传失败：${e.message ?: "未知错误"}")
            runCatching {
                Notifications.uploadStatus(applicationContext, "上传失败", recording.title)
            }
            Result.failure()
        }
    }

    /**
     * 并发上传缺失分片。单个分片失败会先做短延迟重试，全部重试失败才交给
     * WorkManager 退避，避免一次网络抖动就把整次上传拖到几十分钟后。
     */
    private suspend fun uploadMissingChunks(
        recordingId: String,
        title: String,
        file: File,
        chunkSize: Int,
        missing: List<Int>,
        total: Int,
        alreadyDone: Int,
    ): Int = supervisorScope {
        val api = container.api
        val done = AtomicInteger(alreadyDone)
        val gate = Semaphore(MAX_PARALLEL_CHUNKS)
        val results = missing.map { index ->
            async(Dispatchers.IO) {
                gate.withPermit {
                    if (isStopped) throw CancellationException("上传已停止")
                    try {
                        val data = readChunk(file, chunkSize, index)
                        uploadChunkWithRetry(api, recordingId, index, data)
                        val current = done.incrementAndGet()
                        updateProgress(title, current, total)
                        null
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        Log.w(TAG, "分片 $index 上传失败：${e.message}")
                        e
                    }
                }
            }
        }.awaitAll()
        val failure = results.firstOrNull { it != null }
        if (failure != null) throw failure
        done.get()
    }

    private suspend fun uploadChunkWithRetry(
        api: ApiClient,
        recordingId: String,
        index: Int,
        data: ByteArray,
    ) {
        val hash = sha256(data)
        var lastError: Exception? = null
        for (attempt in 1..CHUNK_ATTEMPTS) {
            if (isStopped) throw CancellationException("上传已停止")
            val started = System.currentTimeMillis()
            try {
                api.uploadChunk(recordingId, index, data, hash)
                Log.i(TAG, "分片 $index 完成：${data.size}B，${System.currentTimeMillis() - started}ms")
                return
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiException) {
                val status = e.statusCode
                if (status in 400..499 && status != 408 && status != 429) throw e
                lastError = e
            } catch (e: IOException) {
                lastError = e
            }
            Log.w(
                TAG,
                "分片 $index 第 $attempt 次失败：${lastError?.message ?: "未知错误"}",
            )
            if (attempt < CHUNK_ATTEMPTS) {
                api.resetConnections()
                delay(1_500L * attempt)
            }
        }
        throw lastError ?: ApiException("分片上传失败")
    }

    private fun readChunk(file: File, chunkSize: Int, index: Int): ByteArray {
        RandomAccessFile(file, "r").use { raf ->
            val offset = index.toLong() * chunkSize
            val length = minOf(chunkSize.toLong(), file.length() - offset).toInt()
            if (length <= 0) {
                throw ApiException("本地录音文件不完整，缺少第 ${index + 1} 段")
            }
            val chunk = ByteArray(length)
            raf.seek(offset)
            raf.readFully(chunk)
            return chunk
        }
    }

    private suspend fun updateProgress(title: String, done: Int, total: Int) {
        setProgress(
            workDataOf(
                KEY_UPLOADED_CHUNKS to done,
                KEY_TOTAL_CHUNKS to total,
            )
        )
        enterForeground(title, done, total)
    }

    private suspend fun enterForeground(title: String, done: Int, total: Int) {
        try {
            setForeground(foregroundInfo(title, done, total))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w(TAG, "无法切换为前台上传：${e.message}")
        }
    }

    override suspend fun getForegroundInfo(): ForegroundInfo {
        val recordingId = inputData.getString(KEY_RECORDING_ID)
        val title = recordingId?.let { container.recordings.get(it)?.title } ?: "录音"
        return foregroundInfo(title, 0, 0)
    }

    private fun foregroundInfo(title: String, done: Int, total: Int): ForegroundInfo {
        val safeTotal = total.coerceAtLeast(0)
        val safeDone = done.coerceIn(0, safeTotal.coerceAtLeast(1))
        val text = if (safeTotal > 0) "$title · $safeDone/$safeTotal 段" else title
        val notification = NotificationCompat.Builder(applicationContext, Notifications.CHANNEL_UPLOAD)
            .setSmallIcon(R.drawable.ic_mic)
            .setContentTitle("正在上传录音")
            .setContentText(text)
            .setOnlyAlertOnce(true)
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setProgress(safeTotal, safeDone, safeTotal == 0)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                Notifications.UPLOAD_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(Notifications.UPLOAD_ID, notification)
        }
    }

    private fun handleApiError(recordingId: String, e: ApiException): Result {
        val message = e.message ?: "上传失败"
        val retryable = e.statusCode == 0 ||
            e.statusCode == 408 ||
            e.statusCode == 429 ||
            e.statusCode >= 500
        return if (retryable) {
            notifyRetry("录音", message)
            container.recordings.markRetry(recordingId, "等待重试：$message")
            Result.retry()
        } else {
            container.recordings.markFailed(recordingId, message)
            runCatching {
                Notifications.uploadStatus(applicationContext, "上传失败", message)
            }
            Result.failure()
        }
    }

    private fun notifyRetry(title: String, message: String?) {
        runCatching {
            Notifications.uploadStatus(
                applicationContext,
                "上传暂时中断，将自动继续",
                "$title · ${message ?: "网络不稳"}",
            )
        }
    }

    private fun notifyDone(title: String) {
        runCatching {
            Notifications.uploadStatus(
                applicationContext,
                "录音已上传",
                "$title 已进入电脑转写队列",
            )
        }
    }

    private fun sha256(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        return digest.joinToString("") { "%02x".format(it) }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    companion object {
        private const val TAG = "UploadWorker"
        private const val MAX_PARALLEL_CHUNKS = 3
        private const val CHUNK_ATTEMPTS = 3

        const val KEY_RECORDING_ID = "recording_id"
        const val KEY_UPLOADED_CHUNKS = "uploaded_chunks"
        const val KEY_TOTAL_CHUNKS = "total_chunks"
    }
}
