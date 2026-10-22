package com.meetingnotes.app.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

class RecordingStore(context: Context) {

    private val file = File(context.filesDir, "recordings.json")
    private val json = Json { ignoreUnknownKeys = true; prettyPrint = true }
    private val _items = MutableStateFlow(load())
    val items: StateFlow<List<LocalRecording>> = _items.asStateFlow()

    @Synchronized
    fun add(recording: LocalRecording) {
        _items.value = listOf(recording) + _items.value.filterNot { it.id == recording.id }
        persist()
    }

    @Synchronized
    fun get(id: String): LocalRecording? = _items.value.firstOrNull { it.id == id }

    @Synchronized
    fun markUploading(id: String) {
        update(id) { it.copy(status = LocalRecording.STATUS_UPLOADING, error = null) }
    }

    @Synchronized
    fun markUploaded(id: String, serverRecordingId: String, jobId: String) {
        update(id) {
            it.copy(
                status = LocalRecording.STATUS_UPLOADED,
                error = null,
                serverRecordingId = serverRecordingId,
                jobId = jobId,
            )
        }
    }

    @Synchronized
    fun markFailed(id: String, message: String) {
        update(id) { it.copy(status = LocalRecording.STATUS_FAILED, error = message) }
    }

    @Synchronized
    fun markRetry(id: String, message: String) {
        update(id) {
            it.copy(status = LocalRecording.STATUS_RECORDED, error = message.ifBlank { null })
        }
    }

    private fun update(id: String, transform: (LocalRecording) -> LocalRecording) {
        _items.value = _items.value.map { if (it.id == id) transform(it) else it }
        persist()
    }

    private fun load(): List<LocalRecording> {
        if (!file.isFile) return emptyList()
        return runCatching {
            json.decodeFromString<UploadRecordingList>(file.readText()).items
        }.getOrElse { emptyList() }
    }

    private fun persist() {
        runCatching {
            val temp = File(file.parentFile, file.name + ".tmp")
            temp.writeText(json.encodeToString(UploadRecordingList(_items.value)))
            if (!temp.renameTo(file)) {
                file.delete()
                temp.renameTo(file)
            }
        }
    }
}
