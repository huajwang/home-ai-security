package com.homeai.security.shared.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageButton
import android.widget.Toast
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
import kotlin.concurrent.thread

class CallActivity : AppCompatActivity() {
    private var call: DoorCall? = null
    private var talking = false
    private var recording = false
    private lateinit var client: HubClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_call)
        DoorAlerts.cancel(this)
        client = HubClient(SessionStore(this))
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.callRoot)) { view: View, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        findViewById<ImageButton>(R.id.photoButton).setOnClickListener { savePhoto() }
        findViewById<ImageButton>(R.id.recordButton).setOnClickListener { toggleRecord() }
        findViewById<ImageButton>(R.id.voiceToggle).setOnClickListener { toggleVoice() }
        findViewById<Button>(R.id.hangup).setOnClickListener { finish() }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 7)
        } else {
            startCall()
        }
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

    private fun savePhoto() {
        val id = call?.callId()
        if (id == null) {
            Toast.makeText(this, "Wait for video", Toast.LENGTH_SHORT).show()
            return
        }
        thread {
            try {
                client.savePhoto(id)
                runOnUiThread { Toast.makeText(this, "Photo saved", Toast.LENGTH_SHORT).show() }
            } catch (ex: Exception) {
                runOnUiThread { Toast.makeText(this, ex.message, Toast.LENGTH_LONG).show() }
            }
        }
    }

    private fun toggleRecord() {
        val id = call?.callId()
        if (id == null) {
            Toast.makeText(this, "Wait for video", Toast.LENGTH_SHORT).show()
            return
        }
        val start = !recording
        thread {
            try {
                if (start) {
                    client.startClip(id)
                } else {
                    client.stopClip(id)
                }
                runOnUiThread {
                    recording = start
                    val button = findViewById<ImageButton>(R.id.recordButton)
                    button.isSelected = recording
                    button.contentDescription = if (recording) "Stop recording" else "Record clip"
                    Toast.makeText(
                        this,
                        if (recording) "Recording" else "Clip saved",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            } catch (ex: Exception) {
                runOnUiThread { Toast.makeText(this, ex.message, Toast.LENGTH_LONG).show() }
            }
        }
    }

    private fun toggleVoice() {
        talking = !talking
        call?.setMicEnabled(talking)
        val button = findViewById<ImageButton>(R.id.voiceToggle)
        button.isSelected = talking
        if (talking) {
            button.setImageResource(R.drawable.ic_call_end)
            button.contentDescription = "End voice"
        } else {
            button.setImageResource(R.drawable.ic_mic)
            button.contentDescription = "Start voice"
        }
    }

    private fun startCall() {
        val renderer = findViewById<SurfaceViewRenderer>(R.id.remoteVideo)
        val store = SessionStore(this)
        client = HubClient(store)
        call = DoorCall(this, client, renderer).also { it.start() }
        if (talking) {
            call?.setMicEnabled(true)
        }
    }

    override fun onDestroy() {
        call?.release()
        super.onDestroy()
    }
}
