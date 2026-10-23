package com.meetingnotes.app.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class ApiException(message: String, val statusCode: Int = 0) : IOException(message)

class ApiClient(private val settings: SettingsStore) {

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        encodeDefaults = true
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)
        .writeTimeout(180, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private val downloadClient = client.newBuilder()
        .readTimeout(300, TimeUnit.SECONDS)
        .build()

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val binaryMedia = "application/octet-stream".toMediaType()

    suspend fun pair(serverUrl: String, code: String, deviceName: String): PairResponse {
        val url = SettingsStore.normalizeUrl(serverUrl)
        NetworkPolicy.validate(url)?.let { throw ApiException(it) }
        val payload = json.encodeToString(
            PairRequest(code = code.trim().uppercase(), deviceName = deviceName.trim())
        )
        val request = Request.Builder()
            .url("$url/api/v1/pair")
            .post(payload.toRequestBody(jsonMedia))
            .build()
        val body = execute(request, authenticated = false)
        return json.decodeFromString(body)
    }

    suspend fun me(): MeResponse = json.decodeFromString(request("/api/v1/me"))

    suspend fun listNotes(
        query: String = "",
        contentType: String = "",
        limit: Int = 50,
        offset: Int = 0,
    ): NotesPage {
        val params = buildString {
            append("?limit=").append(limit)
            append("&offset=").append(offset)
            if (query.isNotBlank()) {
                append("&q=").append(URLEncoder.encode(query, "UTF-8"))
            }
            if (contentType.isNotBlank()) {
                append("&content_type=").append(contentType)
            }
        }
        return json.decodeFromString(request("/api/v1/notes$params"))
    }

    suspend fun noteDetail(jobId: String): NoteDetail =
        json.decodeFromString(request("/api/v1/notes/$jobId"))

    suspend fun downloadNoteFile(jobId: String, name: String): ByteArray {
        val request = authorizedRequest("/api/v1/notes/$jobId/files/$name", "GET")
        val response = executeRaw(request)
        return response.use { it.body?.bytes() ?: ByteArray(0) }
    }

    suspend fun createRecording(payload: RecordingCreateRequest): RecordingCreateResponse {
        val body = json.encodeToString(payload)
        return json.decodeFromString(
            request("/api/v1/recordings", method = "POST", body = body)
        )
    }

    suspend fun recordingChunks(recordingId: String): ChunkStatusResponse =
        json.decodeFromString(request("/api/v1/recordings/$recordingId/chunks"))

    suspend fun uploadChunk(
        recordingId: String,
        index: Int,
        data: ByteArray,
        sha256: String,
    ) {
        val request = Request.Builder()
            .url("${baseUrl()}/api/v1/recordings/$recordingId/chunks/$index")
            .header("Authorization", "Bearer ${settings.token}")
            .header("X-Chunk-SHA256", sha256)
            .put(data.toRequestBody(binaryMedia))
            .build()
        execute(request, authenticated = true)
    }

    suspend fun completeRecording(recordingId: String): CompleteResponse {
        val body = request("/api/v1/recordings/$recordingId/complete", method = "POST")
        return json.decodeFromString(body)
    }

    suspend fun latestApp(): AppRelease? {
        val request = Request.Builder()
            .url("${baseUrl()}/api/v1/app/latest")
            .get()
            .build()
        return try {
            json.decodeFromString(execute(request, authenticated = false))
        } catch (e: ApiException) {
            if (e.statusCode == 404) null else throw e
        }
    }

    suspend fun downloadApk(
        apkPath: String,
        target: File,
        expectedSha256: String,
        expectedSize: Long,
        onProgress: (Float) -> Unit,
    ): File = withContext(Dispatchers.IO) {
        val path = apkPath.trim()
        if (!path.startsWith("/")) throw ApiException("更新地址无效", 400)
        val request = Request.Builder().url(baseUrl() + path).get().build()
        val response = try {
            downloadClient.newCall(request).await()
        } catch (e: IOException) {
            throw ApiException("下载更新失败：${e.message ?: "网络错误"}")
        }
        if (!response.isSuccessful) {
            val text = runCatching { response.body?.string().orEmpty() }.getOrDefault("")
            response.close()
            throw ApiException(parseError(text, response.code), response.code)
        }
        val parent = target.parentFile ?: throw ApiException("无法创建更新缓存目录")
        parent.mkdirs()
        val temp = File(parent, target.name + ".part")
        try {
            response.use { resp ->
                val body = resp.body ?: throw ApiException("服务器未返回安装包")
                val total = body.contentLength().takeIf { it > 0 } ?: expectedSize
                body.byteStream().use { input ->
                    temp.outputStream().use { output ->
                        val buffer = ByteArray(256 * 1024)
                        var copied = 0L
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) break
                            output.write(buffer, 0, read)
                            copied += read
                            if (total > 0) {
                                onProgress((copied.toFloat() / total).coerceIn(0f, 1f))
                            }
                        }
                    }
                }
            }
            if (expectedSize > 0 && temp.length() != expectedSize) {
                throw ApiException("安装包大小校验失败，请重新下载")
            }
            if (!sha256(temp).equals(expectedSha256.trim(), ignoreCase = true)) {
                throw ApiException("安装包校验失败，请重新下载")
            }
            if (target.exists() && !target.delete()) {
                throw ApiException("无法替换旧的安装包")
            }
            if (!temp.renameTo(target)) {
                temp.copyTo(target, overwrite = true)
                temp.delete()
            }
            onProgress(1f)
            target
        } catch (e: Exception) {
            temp.delete()
            throw e
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun baseUrl(): String {
        val url = settings.serverUrl
        NetworkPolicy.validate(url)?.let { throw ApiException(it, 400) }
        return url
    }

    private fun authorizedRequest(path: String, method: String): Request {
        if (!settings.isPaired) throw ApiException("尚未配对", 401)
        val builder = Request.Builder()
            .url(baseUrl() + path)
            .header("Authorization", "Bearer ${settings.token}")
        when (method) {
            "GET" -> builder.get()
            else -> builder.method(method, ByteArray(0).toRequestBody(null))
        }
        return builder.build()
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: String? = null,
    ): String {
        if (!settings.isPaired) throw ApiException("尚未配对", 401)
        val builder = Request.Builder()
            .url(baseUrl() + path)
            .header("Authorization", "Bearer ${settings.token}")
        when {
            body != null -> builder.method(method, body.toRequestBody(jsonMedia))
            method == "GET" -> builder.get()
            else -> builder.method(method, ByteArray(0).toRequestBody(null))
        }
        return execute(builder.build(), authenticated = true)
    }

    private suspend fun execute(request: Request, authenticated: Boolean): String =
        executeRaw(request, authenticated).use { response ->
            response.body?.string().orEmpty()
        }

    private suspend fun executeRaw(
        request: Request,
        authenticated: Boolean = true,
    ): Response = withContext(Dispatchers.IO) {
        val finalRequest = if (authenticated && request.header("Authorization") == null) {
            request.newBuilder().header("Authorization", "Bearer ${settings.token}").build()
        } else {
            request
        }
        val response = try {
            client.newCall(finalRequest).await()
        } catch (e: IOException) {
            throw ApiException("无法连接服务器：${e.message ?: "网络错误"}")
        }
        if (!response.isSuccessful) {
            val text = runCatching { response.body?.string().orEmpty() }.getOrDefault("")
            response.close()
            throw ApiException(parseError(text, response.code), response.code)
        }
        response
    }

    private fun parseError(body: String, code: Int): String {
        val detail = runCatching {
            json.parseToJsonElement(body).jsonObject["detail"]
        }.getOrNull()
        return when (detail) {
            is JsonPrimitive -> detail.content
            null -> "服务器返回 $code"
            else -> detail.toString()
        }
    }

    private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
        enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (cont.isActive) cont.resumeWithException(e)
            }

            override fun onResponse(call: Call, response: Response) {
                if (cont.isActive) cont.resume(response) else response.close()
            }
        })
        cont.invokeOnCancellation { runCatching { cancel() } }
    }
}
