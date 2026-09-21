# GE360 Universal Bridge — Android SDK

Questo modulo è il lato frontend del GE360 Universal Bridge.

## Flusso utente

1. Apri **Impostazioni → Collega server GE360**.
2. Scansiona il QR `GE360_DIRECT_BRIDGE_V1`.
3. `PairingPayload.parse()` valida il QR.
4. `Ge360BridgeClient.importPairing()` salva profilo, token dispositivo e configurazione WireGuard.
5. Alla prima connessione Android mostra il consenso VPN obbligatorio di sistema.
6. Dopo il consenso, `connectAndVerify()` attiva WireGuard e verifica il backend.
7. `Ge360EndpointRouter` usa la priorità:
   - LAN;
   - GE360 Bridge;
   - offline.

## Dipendenza WireGuard

Usare il tunnel ufficiale WireGuard Android:

```kotlin
implementation("com.wireguard.android:tunnel:1.0.20260102")
```

La libreria espone `GoBackend`, `Tunnel` e `Config.parse`.

## Integrazione Activity

Pseudo-flusso:

```kotlin
val payload = bridgeClient.importPairing(scannedQr)

val permissionIntent = bridgeClient.prepareVpnPermission()
if (permissionIntent != null) {
    vpnPermissionLauncher.launch(permissionIntent)
} else {
    lifecycleScope.launch {
        val ok = bridgeClient.connectAndVerify()
    }
}
```

Quando il launcher VPN restituisce `RESULT_OK`, chiamare `connectAndVerify()`.

Il consenso VPN Android non può e non deve essere bypassato: compare solo quando necessario.

## Sicurezza

- Il QR contiene una chiave dispositivo revocabile, non la master key.
- La private key WireGuard del telefono resta nel profilo locale del dispositivo.
- Il tunnel usa `AllowedIPs = 10.88.0.0/24`: non instrada tutto Internet.
- L'HTTP applicativo viaggia dentro WireGuard; per questo il manifest deve consentire l'HTTP privato GE360 finché il backend non passa a HTTPS interno.
