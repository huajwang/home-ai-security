package com.homeai.security.shared.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.widget.Button
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.homeai.security.shared.R
import com.homeai.security.shared.api.HubClient
import com.homeai.security.shared.auth.SessionStore
import com.homeai.security.shared.webrtc.DoorCall
import org.webrtc.SurfaceViewRenderer

class CallActivity : AppCompatActivity() {
    private var call: DoorCall? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_call)
        DoorAlerts.cancel(this)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.callRoot)) { view: View, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 7)
        } else {
            startCall()
        }
        findViewById<Button>(R.id.hangup).setOnClickListener { finish() }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startCall()
        } else {
            finish()
        }
    }

    private fun startCall() {
        val renderer = findViewById<SurfaceViewRenderer>(R.id.remoteVideo)
        val store = SessionStore(this)
        call = DoorCall(this, HubClient(store), renderer).also { it.start() }
    }

    override fun onDestroy() {
        call?.release()
        super.onDestroy()
    }
}
