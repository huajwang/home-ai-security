package com.homeai.security.shared.api

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class EventSocket(
    private val client: HubClient,
    private val onEvent: (JSONObject) -> Unit,
    private val onError: (String) -> Unit
) {
    private val http = HubTls.apply(
        OkHttpClient.Builder().readTimeout(0, TimeUnit.MILLISECONDS)
    ).build()
    private var socket: WebSocket? = null

    fun connect() {
        val request = Request.Builder().url(client.wsUrl()).build()
        socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    onEvent(JSONObject(text))
                } catch (ex: Exception) {
                    onError(ex.message ?: "bad event")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                onError(t.message ?: "websocket failed")
            }
        })
    }

    fun close() {
        socket?.close(1000, "bye")
        socket = null
    }
}
