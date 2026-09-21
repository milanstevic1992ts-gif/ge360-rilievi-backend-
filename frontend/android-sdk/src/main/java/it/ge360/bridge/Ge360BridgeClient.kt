package it.ge360.bridge

import android.content.Context
import android.content.Intent
import android.net.VpnService
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayInputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets

class Ge360BridgeClient(
    context: Context,
    private val store: BridgeProfileStore = BridgeProfileStore(context),
) {
    private val appContext = context.applicationContext
    private val backend = GoBackend(appContext)
    private val tunnel = Ge360Tunnel("ge360")

    fun importPairing(qrText: String): PairingPayload {
        val payload = PairingPayload.parse(qrText)
        store.save(payload)
        return payload
    }

    fun currentProfile(): PairingPayload? = store.load()

    /**
     * Android requires explicit user consent the first time a VPN is activated.
     * Launch the returned Intent from an Activity; when RESULT_OK is received,
     * call connect().
     */
    fun prepareVpnPermission(): Intent? = VpnService.prepare(appContext)

    suspend fun connect(): Tunnel.State = withContext(Dispatchers.IO) {
        val profile = requireNotNull(store.load()) { "Nessun profilo GE360 configurato" }
        val input = ByteArrayInputStream(
            profile.wireGuardConfig.toByteArray(StandardCharsets.UTF_8)
        )
        val config = Config.parse(input)
        backend.setState(tunnel, Tunnel.State.UP, config)
    }

    suspend fun disconnect(): Tunnel.State = withContext(Dispatchers.IO) {
        backend.setState(tunnel, Tunnel.State.DOWN, null)
    }

    suspend fun state(): Tunnel.State = withContext(Dispatchers.IO) {
        backend.getState(tunnel)
    }

    suspend fun bridgeHealth(timeoutMs: Int = 2500): Boolean = withContext(Dispatchers.IO) {
        val profile = store.load() ?: return@withContext false
        val url = URL(profile.backendUrl.trimEnd('/') + "/api/v1/health")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = timeoutMs
            readTimeout = timeoutMs
            setRequestProperty("X-GE360-API-Key", profile.apiKey)
        }
        try {
            conn.responseCode in 200..299
        } catch (_: Exception) {
            false
        } finally {
            conn.disconnect()
        }
    }

    suspend fun connectAndVerify(): Boolean {
        connect()
        return bridgeHealth()
    }
}
