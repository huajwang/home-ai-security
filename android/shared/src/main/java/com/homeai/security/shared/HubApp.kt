package com.homeai.security.shared

import android.app.Application
import com.homeai.security.shared.service.HubEventService

class HubApp : Application() {
    override fun onCreate() {
        super.onCreate()
        HubEventService.start(this)
    }
}
