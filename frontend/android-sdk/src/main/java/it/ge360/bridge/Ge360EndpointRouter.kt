package it.ge360.bridge

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

class Ge360EndpointRouter(
    private val bridgeClient: Ge360BridgeClient,
) {
    enum class Route { LAN, BRIDGE, OFFLINE }

    data class Result(val route: Route, val baseUrl: String?)

    suspend fun resolve(
        lanCandidates: List<String>,
        apiKey: String?,
        timeoutMs: Int = 900,
    ): Result {
        for (candidate in lanCandidates) {
            if (probe(candidate, apiKey, timeoutMs)) {
                return Result(Route.LAN, candidate.trimEnd('/'))
            }
        }

        val profile = bridgeClient.currentProfile()
        if (profile != null) {
            val permission = bridgeClient.prepareVpnPermission()
            if (permission == null) {
                runCatching { bridgeClient.connect() }
                if (bridgeClient.bridgeHealth(timeoutMs.coerceAtLeast(1500))) {
                    return Result(Route.BRIDGE, profile.backendUrl.trimEnd('/'))
                }
            }
        }

        return Result(Route.OFFLINE, null)
    }

    private suspend fun probe(base: String, apiKey: String?, timeoutMs: Int): Boolean =
        withContext(Dispatchers.IO) {
            val conn = runCatching {
                (URL(base.trimEnd('/') + "/api/v1/health").openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = timeoutMs
                    readTimeout = timeoutMs
                    if (!apiKey.isNullOrBlank()) {
                        setRequestProperty("X-GE360-API-Key", apiKey)
                    }
                }
            }.getOrNull() ?: return@withContext false

            try {
                conn.responseCode in 200..299
            } catch (_: Exception) {
                false
            } finally {
                conn.disconnect()
            }
        }
}
