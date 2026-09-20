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
    const val CHANNEL_ID = "doorbell_alert"
    const val NOTICE_ID = 41
    const val EXTRA_TITLE = "alert_title"
    const val EXTRA_DETAIL = "alert_detail"

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.deleteNotificationChannel("doorbell")
        val alarm = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Doorbell",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "Someone pressed the doorbell"
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
            setBypassDnd(true)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            setSound(Settings.System.DEFAULT_ALARM_ALERT_URI, alarm)
        }
        manager.createNotificationChannel(channel)
    }

    fun ring(
        context: Context,
        title: String = "Front door",
        detail: String = "Doorbell pressed. Talk or dismiss."
    ) {
        ensureChannel(context)
        Log.i("DoorAlerts", "ring $detail")
        val incoming = Intent(context, IncomingDoorActivity::class.java).addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_NO_USER_ACTION
        ).putExtra(EXTRA_TITLE, title).putExtra(EXTRA_DETAIL, detail)
        val talk = Intent(context, CallActivity::class.java).addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        )
        val incomingPi = pending(context, 1, incoming)
        val talkPi = pending(context, 2, talk)
        val dismissPi = PendingIntent.getBroadcast(
            context,
            3,
            Intent(context, DismissDoorReceiver::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val built = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(title)
            .setContentText(detail)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setContentIntent(incomingPi)
            .setFullScreenIntent(incomingPi, true)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Dismiss", dismissPi)
            .addAction(android.R.drawable.ic_menu_call, "Talk", talkPi)
            .setAutoCancel(true)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .setTimeoutAfter(60_000)
            .build()
        built.flags = built.flags or Notification.FLAG_INSISTENT
        if (Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
            == PackageManager.PERMISSION_GRANTED
        ) {
            NotificationManagerCompat.from(context).notify(NOTICE_ID, built)
        } else {
            Log.w("DoorAlerts", "POST_NOTIFICATIONS denied")
        }
        try {
            context.startActivity(incoming)
        } catch (ex: Exception) {
            Log.w("DoorAlerts", "startActivity blocked: ${ex.message}")
        }
    }

    fun cancel(context: Context) {
        NotificationManagerCompat.from(context).cancel(NOTICE_ID)
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
