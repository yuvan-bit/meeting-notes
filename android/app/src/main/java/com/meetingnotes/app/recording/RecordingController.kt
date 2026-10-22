package com.meetingnotes.app.recording

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class RecordingUiState(
    val active: Boolean = false,
    val startedAtMs: Long = 0L,
    val title: String = "",
    val contentType: String = "auto",
    val error: String? = null,
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

    fun finished() {
        _state.value = _state.value.copy(active = false, startedAtMs = 0L)
    }

    fun setError(message: String) {
        _state.value = _state.value.copy(active = false, error = message)
    }

    fun clearError() {
        _state.value = _state.value.copy(error = null)
    }
}
