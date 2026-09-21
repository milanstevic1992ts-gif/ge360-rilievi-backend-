# Pacchetto Debian GE360 Rilievi Backend

Il repository genera un vero pacchetto `.deb` installabile su Debian/Ubuntu compatibili.

## Build

```bash
sudo apt install -y dpkg-dev rsync
bash scripts/build-deb.sh
```

Il file viene creato in `dist/`, per esempio:

```text
dist/ge360-rilievi-backend_1.5.0_all.deb
```

## Installazione

```bash
sudo apt install ./dist/ge360-rilievi-backend_1.5.0_all.deb
```

Durante la prima configurazione il pacchetto:

- crea l'utente di servizio `ge360`;
- installa il backend in `/opt/ge360/ge360-rilievi-backend`;
- crea il virtualenv e installa `requirements.txt`;
- crea `/etc/ge360-rilievi-backend/ge360.env` senza sovrascriverlo agli aggiornamenti;
- crea `/opt/ge360/data/rilievi/.api-key` se manca;
- installa e abilita `ge360-rilievi-backend.service`;
- mantiene il backend locale su `127.0.0.1:9888`.

La prima installazione richiede accesso a Internet per scaricare le dipendenze Python nel virtualenv.

## Verifica

```bash
systemctl status ge360-rilievi-backend --no-pager
curl http://127.0.0.1:9888/healthz
```

Pannello locale:

```text
http://127.0.0.1:9888/control/
```

Configurazione:

```text
/etc/ge360-rilievi-backend/ge360.env
```

## GE360 Direct Bridge

Il bridge non viene esposto automaticamente dal solo pacchetto. Dopo avere verificato il backend locale:

```bash
sudo GE360_SERVICE_USER=ge360 /opt/ge360/ge360-rilievi-backend/scripts/install-direct-bridge.sh
```

Il backend rimane quindi protetto dalle regole WireGuard/nftables già previste dal progetto.

## Aggiornamento

Costruire una versione successiva e installarla con `apt install ./nuovo-pacchetto.deb`.
Configurazione, API key e dati vengono preservati.

## Rimozione

```bash
sudo apt remove ge360-rilievi-backend
```

I dati e la configurazione vengono lasciati intenzionalmente sul disco per evitare perdite accidentali.
