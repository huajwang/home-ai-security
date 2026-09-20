package com.homeai.security.shared.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.ImageView
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.homeai.security.shared.R
import com.homeai.security.shared.api.HubClient
import com.homeai.security.shared.auth.SessionStore
import com.homeai.security.shared.model.DoorEvent
import com.homeai.security.shared.notify.HubEvents
import com.homeai.security.shared.service.HubEventService
import kotlin.concurrent.thread

class HomeActivity : AppCompatActivity() {
    private lateinit var store: SessionStore
    private lateinit var client: HubClient
    private val events = mutableListOf<String>()
    private val eventModels = mutableListOf<DoorEvent>()
    private lateinit var adapter: ArrayAdapter<String>
    private val stationMode: Boolean
        get() = packageName.endsWith(".station")
    private val hubListener = HubEvents.Listener { runOnUiThread { refresh() } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = SessionStore(this)
        if (store.accessToken() == null) {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }
        setContentView(if (stationMode) R.layout.activity_home_station else R.layout.activity_home_phone)
        DoorAlerts.ensureChannel(this)
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 9)
        }
        askBatteryExemption()
        HubEventService.start(this)
        client = HubClient(store)
        adapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, events)
        findViewById<ListView>(R.id.events).adapter = adapter
        findViewById<ListView>(R.id.events).setOnItemClickListener { _, _, position, _ ->
            val event = eventModels.getOrNull(position) ?: return@setOnItemClickListener
            val path = event.snapshotUrl ?: return@setOnItemClickListener
            thread {
                try {
                    val bytes = client.snapshotBytes(path)
                    val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    runOnUiThread {
                        val image = ImageView(this).apply { setImageBitmap(bitmap) }
                        MaterialAlertDialogBuilder(this)
                            .setTitle(event.ts)
                            .setView(image)
                            .setPositiveButton("OK", null)
                            .show()
                    }
                } catch (ex: Exception) {
                    runOnUiThread { Toast.makeText(this, ex.message, Toast.LENGTH_LONG).show() }
                }
            }
        }

        findViewById<Button>(R.id.talk).setOnClickListener {
            startActivity(Intent(this, CallActivity::class.java))
        }
        findViewById<Button>(R.id.arm).setOnClickListener { act { client.arm() } }
        findViewById<Button>(R.id.disarm).setOnClickListener { act { client.disarm() } }
        findViewById<Button>(R.id.lockDoor).setOnClickListener { act { client.lockDoor() } }
        findViewById<Button>(R.id.unlock).setOnClickListener {
            UnlockHelper.confirm(this, store, preferBiometric = !stationMode) {
                act { client.unlockDoor() }
            }
        }
        refresh()
    }

    override fun onStart() {
        super.onStart()
        HubEvents.addListener(hubListener)
    }

    override fun onStop() {
        HubEvents.removeListener(hubListener)
        super.onStop()
    }

    private fun askBatteryExemption() {
        if (Build.VERSION.SDK_INT < 23) return
        val power = getSystemService(PowerManager::class.java) ?: return
        if (power.isIgnoringBatteryOptimizations(packageName)) return
        try {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                    .setData(Uri.parse("package:$packageName"))
            )
        } catch (_: Exception) {
        }
    }

    private fun act(block: () -> Any) {
        thread {
            try {
                block()
                runOnUiThread { refresh() }
            } catch (ex: Exception) {
                runOnUiThread { Toast.makeText(this, ex.message, Toast.LENGTH_LONG).show() }
            }
        }
    }

    private fun refresh() {
        thread {
            try {
                val status = client.system()
                val list = client.events()
                runOnUiThread { bind(status.armed, status.lockState, status.alarmActive, list) }
            } catch (ex: Exception) {
                runOnUiThread {
                    findViewById<TextView>(R.id.statusLine).text = "Hub unreachable"
                    findViewById<TextView>(R.id.detailLine).text = ex.message
                }
            }
        }
    }

    private fun bind(armed: Boolean, lockState: String, alarm: Boolean, list: List<DoorEvent>) {
        val mode = when {
            !armed -> "DISARMED"
            alarm -> "ALERT"
            else -> "ALL CLEAR"
        }
        findViewById<TextView>(R.id.statusLine).text = "${if (stationMode) "Station" else "Phone"}  |  $mode"
        findViewById<TextView>(R.id.detailLine).text = "Lock: $lockState   Events: ${list.size}"
        events.clear()
        eventModels.clear()
        eventModels.addAll(list)
        events.addAll(list.map { "${it.ts}  ${it.label}  ${"%.2f".format(it.confidence)}" })
        adapter.notifyDataSetChanged()
    }
}
