package it.ge360.bridge

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

class BridgeProfileStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(
        "ge360_universal_bridge",
        Context.MODE_PRIVATE,
    )

    fun save(payload: PairingPayload) {
        val apps = JSONArray()
        payload.apps.forEach {
            apps.put(
                JSONObject()
                    .put("app_id", it.appId)
                    .put("name", it.name)
                    .put("backend_url", it.backendUrl)
                    .put("port", it.port)
            )
        }

        val json = JSONObject()
            .put("format", payload.format)
            .put("version", payload.version)
            .put("device_id", payload.deviceId)
            .put("backend_url", payload.backendUrl)
            .put("api_key", payload.apiKey)
            .put("app_id", payload.appId)
            .put("apps", apps)
            .put(
                "pairing",
                JSONObject()
                    .put("wireguard_config", payload.wireGuardConfig)
                    .put("backend_url", payload.backendUrl)
            )

        prefs.edit().putString("profile", json.toString()).apply()
    }

    fun load(): PairingPayload? {
        val raw = prefs.getString("profile", null) ?: return null
        return runCatching { PairingPayload.parse(raw) }.getOrNull()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }
}
