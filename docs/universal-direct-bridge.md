# GE360 Universal Direct Bridge

Il Direct Bridge di Rilievi è ora trattato come infrastruttura GE360 condivisa.

## Obiettivo

Un solo tunnel WireGuard persistente collega il telefono al server Linux e può trasportare più backend:

```text
Android / Tablet
      |
      | WireGuard UDP 51820
      v
Linux GE360
  wg0 = 10.88.0.1/24
      |
      +-- Rilievi      TCP 9888
      +-- Preventivi   TCP 9890
      +-- Attrezzi     TCP 9891
      +-- altre app...
```

Rilievi resta completamente compatibile:

- `wg0`
- rete `10.88.0.0/24`
- server `10.88.0.1`
- UDP `51820`
- backend `http://10.88.0.1:9888`
- QR `GE360_DIRECT_BRIDGE_V1`
- token dispositivo `ge360d_...`

## Registro applicazioni

I backend collegati al tunnel vengono registrati in:

```text
/etc/ge360/direct-bridge/apps.d/
```

Rilievi viene creato automaticamente come:

```text
APP_ID=rilievi
APP_NAME=GE360 Rilievi
APP_PORT=9888
APP_SERVICE=ge360-rilievi-backend.service
APP_HEALTH_URL=http://127.0.0.1:9888/healthz
APP_ENABLED=true
```

## Aggiungere una nuova app

Esempio:

```bash
sudo APP_ID=preventivi \
APP_NAME="GE360 Preventivi" \
APP_PORT=9890 \
APP_SERVICE=ge360-preventivi-backend.service \
APP_HEALTH_URL=http://127.0.0.1:9890/healthz \
/usr/local/sbin/ge360-bridge-register-app
```

La registrazione aggiorna automaticamente il firewall e il controllo al boot.

## Persistenza

NON vengono rigenerati o cancellati durante aggiornamenti/reboot:

```text
/etc/ge360/direct-bridge/server.key
/etc/ge360/direct-bridge/server.pub
/etc/ge360/direct-bridge/bridge.env
/etc/ge360/direct-bridge/wireguard/wg0.conf
/var/lib/ge360/direct-bridge/bridge.sqlite3
```

Il database mantiene peer, device id e hash dei token dispositivo.

## Firewall

Il firewall legge tutte le app abilitate in `apps.d` e per ciascuna porta TCP consente solo:

- loopback;
- interfaccia WireGuard.

L'accesso WAN diretto alle porte applicative viene bloccato.

La sola porta pubblica prevista è WireGuard UDP 51820.

## Reboot

`ge360-boot-verify.service`:

1. verifica `wg-quick@wg0`;
2. verifica il firewall;
3. legge tutte le app registrate;
4. riavvia i relativi servizi se necessario;
5. controlla ogni health endpoint;
6. non ruota mai le chiavi.

## Migrazione dell'installazione già esistente

Rieseguire:

```bash
sudo GE360_SERVICE_USER=ge360 \
bash /opt/ge360/ge360-rilievi-backend/scripts/install-direct-bridge.sh
```

L'installer riconosce e preserva l'identità già presente. Aggiunge soltanto il registro applicazioni e registra Rilievi come prima app.

## Regola per future repository

Una nuova app GE360 non deve creare un secondo WireGuard se il core esiste già. Deve registrarsi nel Bridge condiviso indicando:

- APP_ID;
- APP_PORT;
- APP_SERVICE;
- APP_HEALTH_URL.

Questo mantiene un'unica connessione stabile tra telefono e server.
