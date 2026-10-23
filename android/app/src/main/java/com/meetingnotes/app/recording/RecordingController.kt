package com.meetingnotes.app.recording

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class RecordingUiState(
    val active: Boolean = false,
    val paused: Boolean = false,
    val startedAtMs: Long = 0L,
    val elapsedMs: Long = 0L,
    val title: String = "",
    val contentType: String = "auto",
    val error: String? = null,
    val notice: String? = null,
)

class RecordingController {
    private val _state = MutableStateFlow(RecordingUiState())
    val state: StateFlow<RecordingUiState> = _state.asStateFlow()

    fun started(title: String, contentType: String, startedAtMs: Long) {
        _state.value = RecordingUiState(
            active = true,
            startedAtMs = startedAtMs,
            title = title,
            contentType = contentType,
        )
    }

    fun tick(elapsedMs: Long) {
        val current = _state.value
        if (current.active) {
            _state.value = current.copy(elapsedMs = elapsedMs)
        }
    }

    fun setPaused(paused: Boolean, elapsedMs: Long) {
        val current = _state.value
        if (current.active) {
            _state.value = current.copy(paused = paused, elapsedMs = elapsedMs)
        }
    }

    fun finished() {
        _state.value = _state.value.copy(
            active = false,
            paused = false,
            startedAtMs = 0L,
            elapsedMs = 0L,
        )
    }

    fun setError(message: String) {
        _state.value = _state.value.copy(active = false, paused = false, error = message)
    }

    fun clearError() {
        _state.value = _state.value.copy(error = null)
    }

    fun setNotice(message: String) {
        _state.value = _state.value.copy(notice = message)
    }

    fun clearNotice() {
        _state.value = _state.value.copy(notice = null)
    }
}
