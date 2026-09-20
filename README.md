# GE360 Rilievi Backend

Backend Python/FastAPI per trasformare il rilievo rapido di `ge360-open-plan3d` in una geometria metrica verificabile e in elaborati tecnici versionati.

Regola centrale: **le misure dichiarate dall'utente sono autorevoli**. Il backend può correggere topologia, piccoli gap e vincoli geometrici, ma non modifica `declaredLengthMm`, larghezze/offset delle aperture o altre misure utente per forzare la chiusura.

## Stato V1 sulla branch `feature/deterministic-pipeline-v1`

Implementato e coperto da test:

- payload frontend v4 e compatibilità `POST /api/v1/plans/refine`;
- RAW originale immutabile più snapshot successivi;
- SQLite per stato e indice;
- stati `RAW`, `QUEUED`, `PROCESSING`, `PROCESSED`, `NEEDS_REVIEW`, `ERROR`;
- worker interno `ThreadPoolExecutor` con deduplica per `planId`;
- normalizzazione mm, topologia NetworkX, solver SciPy, stanze Shapely;
- agente Ollama **opzionale**, solo tool calling, massimo 5 iterazioni, validation/rollback;
- fallback completo quando Ollama non è disponibile;
- output reali `processed-plan.json`, `plan.dxf`, `plan.svg`, `preview.png`, `plan.pdf`, `plan3d.json`;
- versioni `001`, `002`, ... e accesso ai vecchi elaborati;
- API key opzionale in sviluppo e obbligatoria quando `GE360_API_KEY` è valorizzata;
- CORS configurabile via ENV;
- viewer Three.js minimale su `/viewer3d/` con orbit, pan, zoom, top, perspective e reset;
- adapter opzionali per archit-app/openPlan3D; ArchLang è esplicitamente `NOT_USED_V1`;
- systemd, Docker e CI GitHub Actions.

**Non inclusi nel percorso V1:** Telegram e generazione GLB. `GET /api/v1/plans/{planId}/glb` restituisce 404 intenzionalmente. `plan3d.json` è il formato 3D autorevole per questa fase.

## Flusso frontend

```text
GE360 OPEN PLAN3D
  -> POST /api/v1/plans
  -> POST /api/v1/plans/{planId}/process
  -> QUEUED + jobId
  -> polling job/status
  -> solver/validator/export
  -> current + versions/NNN
  -> 2D / 3D / PDF / DXF / PNG / SVG / JSON
```

Contratto completo: `docs/frontend-api.md`.

