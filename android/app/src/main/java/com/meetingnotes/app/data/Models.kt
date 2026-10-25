package com.meetingnotes.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class PairResponse(
    @SerialName("device_id") val deviceId: String,
    val token: String,
    val role: String,
)

@Serializable
data class MeResponse(
    @SerialName("device_id") val deviceId: String,
    val name: String,
    val role: String,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class NoteFile(
    val name: String,
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    val url: String = "",
)

@Serializable
data class NoteItem(
    @SerialName("job_id") val jobId: String,
    @SerialName("recording_id") val recordingId: String,
    val title: String = "",
    @SerialName("content_type") val contentType: String = "meeting",
    val topic: String = "",
    val summary: String = "",
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("duration_s") val durationS: Double? = null,
    val pinned: Boolean = false,
    @SerialName("audio_available") val audioAvailable: Boolean = false,
    val files: List<NoteFile> = emptyList(),
)

@Serializable
data class NotesPage(
    val items: List<NoteItem> = emptyList(),
    val total: Int = 0,
    val limit: Int = 50,
    val offset: Int = 0,
)

@Serializable
data class CachedNotesPage(
    val savedAtMs: Long = 0,
    val items: List<NoteItem> = emptyList(),
    val total: Int = 0,
)

@Serializable
data class NoteDetail(
    @SerialName("job_id") val jobId: String,
    @SerialName("recording_id") val recordingId: String,
    val title: String = "",
    @SerialName("content_type") val contentType: String = "meeting",
    val topic: String = "",
    val summary: String = "",
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("duration_s") val durationS: Double? = null,
    val pinned: Boolean = false,
    @SerialName("audio_available") val audioAvailable: Boolean = false,
    val files: List<NoteFile> = emptyList(),
    @SerialName("minutes_markdown") val minutesMarkdown: String = "",
    val meta: JsonObject? = null,
)

@Serializable
data class RecordingCreateRequest(
    val title: String,
    @SerialName("content_type") val contentType: String,
    val filename: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    val sha256: String,
    @SerialName("duration_s") val durationS: Double?,
    @SerialName("client_upload_id") val clientUploadId: String,
)

@Serializable
data class RecordingCreateResponse(
    @SerialName("recording_id") val recordingId: String,
    @SerialName("chunk_size") val chunkSize: Int,
    @SerialName("total_chunks") val totalChunks: Int,
    val status: String,
)

@Serializable
data class CompleteResponse(
    @SerialName("recording_id") val recordingId: String,
    @SerialName("job_id") val jobId: String,
    val status: String,
    @SerialName("note_id") val noteId: String? = null,
)

@Serializable
data class ChunkStatusResponse(
    @SerialName("recording_id") val recordingId: String,
    val status: String,
    @SerialName("chunk_size") val chunkSize: Int,
    @SerialName("total_chunks") val totalChunks: Int,
    val uploaded: List<Int> = emptyList(),
    val missing: List<Int> = emptyList(),
)

@Serializable
data class AppRelease(
    @SerialName("version_code") val versionCode: Int,
    @SerialName("version_name") val versionName: String,
    @SerialName("apk_url") val apkUrl: String,
    val sha256: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    val changelog: String = "",
    @SerialName("published_at") val publishedAt: String = "",
)

@Serializable
data class PairRequest(
    val code: String,
    @SerialName("device_name") val deviceName: String,
    val role: String = "phone",
)

@Serializable
data class UploadRecordingList(val items: List<LocalRecording> = emptyList())

@Serializable
data class LocalRecording(
    val id: String,
    val title: String,
    @SerialName("content_type") val contentType: String,
    @SerialName("file_path") val filePath: String,
    @SerialName("duration_ms") val durationMs: Long,
    @SerialName("created_at_ms") val createdAtMs: Long,
    val status: String = STATUS_RECORDED,
    @SerialName("server_recording_id") val serverRecordingId: String? = null,
    @SerialName("job_id") val jobId: String? = null,
    val error: String? = null,
) {
    companion object {
        const val STATUS_RECORDED = "recorded"
        const val STATUS_UPLOADING = "uploading"
        const val STATUS_UPLOADED = "uploaded"
        const val STATUS_FAILED = "failed"
    }
}
