package com.homeai.security.shared.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.homeai.security.shared.ui.DoorAlerts

class DismissDoorReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val noticeId = intent.getIntExtra(DoorAlerts.EXTRA_NOTICE_ID, -1)
        DoorAlerts.cancel(context, if (noticeId >= 0) noticeId else null)
    }
}
