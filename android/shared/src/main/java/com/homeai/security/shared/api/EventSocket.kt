package com.homeai.security.shared.api

import android.util.Log
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
    private var closing = false
    private val pinger = android.os.Handler(android.os.Looper.getMainLooper())
    private val ping = object : Runnable {
        override fun run() {
            socket?.send("ping")
            if (!closing) pinger.postDelayed(this, 15_000)
        }
    }

    fun connect() {
        closing = false
        val request = Request.Builder().url(client.wsUrl()).build()
        Log.i(TAG, "connecting")
        socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "open")
                pinger.postDelayed(ping, 15_000)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.i(TAG, "event $text")
                try {
                    onEvent(JSONObject(text))
                } catch (ex: Exception) {
                    onError(ex.message ?: "bad event")
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.w(TAG, "closed $code $reason")
                if (!closing) onError("closed")
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "failed ${t.message}")
                if (!closing) onError(t.message ?: "websocket failed")
            }
        })
    }

    fun close() {
        closing = true
        pinger.removeCallbacksAndMessages(null)
        socket?.close(1000, "bye")
        socket = null
    }

    companion object {
        private const val TAG = "EventSocket"
    }
}
