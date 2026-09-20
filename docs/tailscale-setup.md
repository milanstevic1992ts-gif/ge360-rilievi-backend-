# Collegamento GE360 tramite Tailscale

GE360 Rilievi mantiene Uvicorn su `127.0.0.1:8796` e usa Tailscale Serve come reverse proxy HTTPS privato verso il tailnet.

Questa scelta evita di esporre direttamente Uvicorn sulla LAN.

## Setup rapido

Sul server Debian:

```bash
sudo bash scripts/setup-tailscale.sh
```

Lo script:
1. verifica che Tailscale sia installato e connesso;
2. crea una API key GE360 se non esiste;
3. la salva fuori dal repository in `/opt/ge360/data/rilievi/.api-key` con permessi 0600;
4. configura Tailscale Serve verso `http://127.0.0.1:8796`;
5. stampa il Backend URL e la API key da copiare nel frontend.

Esempio risultato:

```text
Backend URL : https://nome-macchina.tailnet.ts.net/api/v1
API key     : <chiave-generata>
```

## Pagina impostazioni locale

Aprire sul server:

```text
http://127.0.0.1:8796/setup/
```

La pagina mostra:
- stato backend;
- Tailscale installato/connesso;
- MagicDNS;
- stato Tailscale Serve;
- URL pronto per il frontend;
- generazione/rotazione API key.

La generazione della chiave senza autenticazione è consentita soltanto con accesso diretto localhost. Da un host remoto occorre una API key valida.

## Runtime API key

Ordine di priorità:
1. file `GE360_API_KEY_FILE` se configurato;
2. default `<GE360_DATA_DIR>/.api-key`;
3. fallback a `GE360_API_KEY` / `GE360_RILIEVO_API_KEY`.

Questo consente alla pagina setup di generare una chiave valida immediatamente senza riavviare Uvicorn.

## Frontend

Nel frontend GE360 Open Plan3D:

```text
serverUrl = https://<MagicDNS>.ts.net/api/v1
apiKey    = <chiave GE360>
```

Il frontend può poi usare:
- `/health`
- `/plans/refine`
- gli URL restituiti dal backend.

Non usare Tailscale Funnel per questo flusso: GE360 deve restare privato nel tailnet.
