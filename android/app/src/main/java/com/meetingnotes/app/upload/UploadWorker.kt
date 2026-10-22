package com.meetingnotes.app.upload

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.meetingnotes.app.MeetingApp
import com.meetingnotes.app.Notifications
import com.meetingnotes.app.data.ApiException
import com.meetingnotes.app.data.RecordingCreateRequest
import java.io.File
import java.io.IOException
import java.security.MessageDigest

class UploadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as MeetingApp).container
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
        runCatching {
            Notifications.uploadStatus(applicationContext, "正在上传录音", recording.title)
        }

        return try {
            val wholeSha = sha256(file)
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
            var index = 0
            file.inputStream().use { input ->
                val buffer = ByteArray(chunkSize)
                while (index < created.totalChunks) {
                    if (isStopped) return Result.retry()
                    var filled = 0
                    while (filled < chunkSize) {
                        val read = input.read(buffer, filled, chunkSize - filled)
                        if (read < 0) break
                        filled += read
                    }
                    if (filled <= 0) break
                    val chunk = if (filled == chunkSize) buffer.copyOf() else buffer.copyOf(filled)
                    container.api.uploadChunk(
                        recordingId = created.recordingId,
                        index = index,
                        data = chunk,
                        sha256 = sha256(chunk),
                    )
                    index += 1
                    setProgress(
                        workDataOf(
                            KEY_UPLOADED_CHUNKS to index,
                            KEY_TOTAL_CHUNKS to created.totalChunks,
                        )
                    )
                }
            }
            if (index != created.totalChunks) {
                throw ApiException("本地文件读取提前结束")
            }
            val complete = container.api.completeRecording(created.recordingId)
            container.recordings.markUploaded(recordingId, created.recordingId, complete.jobId)
            notifyDone(recording.title)
            Result.success()
        } catch (e: ApiException) {
            handleApiError(container, recordingId, e)
        } catch (e: IOException) {
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

    private fun handleApiError(
        container: com.meetingnotes.app.AppContainer,
        recordingId: String,
        e: ApiException,
    ): Result {
        val message = e.message ?: "上传失败"
        val retryable = e.statusCode == 0 ||
            e.statusCode == 408 ||
            e.statusCode == 429 ||
            e.statusCode >= 500
        return if (retryable) {
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
        const val KEY_RECORDING_ID = "recording_id"
        const val KEY_UPLOADED_CHUNKS = "uploaded_chunks"
        const val KEY_TOTAL_CHUNKS = "total_chunks"
    }
}
