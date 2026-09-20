# GE360 DIRECT BRIDGE

GE360 DIRECT BRIDGE è il collegamento remoto nativo del backend GE360 Rilievi. **WireGuard è il tunnel**; GE360 gestisce soltanto configurazione, peer, QR, stato, diagnostica, revoca e persistenza.

Non dipende da Tailscale, Cloudflare Tunnel, FRP, ngrok, ZeroTier, VPS o relay proprietari.

## Architettura

```text
Android GE360
    |
    | WireGuard UDP 51820
    v
Linux GE360
  wg0 = 10.88.0.1/24
    |
    +-- GE360 Backend TCP 9888

Telefono 1 = 10.88.0.2/32
Tablet     = 10.88.0.3/32
...
```

Il backend resta sulla porta applicativa **9888**. L'installer aggiunge un drop-in systemd che consente al backend di ascoltare su LAN/WireGuard e una tabella nftables dedicata che blocca TCP 9888 da sorgenti WAN pubbliche. Sul router **non va mai inoltrata TCP 9888**.

## Installazione Debian

Dalla root della repository:

```bash
sudo bash scripts/install-direct-bridge.sh
```

Lo script è idempotente e:

- installa `wireguard-tools`, `nftables` e `miniupnpc` se mancanti;
- crea il gruppo ristretto `ge360-bridge`;
- crea `/etc/ge360/direct-bridge` e `/var/lib/ge360/direct-bridge`;
- genera la server key solo se non esiste;
- crea `/etc/wireguard/wg0.conf` solo se non esiste;
- rifiuta di sovrascrivere un `wg0.conf` non marcato come gestito da GE360;
- abilita `wg-quick@wg0.service`;
- installa la guardia nftables per la porta 9888;
- aggiunge al servizio FastAPI solo `CAP_NET_ADMIN` e accesso alle directory Bridge;
- non cancella dispositivi o identità esistenti.

Verifica:

```bash
sudo systemctl status wg-quick@wg0
sudo wg show wg0
sudo systemctl status ge360-rilievi-backend
curl http://127.0.0.1:9888/healthz
```

Apri localmente:

```text
http://127.0.0.1:9888/setup/
```

## Persistenza e segreti

Configurazione:

```text
/etc/ge360/direct-bridge/
  bridge.env
  server.key
  server.pub
  wireguard/
    wg0.conf

/etc/wireguard/
  wg0.conf -> /etc/ge360/direct-bridge/wireguard/wg0.conf
```

Stato:

```text
/var/lib/ge360/direct-bridge/
  bridge.sqlite3
  backups/
  qr/
  state/
```

La private key del server non entra mai in Git. L'identità server non viene rigenerata durante pull, reboot, reinstallazione Python, restart FastAPI o build Android.

Ogni Android usa una chiave WireGuard diversa. La private key del dispositivo viene generata durante il pairing, inserita nella configurazione/QR restituita e **non viene salvata nel database**. Per questo il QR è disponibile una sola volta. `GET /api/v1/bridge/devices/{id}/qr` restituisce HTTP 410 dopo il pairing.

## Configurazione

Il file persistente è `/etc/ge360/direct-bridge/bridge.env`.

Valori predefiniti:

```text
GE360_BRIDGE_ENABLED=true
GE360_BRIDGE_INTERFACE=wg0
GE360_BRIDGE_NETWORK=10.88.0.0/24
GE360_BRIDGE_SERVER_IP=10.88.0.1
GE360_BRIDGE_PORT=51820
GE360_BRIDGE_KEEPALIVE=25
GE360_PUBLIC_HOST=
GE360_BRIDGE_WG_CONFIG=/etc/ge360/direct-bridge/wireguard/wg0.conf
GE360_BRIDGE_AUTO_PORT_MAPPING=false
```

Se hai IP pubblico o DNS/DDNS stabile, imposta ad esempio:

```text
GE360_PUBLIC_HOST=vpn.example.it
```

Poi:

```bash
sudo systemctl restart ge360-rilievi-backend
```

## Router, NAT e CGNAT

La sola porta da inoltrare sul router è:

```text
UDP 51820 -> server GE360
```

`GE360_BRIDGE_AUTO_PORT_MAPPING=true` abilita il tentativo opzionale UPnP IGD. Il backend rileva anche se gli strumenti NAT-PMP/PCP sono disponibili, ma non richiede servizi cloud.

La diagnostica distingue:

- IPv4 pubblico rilevato;
- IPv6 pubblico rilevato;
- NAT;
- possibile CGNAT/non-public WAN;
- endpoint non determinabile.

