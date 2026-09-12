package com.homeai.security.shared.ui

import android.content.Intent
import android.graphics.BitmapFactory
import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.ImageView
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.homeai.security.shared.R
import com.homeai.security.shared.api.EventSocket
import com.homeai.security.shared.api.HubClient
import com.homeai.security.shared.auth.SessionStore
import com.homeai.security.shared.model.DoorEvent
import kotlin.concurrent.thread

class HomeActivity : AppCompatActivity() {
    private lateinit var store: SessionStore
    private lateinit var client: HubClient
    private var socket: EventSocket? = null
    private val events = mutableListOf<String>()
    private val eventModels = mutableListOf<DoorEvent>()
    private lateinit var adapter: ArrayAdapter<String>
    private val stationMode: Boolean
        get() = packageName.endsWith(".station")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = SessionStore(this)
        if (store.accessToken() == null) {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }
        setContentView(if (stationMode) R.layout.activity_home_station else R.layout.activity_home_phone)
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
        socket = EventSocket(client, onEvent = { payload ->
            runOnUiThread {
                Toast.makeText(this, payload.optString("type"), Toast.LENGTH_SHORT).show()
                refresh()
            }
        }, onError = {})
        socket?.connect()
    }

    override fun onDestroy() {
        socket?.close()
        super.onDestroy()
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
