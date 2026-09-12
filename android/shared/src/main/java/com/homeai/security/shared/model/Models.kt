package com.homeai.security.shared.model

data class User(
    val id: Int,
    val username: String,
    val role: String,
    val canUnlock: Boolean
)

data class Device(
    val id: Int,
    val deviceName: String,
    val deviceRole: String
)

data class Home(val name: String)

data class Session(
    val accessToken: String,
    val refreshToken: String,
    val user: User,
    val home: Home,
    val device: Device?
)

data class SystemStatus(
    val armed: Boolean,
    val alarmActive: Boolean,
    val visionFps: Double,
    val visionRunning: Boolean,
    val lastPersonAt: String?,
    val lockState: String,
    val lockAdapter: String,
    val hubTime: String
)

data class DoorEvent(
    val id: Int,
    val ts: String,
    val label: String,
    val confidence: Double,
    val snapshotUrl: String?
)

data class LockStatus(
    val state: String,
    val updatedAt: String,
    val adapter: String
)