## Avvio locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
set -a
source .env
set +a
uvicorn backend.main:app --host 127.0.0.1 --port 8796
```

Con `GE360_API_KEY=` vuoto l'API parte in modalità sviluppo e registra un warning. In installazione reale impostare una chiave, per esempio:

```bash
openssl rand -hex 32
```

## Installazione Debian/systemd

```bash
sudo bash scripts/install-debian.sh
sudo nano /opt/ge360/ge360-rilievi-backend/.env
sudo systemctl enable --now ge360-rilievi-backend.service
sudo systemctl status ge360-rilievi-backend.service
```

Il template systemd usa `User=jarvis`, bind `127.0.0.1:8796` e storage `/opt/ge360/data/rilievi`. Se l'host usa un altro utente, adattare l'unit prima dell'avvio.

## Docker

```bash
cp .env.example .env
docker compose up -d --build
```

La porta viene pubblicata solo su `127.0.0.1:8796` e i dati persistono in `./local-data`.

## ENV principali

```text
GE360_API_KEY=
GE360_DATA_DIR=/opt/ge360/data/rilievi
GE360_DB_PATH=/opt/ge360/data/rilievi/ge360-rilievi.sqlite3
GE360_HOST=127.0.0.1
GE360_PORT=8796
GE360_CORS_ORIGINS=http://localhost,http://127.0.0.1,https://localhost,capacitor://localhost
GE360_JOB_WORKERS=2
GE360_DEFAULT_WALL_THICKNESS_MM=120
GE360_DEFAULT_WALL_HEIGHT_MM=2700
GE360_SNAP_TOLERANCE_MM=250
GE360_ORTHOGONAL_TOLERANCE_DEG=25
GE360_LENGTH_TOLERANCE_MM=0.5
GE360_AI_ENABLED=false
GE360_OLLAMA_URL=http://127.0.0.1:11434
GE360_OLLAMA_MODEL=qwen2.5:7b
GE360_OLLAMA_TIMEOUT=20
```

Nessun secret è committato; `.env` è ignorato da Git.

## API V1

Quando `GE360_API_KEY` è valorizzata, inviare:

```text
X-GE360-API-Key: <key>
```

Endpoint principali:

- `GET /api/v1/health`
- `POST /api/v1/plans`
- `POST /api/v1/plans/refine`
- `POST /api/v1/plans/{planId}/process`
- `POST /api/v1/plans/{planId}/reprocess`
- `GET /api/v1/jobs/{jobId}`
- `GET /api/v1/plans/{planId}`
- `GET /api/v1/plans/{planId}/processed`
- `GET /api/v1/plans/{planId}/preview`
- `GET /api/v1/plans/{planId}/png`
- `GET /api/v1/plans/{planId}/svg`
- `GET /api/v1/plans/{planId}/dxf`
- `GET /api/v1/plans/{planId}/pdf`
- `GET /api/v1/plans/{planId}/3d`
- `GET /api/v1/plans/{planId}/versions`
- `GET /api/v1/plans/{planId}/versions/{version}`
- `GET /api/v1/plans/{planId}/versions/{version}/{artifact}`
- `POST /api/v1/notes/rewrite`

`POST /process` e `/reprocess` non bloccano fino alla fine: restituiscono `QUEUED` e un `jobId`. Una seconda richiesta sullo stesso piano mentre esiste un job attivo non crea un worker concorrente.

## Storage

Per ogni `planId`:

```text
raw/original.json        # primo payload, immutabile
raw/latest.json
raw/received-*.json      # invii successivi
current/                 # ultima versione pubblicata
versions/001/
versions/002/
logs/processing.jsonl
```

Ogni versione contiene `manifest.json` con stato, date, qualità, summary, hash input, file e stato AI.

## Ollama

La pipeline deterministica non dipende da Ollama. Con `GE360_AI_ENABLED=false` l'agente non viene usato. Se è attivo ma Ollama non risponde, l'elaborazione continua e registra `aiAvailable=false`.

L'agente non può creare direttamente coordinate o sostituire `walls`. Propone solo tool GE360; ogni candidato passa snapshot, controllo misure/aperture/topologia, nuovo solve, validation e score. Se non migliora o altera dati autorevoli viene scartato.

## Viewer 3D

Dopo aver processato un piano:

```text
http://127.0.0.1:8796/viewer3d/?plan=/api/v1/plans/PLAN_ID/3d
```

Il viewer usa `plan3d.json`, renderizza muri, pavimenti e aperture porta/finestra ed è indipendente dall'applicazione openPlan3D.

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```

La suite copre geometria A-K, diagonali, forma a L, muri condivisi, aperture, DXF riaperto con ezdxf, SVG/PNG/PDF/plan3d, RAW immutabile, versioning, job async/deduplica, API key/CORS, vecchie versioni, fallback Ollama, adapter e viewer. La stessa suite gira in `.github/workflows/ci.yml` su Python 3.12.

## Dipendenze esterne

Nessuna repository esterna è copiata interamente nel backend. Audit, commit analizzati e decisioni sono in `docs/third-party-audit.md`. `backend/third_party/` non contiene codice vendor nella V1.


## Smoke test HTTP reale

Oltre alla suite pytest, la repository contiene un test end-to-end che usa una vera istanza Uvicorn:

```bash
bash scripts/smoke-http.sh
```

Lo script usa una directory dati temporanea, non tocca i rilievi reali, invia il fixture v4 del frontend, attende la fine del job e verifica gli elaborati scaricabili. Viene eseguito anche da GitHub Actions.
