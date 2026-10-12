package com.homeai.security.shared.api

import okhttp3.OkHttpClient
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * Prototype TLS: trust the hub's self-signed / mkcert / Tailscale Let's Encrypt cert
 * so LAN and remote signaling works without requiring manual CA installation.
 */
object HubTls {
    private val systemTrustManager: X509TrustManager? = try {
        val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        factory.init(null as java.security.KeyStore?)
        factory.trustManagers.filterIsInstance<X509TrustManager>().firstOrNull()
    } catch (_: Exception) {
        null
    }

    private val trustManager = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}

        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            if (chain.isEmpty()) {
                throw java.security.cert.CertificateException("empty certificate chain")
            }
            try {
                systemTrustManager?.checkServerTrusted(chain, authType)
                return
            } catch (_: Exception) {
                // Fall back to prototype cert name matching below
            }
            val subject = chain[0].subjectX500Principal.name.lowercase()
            val issuer = chain[0].issuerX500Principal.name.lowercase()
            val ok = listOf(
                "home-ai-security-hub",
                "mkcert",
                "home ai security",
                "let's encrypt",
                "tailscale",
                ".ts.net",
                "rock-5t"
            ).any {
                it in subject || it in issuer
            }
            if (!ok) {
                throw java.security.cert.CertificateException("unexpected hub certificate: $subject")
            }
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> =
            systemTrustManager?.acceptedIssuers ?: emptyArray()
    }

    private val socketFactory = SSLContext.getInstance("TLS").apply {
        init(null, arrayOf(trustManager), SecureRandom())
    }.socketFactory

    fun apply(builder: OkHttpClient.Builder): OkHttpClient.Builder {
        return builder
            .sslSocketFactory(socketFactory, trustManager)
            .hostnameVerifier { _, _ -> true }
    }
}
