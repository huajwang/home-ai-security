package com.homeai.security.shared.ui

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.homeai.security.shared.R
import com.homeai.security.shared.api.HubClient
import com.homeai.security.shared.auth.SessionStore
import kotlin.concurrent.thread

class LoginActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = SessionStore(this)
        val client = HubClient(store)
        if (store.accessToken() != null) {
            thread {
                val ok = try {
                    client.system()
                    true
                } catch (_: Exception) {
                    client.tryRefresh()
                }
                runOnUiThread {
                    if (ok || store.accessToken() != null) {
                        startActivity(Intent(this, HomeActivity::class.java))
                        finish()
                    } else {
                        showLogin(store)
                    }
                }
            }
            return
        }
        showLogin(store)
    }

    private fun showLogin(store: SessionStore) {
        setContentView(R.layout.activity_login)
        val hubUrl = findViewById<EditText>(R.id.hubUrl)
        val username = findViewById<EditText>(R.id.username)
        val password = findViewById<EditText>(R.id.password)
        val error = findViewById<TextView>(R.id.error)
        hubUrl.setText(store.hubBaseUrl)
        username.setText("owner")

        findViewById<Button>(R.id.login).setOnClickListener {
            error.text = ""
            store.hubBaseUrl = hubUrl.text.toString()
            val client = HubClient(store)
            val role = if (packageName.endsWith(".station")) "station" else "phone"
            val deviceName = android.os.Build.MODEL ?: role
            thread {
                try {
                    client.login(
                        username.text.toString(),
                        password.text.toString(),
                        deviceName,
                        role
                    )
                    runOnUiThread {
                        startActivity(Intent(this, HomeActivity::class.java))
                        finish()
                    }
                } catch (ex: Exception) {
                    runOnUiThread { error.text = ex.message }
                }
            }
        }
    }
}
