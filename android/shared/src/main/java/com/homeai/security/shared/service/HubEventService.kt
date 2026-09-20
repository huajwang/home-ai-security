package com.homeai.security.shared.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.homeai.security.shared.api.EventSocket
import com.homeai.security.shared.api.HubClient
import com.homeai.security.shared.auth.SessionStore
import com.homeai.security.shared.notify.HubEvents
import com.homeai.security.shared.ui.DoorAlerts
import com.homeai.security.shared.ui.HomeActivity

class HubEventService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private var socket: EventSocket? = null
    private var stopped = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ensureListenChannel()
        val notice = listenNotice()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(LISTEN_ID, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(LISTEN_ID, notice)
        }
        connect()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (SessionStore(this).accessToken() == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (intent?.getBooleanExtra(EXTRA_RING, false) == true) {
            handler.post { DoorAlerts.ring(applicationContext) }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopped = true
        handler.removeCallbacksAndMessages(null)
        socket?.close()
        socket = null
        super.onDestroy()
    }

    private fun connect() {
        if (stopped) return
        socket?.close()
        val store = SessionStore(this)
        if (store.accessToken() == null) {
            stopSelf()
            return
        }
        socket = EventSocket(
            HubClient(store),
            onEvent = { payload ->
                val type = payload.optString("type")
                android.util.Log.i("HubEventService", "event $type")
                handler.post {
                    HubEvents.dispatch(type)
                    if (type == "doorbell_pressed") {
                        DoorAlerts.ring(applicationContext)
                    } else if (type == "person_at_door") {
                        DoorAlerts.person(applicationContext)
                    }
                }
            },
            onError = {
                if (!stopped) handler.postDelayed({ connect() }, 3_000)
            }
        ).also { it.connect() }
    }

    private fun ensureListenChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(LISTEN_CHANNEL, "Hub connection", NotificationManager.IMPORTANCE_LOW)
        )
    }

    private fun listenNotice(): Notification {
        val launch = PendingIntent.getActivity(
            this,
            0,
            Intent(this, HomeActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, LISTEN_CHANNEL)
            .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
            .setContentTitle("Home hub")
            .setContentText("Listening for the doorbell")
            .setContentIntent(launch)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setGroup("hub_listen")
            .build()
    }

    companion object {
        private const val LISTEN_CHANNEL = "hub_listen"
        private const val LISTEN_ID = 40
        const val EXTRA_RING = "ring"

        fun start(context: Context) {
            if (SessionStore(context).accessToken() == null) return
            ContextCompat.startForegroundService(context, Intent(context, HubEventService::class.java))
        }
    }
}
