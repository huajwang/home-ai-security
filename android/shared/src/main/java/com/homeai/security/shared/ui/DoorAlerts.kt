package com.homeai.security.shared.ui

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.homeai.security.shared.service.DismissDoorReceiver

object DoorAlerts {
    const val RING_CHANNEL_ID = "doorbell_ring"
    const val PERSON_CHANNEL_ID = "person_notice_v2"
    const val RING_ID = 41
    const val PERSON_ID = 42
    const val EXTRA_NOTICE_ID = "notice_id"

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = context.getSystemService(NotificationManager::class.java)
        listOf(
            "doorbell",
            "doorbell_alert",
            "person_notice",
            "person_notice_v3",
            "person_notice_station_v1"
        ).forEach { manager.deleteNotificationChannel(it) }

        val alarm = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        val ring = NotificationChannel(
            RING_CHANNEL_ID,
            "Doorbell",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "Doorbell button pressed"
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
            setBypassDnd(true)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            setSound(Settings.System.DEFAULT_ALARM_ALERT_URI, alarm)
        }
        val person = NotificationChannel(
            PERSON_CHANNEL_ID,
            "Person at door",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "A person was detected at the door"
            enableVibration(false)
            setSound(null, null)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        manager.createNotificationChannel(ring)
        manager.createNotificationChannel(person)
    }

    fun ring(context: Context) {
        post(
            context,
            channelId = RING_CHANNEL_ID,
            noticeId = RING_ID,
            title = "Front door",
            detail = "Doorbell pressed",
            sound = true
        )
    }

    fun person(context: Context) {
        post(
            context,
            channelId = PERSON_CHANNEL_ID,
            noticeId = PERSON_ID,
            title = "Front door",
            detail = "Person detected",
            sound = false
        )
    }

    fun cancel(context: Context, noticeId: Int? = null) {
        val manager = NotificationManagerCompat.from(context)
        if (noticeId == null) {
            manager.cancel(RING_ID)
            manager.cancel(PERSON_ID)
        } else {
            manager.cancel(noticeId)
        }
    }

    private fun post(
        context: Context,
        channelId: String,
        noticeId: Int,
        title: String,
        detail: String,
        sound: Boolean
    ) {
        ensureChannel(context)
        Log.i("DoorAlerts", "notify $detail sound=$sound")
        val home = pending(
            context,
            noticeId,
            Intent(context, HomeActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            )
        )
        val talk = pending(
            context,
            noticeId + 100,
            Intent(context, CallActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            )
        )
        val dismiss = PendingIntent.getBroadcast(
            context,
            noticeId + 200,
            Intent(context, DismissDoorReceiver::class.java).putExtra(EXTRA_NOTICE_ID, noticeId),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val builder = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(title)
            .setContentText(detail)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setContentIntent(home)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Dismiss", dismiss)
            .addAction(android.R.drawable.ic_menu_call, "Talk", talk)
            .setAutoCancel(true)
            .setTimeoutAfter(60_000)
        if (sound) {
            builder.setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setDefaults(NotificationCompat.DEFAULT_SOUND or NotificationCompat.DEFAULT_VIBRATE)
        } else {
            builder.setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_STATUS)
                .setDefaults(0)
        }
        val built = builder.build()
        if (sound) {
            built.flags = built.flags or Notification.FLAG_INSISTENT
        }
        if (Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
            == PackageManager.PERMISSION_GRANTED
        ) {
            NotificationManagerCompat.from(context).notify(noticeId, built)
        } else {
            Log.w("DoorAlerts", "POST_NOTIFICATIONS denied")
        }
    }

    private fun pending(context: Context, requestCode: Int, intent: Intent): PendingIntent {
        return PendingIntent.getActivity(
            context,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }
}
