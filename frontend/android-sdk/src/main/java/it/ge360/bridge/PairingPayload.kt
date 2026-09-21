package it.ge360.bridge

import org.json.JSONObject

data class BridgeApp(
    val appId: String,
    val name: String,
    val backendUrl: String,
    val port: Int,
)

data class PairingPayload(
    val format: String,
    val version: Int,
    val deviceId: String,
    val backendUrl: String,
    val apiKey: String,
    val wireGuardConfig: String,
    val appId: String?,
    val apps: List<BridgeApp>,
) {
    companion object {
        const val FORMAT = "GE360_DIRECT_BRIDGE_V1"

        fun parse(raw: String): PairingPayload {
            val json = JSONObject(raw)
            val format = json.getString("format")
            require(format == FORMAT) { "Formato QR GE360 non supportato: $format" }

            val version = json.optInt("version", 1)
            require(version == 1) { "Versione QR GE360 non supportata: $version" }

            val pairing = json.getJSONObject("pairing")
            val appsJson = json.optJSONArray("apps")
            val apps = buildList {
                if (appsJson != null) {
                    for (i in 0 until appsJson.length()) {
                        val row = appsJson.getJSONObject(i)
                        add(
                            BridgeApp(
                                appId = row.getString("app_id"),
                                name = row.optString("name", row.getString("app_id")),
                                backendUrl = row.getString("backend_url"),
                                port = row.optInt("port", 0),
                            )
                        )
                    }
                }
            }

            return PairingPayload(
                format = format,
                version = version,
                deviceId = json.getString("device_id"),
                backendUrl = json.getString("backend_url"),
                apiKey = json.getString("api_key"),
                wireGuardConfig = pairing.getString("wireguard_config"),
                appId = json.optString("app_id").takeIf { it.isNotBlank() },
                apps = apps,
            )
        }
    }
}
