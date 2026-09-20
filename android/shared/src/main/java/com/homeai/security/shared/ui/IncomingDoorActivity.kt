package com.homeai.security.shared.ui

import android.app.KeyguardManager
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.homeai.security.shared.R

class IncomingDoorActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            )
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            keyguard?.requestDismissKeyguard(this, null)
        }
        setContentView(R.layout.activity_incoming_door)
        findViewById<TextView>(R.id.incomingTitle).text =
            intent.getStringExtra(DoorAlerts.EXTRA_TITLE) ?: "Front door"
        findViewById<TextView>(R.id.incomingDetail).text =
            intent.getStringExtra(DoorAlerts.EXTRA_DETAIL) ?: "Doorbell pressed"
        findViewById<Button>(R.id.talk).setOnClickListener {
            DoorAlerts.cancel(this)
            startActivity(Intent(this, CallActivity::class.java))
            finish()
        }
        findViewById<Button>(R.id.dismiss).setOnClickListener {
            DoorAlerts.cancel(this)
            finish()
        }
    }
}
