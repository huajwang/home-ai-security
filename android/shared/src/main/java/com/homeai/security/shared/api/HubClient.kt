package com.homeai.security.shared.api

import com.homeai.security.shared.auth.SessionStore
import com.homeai.security.shared.model.Device
import com.homeai.security.shared.model.DoorEvent
import com.homeai.security.shared.model.Home
import com.homeai.security.shared.model.LockStatus
import com.homeai.security.shared.model.Session
import com.homeai.security.shared.model.SystemStatus
import com.homeai.security.shared.model.User
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class HubException(val code: String, message: String) : Exception(message)

class HubClient(private val store: SessionStore) {
    private val jsonType = "application/json; charset=utf-8".toMediaType()
    private val http = HubTls.apply(
        OkHttpClient.Builder().callTimeout(20, TimeUnit.SECONDS)
    ).build()

    fun login(username: String, password: String, deviceName: String, deviceRole: String): Session {
        val body = JSONObject()
            .put("username", username)
            .put("password", password)
            .put("device_name", deviceName)
            .put("device_role", deviceRole)
        val obj = request("POST", "/v1/auth/login", body, auth = false)
        val session = parseSession(obj)
        store.save(session)
        return session
    }

    fun system(): SystemStatus {
        val obj = request("GET", "/v1/system")
        val vision = obj.getJSONObject("vision")
        val lock = obj.getJSONObject("lock")
        return SystemStatus(
            armed = obj.getBoolean("armed"),
            alarmActive = obj.optBoolean("alarm_active", false),
            visionFps = vision.optDouble("fps", 0.0),
            visionRunning = vision.optBoolean("running", false),
            lastPersonAt = vision.optString("last_person_at", null).takeIf { it.isNotBlank() && it != "null" },
            lockState = lock.optString("state"),
            lockAdapter = lock.optString("adapter"),
            hubTime = obj.optString("hub_time")
        )
    }

    fun arm(): SystemStatus {
        request("POST", "/v1/system/arm")
        return system()
    }

    fun disarm(): SystemStatus {
        request("POST", "/v1/system/disarm")
        return system()
    }

    fun events(): List<DoorEvent> {
        val obj = request("GET", "/v1/events?limit=50")
        val list = obj.getJSONArray("events")
        return buildList {
            for (i in 0 until list.length()) {
                val item = list.getJSONObject(i)
                add(
                    DoorEvent(
                        id = item.getInt("id"),
                        ts = item.getString("ts"),
                        label = item.getString("label"),
                        confidence = item.optDouble("confidence", 0.0),
                        snapshotUrl = item.optString("snapshot_url", null).takeIf { it.isNotBlank() && it != "null" }
                    )
                )
            }
        }
    }

    fun snapshotUrl(relative: String): String = store.hubBaseUrl + relative

    fun snapshotBytes(relative: String): ByteArray {
        val token = store.accessToken() ?: throw HubException("unauthorized", "Not signed in")
        val request = Request.Builder()
            .url(store.hubBaseUrl + relative)
            .header("Authorization", "Bearer $token")
            .get()
            .build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw HubException("not_found", "Snapshot not available")
            }
            return response.body?.bytes() ?: ByteArray(0)
        }
    }

    fun lockStatus(): LockStatus {
        val obj = request("GET", "/v1/lock")
        return LockStatus(obj.getString("state"), obj.optString("updated_at"), obj.optString("adapter"))
    }

    fun lockDoor(): LockStatus {
        val obj = request("POST", "/v1/lock/lock")
        return LockStatus(obj.getString("state"), obj.optString("updated_at"), obj.optString("adapter"))
    }

    fun unlockDoor(): LockStatus {
        val body = JSONObject().put("confirm", true)
        val obj = request("POST", "/v1/lock/unlock", body)
        return LockStatus(obj.getString("state"), obj.optString("updated_at"), obj.optString("adapter"))
    }

    fun createCall(): String = request("POST", "/v1/calls").getString("call_id")

    fun postOffer(callId: String, sdp: String): Pair<String, String> {
        val body = JSONObject().put("sdp", sdp).put("type", "offer")
        val obj = request("POST", "/v1/calls/$callId/offer", body)
        return obj.getString("sdp") to obj.getString("type")
    }

    fun postIce(callId: String, candidate: String, sdpMid: String?, sdpMLineIndex: Int?) {
        val body = JSONObject().put("candidate", candidate)
        if (sdpMid != null) body.put("sdpMid", sdpMid)
        if (sdpMLineIndex != null) body.put("sdpMLineIndex", sdpMLineIndex)
        request("POST", "/v1/calls/$callId/ice", body)
    }

    fun hangup(callId: String) {
        request("DELETE", "/v1/calls/$callId")
    }

    fun savePhoto(callId: String) {
        request("POST", "/v1/calls/$callId/photo")
    }

    fun startClip(callId: String) {
        request("POST", "/v1/calls/$callId/clip/start")
    }

    fun stopClip(callId: String) {
        request("POST", "/v1/calls/$callId/clip/stop")
    }

    fun wsUrl(): String {
        val base = store.hubBaseUrl.replace("https://", "wss://").replace("http://", "ws://")
        val token = store.accessToken().orEmpty()
        return "$base/v1/stream/events?access_token=$token"
    }

    private fun parseSession(obj: JSONObject): Session {
        val user = obj.getJSONObject("user")
        val home = obj.getJSONObject("home")
        val device = obj.optJSONObject("device")
        return Session(
            accessToken = obj.getString("access_token"),
            refreshToken = obj.getString("refresh_token"),
            user = User(
                user.getInt("id"),
                user.getString("username"),
                user.getString("role"),
                user.optBoolean("can_unlock", false)
            ),
            home = Home(home.optString("name", "Home")),
            device = device?.let {
                Device(it.getInt("id"), it.getString("device_name"), it.getString("device_role"))
            }
        )
    }

    fun tryRefresh(): Boolean {
        val refresh = store.refreshToken() ?: return false
        return try {
            val obj = request(
                "POST",
                "/v1/auth/refresh",
                JSONObject().put("refresh_token", refresh),
                auth = false
            )
            store.save(parseSession(obj))
            true
        } catch (_: Exception) {
            store.clear()
            false
        }
    }

    private fun request(
        method: String,
        path: String,
        body: JSONObject? = null,
        auth: Boolean = true,
        retried: Boolean = false
    ): JSONObject {
        val builder = Request.Builder().url(store.hubBaseUrl + path)
        if (auth) {
            val token = store.accessToken() ?: throw HubException("unauthorized", "Not signed in")
            builder.header("Authorization", "Bearer $token")
        }
        val payload = body?.toString()?.toRequestBody(jsonType)
        when (method) {
            "GET" -> builder.get()
            "DELETE" -> builder.delete()
            else -> builder.method(method, payload ?: "{}".toRequestBody(jsonType))
        }
        http.newCall(builder.build()).execute().use { response ->
            val text = response.body?.string().orEmpty()
            val obj = if (text.isBlank()) JSONObject() else JSONObject(text)
            if (response.code == 401 && auth && !retried && tryRefresh()) {
                return request(method, path, body, auth = true, retried = true)
            }
            if (!response.isSuccessful) {
                throw HubException(obj.optString("code", "error"), obj.optString("message", text))
            }
            return obj
        }
    }
}