Se il router espone un indirizzo WAN nella rete `100.64.0.0/10` o comunque non pubblico, l'API restituisce:

```text
REMOTE_ACCESS_UNAVAILABLE_CGNAT
```

con il messaggio:

> La rete non consente connessioni dirette in ingresso. È necessario un IP pubblico, IPv6 raggiungibile o un relay esterno.

GE360 non finge che la connessione diretta funzioni. Il backend locale continua a funzionare.

## API

Tutte le API Bridge usano la stessa protezione amministrativa già presente nel backend: localhost diretto oppure `X-GE360-API-Key` valida.

```text
GET    /api/v1/bridge/status
POST   /api/v1/bridge/devices
GET    /api/v1/bridge/devices
GET    /api/v1/bridge/devices/{id}
DELETE /api/v1/bridge/devices/{id}
POST   /api/v1/bridge/devices/{id}/revoke
GET    /api/v1/bridge/devices/{id}/qr
POST   /api/v1/bridge/restart
GET    /api/v1/bridge/diagnostics
```

Creazione dispositivo:

```json
{"name":"Telefono Milan"}
```

La risposta contiene il record pubblico del dispositivo e `pairing` con:

- configurazione WireGuard completa;
- QR PNG base64 one-shot;
- endpoint WireGuard;
- backend GE360 `http://10.88.0.1:9888`.

Lo stato espone inoltre conteggio peer, ultimo handshake disponibile e traffico RX/TX aggregato.

## Android

Usare il motore ufficiale WireGuard per Android, modulo `com.wireguard.android:tunnel`, seguendo la versione supportata dal progetto Android al momento della build.

Flusso consigliato:

1. Impostazioni → **Collega server GE360**.
2. Apri scanner QR.
3. Importa la configurazione WireGuard.
4. Crea/attiva il tunnel tramite la libreria WireGuard.
5. Verifica `http://10.88.0.1:9888/api/v1/health` con `X-GE360-API-Key`.
6. Salva il profilo server.
7. Riconnetti il tunnel quando l'app deve usare il backend fuori LAN.

Priorità frontend:

```text
1. backend LAN
2. WireGuard -> http://10.88.0.1:9888
3. offline
```

Il tunnel usa `AllowedIPs = 10.88.0.0/24`, quindi non dirotta tutto il traffico Internet del telefono.

## Test manuale reale

1. `sudo bash scripts/install-direct-bridge.sh`
2. Apri `http://127.0.0.1:9888/setup/`.
3. Premi **+ COLLEGA DISPOSITIVO**.
4. Scansiona il QR sul telefono.
5. Attiva WireGuard e verifica handshake con `sudo wg show wg0`.
6. Dal telefono verifica `http://10.88.0.1:9888`.
7. Disattiva il tunnel.
8. Riattivalo e verifica una nuova connessione.
9. Riavvia il server Linux.
10. Verifica che `wg0`, la server public key e il dispositivo registrato siano rimasti invariati.

## Test automatici

```bash
pytest -q tests/test_direct_bridge.py
bash -n scripts/install-direct-bridge.sh
bash -n scripts/direct-bridge-firewall.sh
```

La CI esegue anche l'intera suite backend e lo smoke HTTP esistente.

## Rollback

Per disattivare il Bridge senza cancellare identità o dispositivi:

```bash
sudo systemctl disable --now wg-quick@wg0
sudo systemctl disable --now ge360-direct-bridge-firewall.service
sudo rm -f /etc/systemd/system/ge360-rilievi-backend.service.d/direct-bridge.conf
sudo systemctl daemon-reload
sudo systemctl restart ge360-rilievi-backend
```

Questo lascia intatti:

```text
/etc/ge360/direct-bridge
/var/lib/ge360/direct-bridge
/etc/ge360/direct-bridge/wireguard/wg0.conf
/etc/wireguard/wg0.conf (symlink)
```

Per riattivarlo basta rieseguire l'installer. La cancellazione permanente di chiavi/dispositivi deve essere un'azione manuale esplicita, mai parte di un aggiornamento.

## Limiti

GE360 Direct Bridge è pensato per l'installazione Debian/systemd nativa. Il `docker-compose.yml` continua intenzionalmente a pubblicare 9888 soltanto su loopback e non configura WireGuard nell'host.

Il Bridge è indipendente da solver geometrico, CAD, Qwen e Ollama. Qwen3:8b non configura e non modifica WireGuard.
