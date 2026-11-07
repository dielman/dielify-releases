package com.dielify.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** The phone's sign-in to one Dielify server. */
data class Account(
    val addresses: List<String>,  // as typed, e.g. "192.168.1.249:4747", "100.73.103.100:4747"
    val username: String,
    val profile: String,
    val deviceId: Int,
    val token: String,
)

/**
 * Keeps the account on the phone. The device token is encrypted with a key held in the
 * Android Keystore (it never leaves the phone's secure hardware); the rest is plain
 * settings. App backups are switched off in the manifest.
 */
class AccountStore(context: Context) {
    private val prefs = context.getSharedPreferences("account", Context.MODE_PRIVATE)

    fun load(): Account? {
        val token = prefs.getString(TOKEN, null)?.let { runCatching { decrypt(it) }.getOrNull() }
            ?: return null
        return Account(
            addresses = lastAddresses(),
            username = prefs.getString(USER, "") ?: "",
            profile = prefs.getString(PROFILE, "") ?: "",
            deviceId = prefs.getInt(DEVICE, 0),
            token = token,
        )
    }

    fun save(account: Account) {
        prefs.edit()
            .putString(ADDRESSES, account.addresses.joinToString("\n"))
            .putString(USER, account.username)
            .putString(PROFILE, account.profile)
            .putInt(DEVICE, account.deviceId)
            .putString(TOKEN, encrypt(account.token))
            .apply()
    }

    /** Sign out: forget the token, keep the addresses and user name for next time. */
    fun clearToken() {
        prefs.edit().remove(TOKEN).remove(DEVICE).remove(PROFILE).apply()
    }

    fun lastAddresses(): List<String> =
        prefs.getString(ADDRESSES, null)?.split("\n")?.filter { it.isNotBlank() } ?: emptyList()

    fun lastUsername(): String = prefs.getString(USER, "") ?: ""

    // --- Keystore encryption (AES-256-GCM) ---------------------------------------------

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return gen.generateKey()
    }

    private fun encrypt(text: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val out = cipher.iv + cipher.doFinal(text.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(out, Base64.NO_WRAP)
    }

    private fun decrypt(stored: String): String {
        val raw = Base64.decode(stored, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw, 0, IV_BYTES))
        return String(cipher.doFinal(raw, IV_BYTES, raw.size - IV_BYTES), Charsets.UTF_8)
    }

    private companion object {
        const val KEY_ALIAS = "dielify-device-token"
        const val IV_BYTES = 12
        const val TOKEN = "token"
        const val ADDRESSES = "addresses"
        const val USER = "username"
        const val PROFILE = "profile"
        const val DEVICE = "device_id"
    }
}
