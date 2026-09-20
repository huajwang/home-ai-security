package com.homeai.security.shared.notify

import java.util.concurrent.CopyOnWriteArrayList

object HubEvents {
    fun interface Listener {
        fun onHubEvent(type: String)
    }

    private val listeners = CopyOnWriteArrayList<Listener>()

    fun addListener(listener: Listener) {
        listeners.add(listener)
    }

    fun removeListener(listener: Listener) {
        listeners.remove(listener)
    }

    fun dispatch(type: String) {
        listeners.forEach { it.onHubEvent(type) }
    }
}
