package com.meetingnotes.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.lifecycle.lifecycleScope
import com.meetingnotes.app.data.LocalRecording
import com.meetingnotes.app.ui.AppRoot
import com.meetingnotes.app.ui.theme.MeetingTheme
import com.meetingnotes.app.upload.UploadScheduler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private var lastWarmupMs = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MeetingTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    AppRoot()
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        val container = (application as MeetingApp).container
        container.recordings.items.value
            .filter {
                it.status == LocalRecording.STATUS_RECORDED ||
                    it.status == LocalRecording.STATUS_UPLOADING
            }
            .forEach { recording ->
                UploadScheduler.enqueue(
                    this,
                    recording.id,
                    replace = recording.status == LocalRecording.STATUS_RECORDED,
                )
            }
        val now = System.currentTimeMillis()
        if (container.settings.isPaired && now - lastWarmupMs > 60_000) {
            lastWarmupMs = now
            lifecycleScope.launch(Dispatchers.IO) {
                runCatching { container.api.me() }
            }
        }
    }
}
