package com.homeai.security.shared.ui

import android.widget.EditText
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.homeai.security.shared.auth.SessionStore

object UnlockHelper {
    fun confirm(
        activity: FragmentActivity,
        store: SessionStore,
        preferBiometric: Boolean,
        onConfirmed: () -> Unit
    ) {
        if (preferBiometric && canUseBiometric(activity)) {
            val prompt = BiometricPrompt(
                activity,
                ContextCompat.getMainExecutor(activity),
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                        onConfirmed()
                    }
                }
            )
            prompt.authenticate(
                BiometricPrompt.PromptInfo.Builder()
                    .setTitle("Unlock door")
                    .setSubtitle("Confirm it is you")
                    .setNegativeButtonText("Cancel")
                    .build()
            )
            return
        }

        val input = EditText(activity).apply {
            hint = "Station PIN"
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or
                android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD
        }
        MaterialAlertDialogBuilder(activity)
            .setTitle("Unlock door?")
            .setMessage("This sends a confirmed unlock to the hub lock adapter.")
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Unlock") { _, _ ->
                val pin = input.text.toString()
                if (pin == store.stationPin) {
                    onConfirmed()
                } else {
                    MaterialAlertDialogBuilder(activity)
                        .setMessage("PIN did not match.")
                        .setPositiveButton("OK", null)
                        .show()
                }
            }
            .show()
    }

    private fun canUseBiometric(activity: FragmentActivity): Boolean {
        val manager = BiometricManager.from(activity)
        return manager.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK) ==
            BiometricManager.BIOMETRIC_SUCCESS
    }
}
