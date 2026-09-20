package com.homeai.security.shared.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class HubBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action == Intent.ACTION_BOOT_COMPLETED || action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            HubEventService.start(context)
        }
    }
}
