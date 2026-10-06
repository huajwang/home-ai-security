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
import android.speech.RecognizerIntent
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import java.io.ByteArrayOutputStream
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
    private val jpegStart = byteArrayOf(0xFF.toByte(), 0xD8.toByte())
    private val jpegEnd = byteArrayOf(0xFF.toByte(), 0xD9.toByte())
    private lateinit var store: SessionStore
    private lateinit var client: HubClient
    private val events = mutableListOf<String>()
    private val eventModels = mutableListOf<DoorEvent>()
    private lateinit var adapter: ArrayAdapter<String>
    private val stationMode: Boolean
        get() = packageName.endsWith(".station")
    private val hubListener = HubEvents.Listener { runOnUiThread { refresh() } }
    private var searchText: String = ""

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
        findViewById<Button>(R.id.lightOn).setOnClickListener { act { client.lightOn() } }
        findViewById<Button>(R.id.lightOff).setOnClickListener { act { client.lightOff() } }
        findViewById<Button>(R.id.pairBulb).setOnClickListener { act { client.pairBulb() } }
        findViewById<Button>(R.id.pairLock).setOnClickListener { act { client.pairLock() } }
        findViewById<Button>(R.id.driveway).setOnClickListener { showDriveway() }
        if (!stationMode) {
            val searchBox = findViewById<EditText>(R.id.searchQuery)
            val runSearch = {
                searchText = searchBox.text.toString().trim()
                refresh()
            }
            findViewById<Button>(R.id.search).setOnClickListener { runSearch() }
            searchBox.setOnEditorActionListener { _, actionId, _ ->
                if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH) {
                    runSearch()
                    true
                } else {
                    false
                }
            }
        }
        findViewById<Button>(R.id.unlock).setOnClickListener {
            UnlockHelper.confirm(this, store, preferBiometric = !stationMode) {
                act { client.unlockDoor() }
            }
        }
        findViewById<View>(R.id.assistantVoice)?.setOnClickListener {
            startVoiceAssistant()
        }
        refresh()
    }

    private val speechRequestCode = 101

    private fun startVoiceAssistant() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Ask Home AI (e.g. 'Status?', 'Security briefing')")
        }
        try {
            startActivityForResult(intent, speechRequestCode)
        } catch (_: Exception) {
            promptTextAssistant()
        }
    }

    private fun promptTextAssistant() {
        val input = EditText(this).apply {
            hint = "Ask Home AI (e.g., 'Status?', 'Briefing')"
        }
        MaterialAlertDialogBuilder(this)
            .setTitle("Home AI Assistant")
            .setView(input)
            .setPositiveButton("Ask") { _, _ ->
                val text = input.text.toString().trim()
                if (text.isNotBlank()) {
                    queryAssistant(text)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == speechRequestCode && resultCode == RESULT_OK) {
            val spokenText = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!spokenText.isNullOrBlank()) {
                queryAssistant(spokenText)
            }
        }
    }

    private fun queryAssistant(prompt: String) {
        Toast.makeText(this, "Asking AI: \"$prompt\"", Toast.LENGTH_SHORT).show()
        thread {
            try {
                val res = client.assistantChat(prompt)
                runOnUiThread {
                    MaterialAlertDialogBuilder(this)
                        .setTitle("Home AI Assistant")
                        .setMessage(res.response)
                        .setPositiveButton("OK", null)
                        .show()
                    refresh()
                }
            } catch (ex: Exception) {
                runOnUiThread {
                    Toast.makeText(this, "Assistant error: ${ex.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
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

    private fun showDriveway() {
        val image = ImageView(this).apply {
            adjustViewBounds = true
            minimumHeight = 480
        }
        val dialog = MaterialAlertDialogBuilder(this)
            .setTitle("Driveway")
            .setView(image)
            .setPositiveButton("Close", null)
            .create()
        val call = client.drivewayStream()
        dialog.setOnDismissListener { call.cancel() }
        dialog.show()
        thread {
            try {
                call.execute().use { response ->
                    if (!response.isSuccessful) {
                        throw IllegalStateException("Driveway stream is not available")
                    }
                    val source = response.body?.byteStream() ?: return@use
                    val pending = ByteArrayOutputStream()
                    val chunk = ByteArray(8192)
                    while (true) {
                        val read = source.read(chunk)
                        if (read < 0) break
                        pending.write(chunk, 0, read)
                        val data = pending.toByteArray()
                        val start = indexOf(data, jpegStart)
                        if (start < 0) {
                            if (data.size > 2_000_000) pending.reset()
                            continue
                        }
                        val end = indexOf(data, jpegEnd, start + 2)
                        if (end < 0) continue
                        val jpeg = data.copyOfRange(start, end + 2)
                        val rest = data.copyOfRange(end + 2, data.size)
                        pending.reset()
                        pending.write(rest)
                        val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: continue
                        runOnUiThread { image.setImageBitmap(bitmap) }
                    }
                }
            } catch (ex: Exception) {
                if (!call.isCanceled()) {
                    runOnUiThread { Toast.makeText(this, ex.message, Toast.LENGTH_LONG).show() }
                }
            }
        }
    }

    private fun indexOf(data: ByteArray, marker: ByteArray, from: Int = 0): Int {
        if (marker.isEmpty() || data.size < from + marker.size) return -1
        val last = data.size - marker.size
        for (i in from..last) {
            var matched = true
            for (j in marker.indices) {
                if (data[i + j] != marker[j]) {
                    matched = false
                    break
                }
            }
            if (matched) return i
        }
        return -1
    }

    private fun act(block: () -> Any) {
        thread {
            try {
                val result = block()
                runOnUiThread {
                    if (result is String && result.isNotBlank()) {
                        Toast.makeText(this, result, Toast.LENGTH_LONG).show()
                    }
                    refresh()
                }
            } catch (ex: Exception) {
                runOnUiThread { Toast.makeText(this, ex.message, Toast.LENGTH_LONG).show() }
            }
        }
    }

    private fun refresh() {
        thread {
            try {
                val status = client.system()
                val question = searchText
                if (question.isEmpty()) {
                    val list = client.events()
                    runOnUiThread { bind(status.armed, status.lockState, status.alarmActive, list, null) }
                } else {
                    val found = client.searchEvents(question)
                    val note = if (found.understood) {
                        "Search: ${found.events.size}"
                    } else {
                        "No stored label matches that question"
                    }
                    runOnUiThread {
                        bind(status.armed, status.lockState, status.alarmActive, found.events, note)
                    }
                }
            } catch (ex: Exception) {
                runOnUiThread {
                    findViewById<TextView>(R.id.statusLine).text = "Hub unreachable"
                    findViewById<TextView>(R.id.detailLine).text = ex.message
                }
            }
        }
    }

    private fun bind(
        armed: Boolean,
        lockState: String,
        alarm: Boolean,
        list: List<DoorEvent>,
        searchNote: String?
    ) {
        val mode = when {
            !armed -> "DISARMED"
            alarm -> "ALERT"
            else -> "ALL CLEAR"
        }
        findViewById<TextView>(R.id.statusLine).text = "${if (stationMode) "Station" else "Phone"}  |  $mode"
        val count = searchNote ?: "Events: ${list.size}"
        findViewById<TextView>(R.id.detailLine).text = "Lock: $lockState   $count"
        events.clear()
        eventModels.clear()
        eventModels.addAll(list)
        events.addAll(list.map { event ->
            val where = event.camera?.let { "  $it" }.orEmpty()
            "${event.ts}  ${event.label}$where  ${"%.2f".format(event.confidence)}"
        })
        adapter.notifyDataSetChanged()
    }
}
