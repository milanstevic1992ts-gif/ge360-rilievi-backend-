# Connessione frontend guidata

Il frontend GE360 deve offrire una schermata unica **Collega server GE360**.

## Esperienza desiderata

L'utente deve fare soltanto:

1. premere **Scansiona QR**;
2. inquadrare il QR mostrato dal backend;
3. accettare una volta il consenso VPN Android;
4. vedere **Server collegato**.

Tutto il resto viene letto dal QR:

- endpoint WireGuard;
- chiavi del peer;
- rete VPN;
- backend URL;
- device token;
- device id;
- app disponibili.

## Automazione

Dopo il pairing:

```text
App aperta
   |
   +-- backend LAN raggiungibile? -> usa LAN
   |
   +-- no -> tunnel GE360 attivo?
              |
              +-- no -> attivalo
              |
              +-- verifica /api/v1/health
                    |
                    +-- OK -> usa Bridge
                    +-- KO -> offline + diagnostica
```

La prima autorizzazione `VpnService` è una finestra Android obbligatoria e non è automatizzabile senza violare il modello di sicurezza del sistema.

## Modulo incluso

Vedi `frontend/android-sdk/`:

- `PairingPayload.kt`
- `BridgeProfileStore.kt`
- `Ge360Tunnel.kt`
- `Ge360BridgeClient.kt`
- `Ge360EndpointRouter.kt`

Il motore usa la libreria ufficiale WireGuard Android.
