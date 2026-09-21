# GE360 Rilievi Backend — reinstallazione e ripristino Linux

Questa è la procedura verificata per reinstallare GE360 Rilievi Backend su Debian mantenendo la configurazione stabile usata sul server JARVIS.

## Architettura finale

- Backend GE360: TCP 9888
- WireGuard: UDP 51820
- Interfaccia VPN: wg0
- Rete VPN: 10.88.0.0/24
- Server VPN: 10.88.0.1
- Backend raggiungibile dai client VPN: http://10.88.0.1:9888
- Utente di servizio: ge360
- Config backend: /etc/ge360-rilievi-backend/ge360.env
- Config Direct Bridge: /etc/ge360/direct-bridge/bridge.env
- Dati persistenti: /opt/ge360/data/rilievi
- Stato Direct Bridge: /var/lib/ge360/direct-bridge

## 1. Installazione del pacchetto Debian

```bash
cd ~/Scaricati
sudo apt install ./ge360-rilievi-backend_1.5.1_all.deb
```

Se una vecchia installazione è rimasta incompleta:

```bash
sudo dpkg --configure -a
sudo apt --fix-broken install
sudo apt install ./ge360-rilievi-backend_1.5.1_all.deb
```

## 2. Compatibilità CPU

Il server JARVIS usa una CPU AMD Phenom II. Versioni recenti di NumPy possono terminare con SIGILL/Illegal instruction.

Usare:

```text
numpy>=2.2,<2.4
scipy>=1.15,<1.17
```

Versioni verificate:

```text
numpy 2.3.3
scipy 1.16.3
```

## 3. Configurazione backend

Verificare:

```bash
sudo ls -l /etc/ge360-rilievi-backend/ge360.env
sudo ls -l /opt/ge360/data/rilievi/.api-key
```

Il preflight NON deve eseguire il file .env con `source`, perché valori con spazi come il nome aziendale possono essere interpretati come comandi shell.

Esempio valido:

```text
GE360_BRAND_NAME="EDIL MILAN STEVIC"
GE360_BRAND_SUBTITLE="Restauri & Costruzioni · Trieste e provincia"
GE360_BRAND_TAGLINE="Un artigiano, un unico referente"
```

## 4. Installazione GE360 Direct Bridge

```bash
sudo GE360_SERVICE_USER=ge360 \
bash /opt/ge360/ge360-rilievi-backend/scripts/install-direct-bridge.sh
```

Verificare:

```bash
sudo wg show
sudo systemctl status wg-quick@wg0 --no-pager -l
```

Atteso:

```text
interface: wg0
listening port: 51820
```

e:

```text
10.88.0.1/24
```

## 5. Rete con CGNAT + IPv6 pubblico

Nel caso verificato, l'IPv4 WAN era privato/CGNAT:

```text
10.167.70.225
```

Quindi l'accesso remoto IPv4 diretto non è utilizzabile.

È presente IPv6 pubblico globale. GE360 deve usare l'IPv6 pubblico stabile del server come endpoint WireGuard.

Controllare gli IPv6:

```bash
ip -6 addr show scope global
```

Preferire l'indirizzo globale non temporary/deprecated.

Configurare:

```bash
sudo nano /etc/ge360/direct-bridge/bridge.env
```

Impostare:

```text
GE360_BRIDGE_ENABLED=true
GE360_BRIDGE_INTERFACE=wg0
GE360_BRIDGE_NETWORK=10.88.0.0/24
GE360_BRIDGE_SERVER_IP=10.88.0.1
GE360_BRIDGE_PORT=51820
GE360_BRIDGE_KEEPALIVE=25
GE360_PUBLIC_HOST=<IPV6_PUBBLICO_STABILE>
GE360_BRIDGE_CONFIG_DIR=/etc/ge360/direct-bridge
GE360_BRIDGE_STATE_DIR=/var/lib/ge360/direct-bridge
GE360_BRIDGE_WG_CONFIG=/etc/ge360/direct-bridge/wireguard/wg0.conf
GE360_BRIDGE_AUTO_PORT_MAPPING=false
```

Con IPv6 non serve UPnP/port forwarding IPv4. Il firewall/router deve consentire UDP 51820 verso il server.

## 6. Riavvio servizi

```bash
sudo systemctl restart ge360-direct-bridge-firewall
sudo systemctl restart wg-quick@wg0
sudo systemctl restart ge360-rilievi-backend
```

Poi:

```bash
sudo wg show
ge360-rilievi-status
```

Atteso:

```text
Active: active (running)
```

Healthcheck:

```bash
curl http://127.0.0.1:9888/healthz
```

Atteso:

```json
{"ok":true,"service":"ge360-rilievi-backend"}
```

## 7. Pairing frontend Android

Aprire:

```text
http://127.0.0.1:9888/setup/
```

Inserire un nome dispositivo e premere COLLEGA DISPOSITIVO.

Il QR GE360 contiene:

- configurazione WireGuard del dispositivo
- endpoint pubblico WireGuard
- backend_url http://10.88.0.1:9888
- token applicativo dedicato e revocabile
- device_id

La master API key NON viene inserita nel QR.

## 8. Diagnostica

```bash
ge360-rilievi-status
sudo ge360-rilievi-diagnose
sudo journalctl -u ge360-rilievi-backend -n 100 --no-pager
sudo journalctl -u wg-quick@wg0 -n 100 --no-pager
sudo wg show
```

## 9. Dati da preservare prima di una reinstallazione completa

Fare backup di:

```bash
sudo tar -czf ~/ge360-backup-$(date +%Y%m%d).tar.gz \
  /etc/ge360-rilievi-backend \
  /etc/ge360/direct-bridge \
  /opt/ge360/data/rilievi \
  /var/lib/ge360/direct-bridge
```

Questi percorsi contengono configurazione, API key, identità WireGuard, database dispositivi e stato del bridge.

## 10. Regola importante

Non esporre direttamente TCP 9888 sul router.

L'accesso remoto deve essere:

```text
Frontend Android
      |
      | WireGuard UDP 51820
      v
wg0 / 10.88.0.1
      |
      v
GE360 Backend TCP 9888
```


## 11. Persistenza dopo riavvio del server

GE360 deve ripartire automaticamente senza perdere pairing o configurazioni.

Servizi abilitati al boot:

```bash
sudo systemctl enable ge360-rilievi-backend
sudo systemctl enable wg-quick@wg0
sudo systemctl enable ge360-direct-bridge-firewall
sudo systemctl enable ge360-boot-verify
```

Verifica:

```bash
systemctl is-enabled ge360-rilievi-backend
systemctl is-enabled wg-quick@wg0
systemctl is-enabled ge360-direct-bridge-firewall
systemctl is-enabled ge360-boot-verify
```

Devono risultare `enabled`.

Dopo ogni boot, `ge360-boot-verify.service` controlla che WireGuard, firewall e backend siano attivi e prova a riavviarli se necessario.

Il riavvio NON deve rigenerare:

- server.key / server.pub WireGuard
- API key GE360
- database dispositivi Direct Bridge
- indirizzi VPN assegnati
- configurazione bridge.env
- configurazione backend ge360.env

I dati persistenti restano in:

```text
/etc/ge360-rilievi-backend/
/etc/ge360/direct-bridge/
/opt/ge360/data/rilievi/
/var/lib/ge360/direct-bridge/
```

Dopo un riavvio controllare:

```bash
sudo wg show
ge360-rilievi-status
curl http://127.0.0.1:9888/healthz
```
