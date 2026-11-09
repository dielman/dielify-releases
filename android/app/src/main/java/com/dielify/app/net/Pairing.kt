package com.dielify.app.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// 0.9.10: signing a TV in. The TV shows a code (and a QR code holding dielify://pair/<code>);
// a parent's phone looks it up, picks whose music the TV plays and allows it (pair_api.py).

@Serializable
data class PairPerson(val name: String, val role: String, @SerialName("can_sign_in") val canSignIn: Boolean)

@Serializable
data class PairInfo(
    val code: String,
    @SerialName("device_name") val deviceName: String,
    val address: String,
    @SerialName("expires_in") val expiresIn: Int,
    val people: List<PairPerson>,
    val suggested: String? = null,
)

@Serializable
data class PairApproveIn(val person: String)

@Serializable
data class PairApproved(@SerialName("device_name") val deviceName: String, val person: String)

/** The code inside a scanned QR (dielify://pair/KDW7-RT3P) or as typed. */
fun pairCode(text: String): String = text.trim().trimEnd('/').substringAfterLast('/')
    .uppercase().filter { it.isLetterOrDigit() }.let { if (it.length == 8) it.take(4) + "-" + it.drop(4) else it }

// The TV's side: ask for a code, then check until a phone (or the PC) allows it.

@Serializable
data class PairStartIn(@SerialName("device_name") val deviceName: String)

@Serializable
data class PairStart(val secret: String, val code: String, val link: String, @SerialName("expires_in") val expiresIn: Int)

@Serializable
data class PairPollIn(val secret: String)

@Serializable
data class PairStatus(
    val status: String,                     // waiting | approved | refused | expired
    val token: String? = null,
    @SerialName("device_id") val deviceId: Int? = null,
    val username: String? = null,
    val profile: String? = null,
)
