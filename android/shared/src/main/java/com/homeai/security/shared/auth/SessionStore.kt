package com.homeai.security.shared.auth

import android.content.Context
import com.homeai.security.shared.model.Device
import com.homeai.security.shared.model.Home
import com.homeai.security.shared.model.Session
import com.homeai.security.shared.model.User

class SessionStore(context: Context) {
    private val prefs = context.getSharedPreferences("hub_session", Context.MODE_PRIVATE)

    var hubBaseUrl: String
        get() = prefs.getString(KEY_URL, "https://10.0.0.212:8443") ?: ""
        set(value) { prefs.edit().putString(KEY_URL, value.trimEnd('/')).apply() }

    var stationPin: String
        get() = prefs.getString(KEY_PIN, "1234") ?: "1234"
        set(value) { prefs.edit().putString(KEY_PIN, value).apply() }

    fun save(session: Session) {
        prefs.edit()
            .putString(KEY_ACCESS, session.accessToken)
            .putString(KEY_REFRESH, session.refreshToken)
            .putString(KEY_USER, session.user.username)
            .putInt(KEY_USER_ID, session.user.id)
            .putString(KEY_ROLE, session.user.role)
            .putBoolean(KEY_UNLOCK, session.user.canUnlock)
            .putString(KEY_HOME, session.home.name)
            .apply()
    }

    fun load(): Session? {
        val access = prefs.getString(KEY_ACCESS, null) ?: return null
        val refresh = prefs.getString(KEY_REFRESH, null) ?: return null
        return Session(
            accessToken = access,
            refreshToken = refresh,
            user = User(
                id = prefs.getInt(KEY_USER_ID, 0),
                username = prefs.getString(KEY_USER, "") ?: "",
                role = prefs.getString(KEY_ROLE, "member") ?: "member",
                canUnlock = prefs.getBoolean(KEY_UNLOCK, false)
            ),
            home = Home(prefs.getString(KEY_HOME, "Home") ?: "Home"),
            device = Device(0, "this", "phone")
        )
    }

    fun accessToken(): String? = prefs.getString(KEY_ACCESS, null)

    fun refreshToken(): String? = prefs.getString(KEY_REFRESH, null)

    fun clear() {
        prefs.edit().remove(KEY_ACCESS).remove(KEY_REFRESH).apply()
    }

    companion object {
        private const val KEY_URL = "hub_url"
        private const val KEY_ACCESS = "access"
        private const val KEY_REFRESH = "refresh"
        private const val KEY_USER = "user"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_ROLE = "role"
        private const val KEY_UNLOCK = "can_unlock"
        private const val KEY_HOME = "home"
        private const val KEY_PIN = "station_pin"
    }
}
