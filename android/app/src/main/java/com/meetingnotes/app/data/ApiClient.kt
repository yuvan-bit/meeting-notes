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
import java.io.IOException
import java.net.URLEncoder
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

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val binaryMedia = "application/octet-stream".toMediaType()

    suspend fun pair(serverUrl: String, code: String, deviceName: String): PairResponse {
        val url = SettingsStore.normalizeUrl(serverUrl)
        if (url.isEmpty()) throw ApiException("请填写服务器地址")
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

    suspend fun uploadChunk(
        recordingId: String,
        index: Int,
        data: ByteArray,
        sha256: String,
    ) {
        val request = Request.Builder()
            .url("${settings.serverUrl}/api/v1/recordings/$recordingId/chunks/$index")
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

    private fun authorizedRequest(path: String, method: String): Request {
        if (!settings.isPaired) throw ApiException("尚未配对", 401)
        val builder = Request.Builder()
            .url(settings.serverUrl + path)
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
            .url(settings.serverUrl + path)
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
