package com.meetingnotes.app.data

import android.content.Context
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

/**
 * 笔记列表和详情的轻量磁盘缓存：先显示上一次内容，再后台刷新。
 * 网络慢或 Tailscale 正在重连时，打开笔记不会再一直转圈。
 */
class NoteCache(context: Context) {

    private val root = File(context.filesDir, "note_cache")
    private val listFile = File(root, "list.json")
    private val detailDir = File(root, "details")
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    @Synchronized
    fun loadList(): CachedNotesPage? {
        if (!listFile.isFile) return null
        return runCatching {
            json.decodeFromString<CachedNotesPage>(listFile.readText())
        }.getOrNull()
    }

    @Synchronized
    fun saveList(page: NotesPage) {
        write(
            listFile,
            json.encodeToString(
                CachedNotesPage(
                    savedAtMs = System.currentTimeMillis(),
                    items = page.items,
                    total = page.total,
                )
            ),
        )
    }

    @Synchronized
    fun loadDetail(jobId: String): NoteDetail? {
        val file = detailFile(jobId)
        if (!file.isFile) return null
        return runCatching {
            json.decodeFromString<NoteDetail>(file.readText())
        }.getOrNull()
    }

    @Synchronized
    fun saveDetail(detail: NoteDetail) {
        write(detailFile(detail.jobId), json.encodeToString(detail))
        pruneDetails()
    }

    @Synchronized
    fun clear() {
        runCatching { root.deleteRecursively() }
    }

    private fun detailFile(jobId: String): File {
        val safe = jobId.replace(Regex("[^0-9A-Za-z._-]"), "_").take(120)
        return File(detailDir, "$safe.json")
    }

    private fun write(file: File, text: String) {
        runCatching {
            file.parentFile?.mkdirs()
            val temp = File(file.parentFile, file.name + ".tmp")
            temp.writeText(text)
            if (!temp.renameTo(file)) {
                file.delete()
                temp.renameTo(file)
            }
        }
    }

    private fun pruneDetails() {
        runCatching {
            val files = detailDir.listFiles()?.filter { it.isFile } ?: return
            if (files.size <= MAX_DETAILS) return
            files.sortedBy { it.lastModified() }
                .take(files.size - MAX_DETAILS)
                .forEach { it.delete() }
        }
    }

    companion object {
        private const val MAX_DETAILS = 200
    }
}
