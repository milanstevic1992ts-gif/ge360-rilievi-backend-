# Installazione guidata GE360 Universal Bridge

## Obiettivo

L'installazione deve richiedere il minimo possibile all'utente.

Dal menu applicazioni:

```text
GE360 Universal Bridge
```

si apre un terminale con il wizard.

In alternativa:

```bash
sudo ge360-bridge-wizard
```

## Cosa fa automaticamente

1. installa WireGuard, nftables, miniupnpc e dipendenze;
2. crea/preserva l'identità WireGuard;
3. crea/preserva `wg0`;
4. rileva LAN IPv4;
5. cerca IPv6 pubblico globale;
6. cerca IPv4 WAN tramite router UPnP;
7. distingue IPv4 pubblico, NAT e CGNAT;
8. prova a creare il port mapping UDP WireGuard quando il router supporta UPnP;
9. salva l'endpoint in `bridge.env`;
10. abilita firewall e servizi systemd;
11. registra i backend;
12. verifica healthcheck e WireGuard;
13. mantiene tutto operativo dopo reboot.

Lo stato rete è salvato in:

```text
/var/lib/ge360/direct-bridge/state/network.json
```

## IP pubblico

Il wizard può configurare automaticamente ciò che è tecnicamente disponibile.

### IPv6 pubblico

Se trova un IPv6 globale stabile, lo usa come `GE360_PUBLIC_HOST`.

### IPv4 pubblico

Se il router espone un IPv4 pubblico, prova UPnP:

```text
UDP 51820 -> server GE360
```

### CGNAT

Se l'operatore assegna solo CGNAT e non è presente IPv6 pubblico raggiungibile, il wizard segnala:

```text
BLOCKED_CGNAT
```

In questo caso nessun software installato sul server può creare autonomamente un indirizzo pubblico. Serve un IPv4 pubblico dall'operatore oppure IPv6 raggiungibile.

## Frontend

Dopo aver registrato un backend:

```bash
sudo ge360-bridge-export-frontend rilievi
```

viene creato un pacchetto specifico per il frontend con:

- Android SDK GE360 Bridge;
- profilo backend;
- istruzioni;
- routing LAN → Bridge → offline.

Il pairing effettivo resta per-device e avviene tramite QR.
