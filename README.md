# GE360 Rilievi Backend

Backend Python/FastAPI che trasforma il rilievo rapido prodotto da ge360-open-plan3d in una geometria metrica verificabile, planimetria tecnica 2D, file CAD e modello 3D.

La regola centrale è non negoziabile: le misure inserite dall'utente sono autorevoli; lo schizzo è indicativo. Il backend può sistemare topologia, angoli, parallelismi e piccoli gap, ma non modifica di nascosto lengthCm, widthCm, offsetCm o altre misure dichiarate.

## Base v1 implementata

- FastAPI con autenticazione X-GE360-API-Key.
- Compatibilità con payload frontend v4 e POST /api/v1/plans/refine.
- Storage RAW immutabile più versioni.
- SQLite per indice e stato.
- Normalizzazione interna in millimetri.
- Topology graph NetworkX.
- Solver deterministico SciPy.
- Riconoscimento ambienti con Shapely.
- Preservazione metrica di porte e finestre.
- processed-plan.json, SVG, DXF, PNG e PDF.
- plan3d.json e GLB.
- Worker interno non bloccante sostituibile in futuro con RQ/Celery.
- Agente Ollama opzionale, vincolato da validation e rollback.
- Telegram opzionale.
- Viewer Three.js minimale con orbit, pan, zoom, top view, prospettiva e reset.
- Installazione Debian nativa, systemd e Docker.
- Test A-K, 3D, API e artefatti.

## Architettura

GE360 Android/Web -> FastAPI -> RAW storage -> normalizer -> topology graph -> deterministic geometry solver -> optional constrained AI agent -> validator + geometry score -> single PlanModel -> JSON/SVG/DXF/PNG/PDF + plan3d/GLB -> versioned storage -> frontend/Telegram.

Dettagli in docs/architecture.md.

## Requisiti Debian

Debian 12/13, Python 3.12+, python3-venv e rsync. Ollama è necessario solo se si abilita l'agente IA o la riscrittura appunti.

## Installazione nativa

Clonare la repository, entrare nella cartella e avviare:

    sudo bash scripts/install-debian.sh

Lo script:
- crea /opt/ge360/ge360-rilievi-backend;
- crea il virtualenv;
- installa requirements.txt;
- crea /opt/ge360/data/rilievi;
- copia .env.example in .env solo se .env non esiste;
- non sovrascrive una unit systemd già presente.

Poi modificare:

    sudo nano /opt/ge360/ge360-rilievi-backend/.env

Generare una chiave:

    openssl rand -hex 32

Inserire la chiave in GE360_API_KEY e avviare:

    sudo systemctl enable --now ge360-rilievi-backend.service
    sudo systemctl status ge360-rilievi-backend.service

Bind predefinito: 127.0.0.1:8796.

Il template systemd usa User=jarvis e Group=jarvis. Se il server usa un utente diverso, modificarli prima dell'avvio.

## Avvio manuale

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    set -a
    source .env
    set +a
    uvicorn backend.main:app --host 127.0.0.1 --port 8796

## Docker

Docker è alternativo, non obbligatorio.

    cp .env.example .env
    docker compose up -d --build

## ENV principali

GE360_API_KEY=
GE360_DATA_DIR=/opt/ge360/data/rilievi
GE360_DB_PATH=/opt/ge360/data/rilievi/ge360-rilievi.sqlite3
GE360_HOST=127.0.0.1
GE360_PORT=8796
GE360_DEFAULT_WALL_THICKNESS_MM=120
GE360_DEFAULT_WALL_HEIGHT_MM=2700
GE360_SNAP_TOLERANCE_MM=250
GE360_ORTHOGONAL_TOLERANCE_DEG=25
GE360_LENGTH_TOLERANCE_MM=0.5
GE360_AI_ENABLED=false
GE360_OLLAMA_URL=http://127.0.0.1:11434
GE360_OLLAMA_MODEL=qwen2.5:7b
GE360_OLLAMA_TIMEOUT=20
GE360_TELEGRAM_ENABLED=false
GE360_TELEGRAM_BOT_TOKEN=
GE360_TELEGRAM_CHAT_ID=
GE360_PUBLIC_BASE_URL=

Nessun token o secret è incluso nella repository. .env è ignorato da Git.

## Ollama

La geometria deterministica non dipende da Ollama. Con GE360_AI_ENABLED=false tutta la pipeline resta operativa.

Se abilitato, l'agente può soltanto proporre vincoli da una lista chiusa. Ogni proposta viene ricalcolata e rifiutata se modifica una misura, produce una geometria invalida o non migliora il geometry score. Massimo 5 iterazioni. Il modello predefinito è qwen2.5:7b.

## Telegram

Configurazione solo via .env. Il notifier invia un riepilogo e, quando disponibili, preview.png, plan.pdf e plan.dxf. Un errore Telegram non modifica lo stato dell'elaborazione.

## API

Header richiesto per /api/v1/*:

    X-GE360-API-Key: <key>

Endpoint:

- GET /api/v1/health
- POST /api/v1/plans
- POST /api/v1/plans/refine
- POST /api/v1/plans/{planId}/process
- POST /api/v1/plans/{planId}/reprocess
- GET /api/v1/jobs/{jobId}
- GET /api/v1/plans/{planId}
- GET /api/v1/plans/{planId}/processed
- GET /api/v1/plans/{planId}/preview
- GET /api/v1/plans/{planId}/svg
- GET /api/v1/plans/{planId}/dxf
- GET /api/v1/plans/{planId}/pdf
- GET /api/v1/plans/{planId}/3d
- GET /api/v1/plans/{planId}/glb
- GET /api/v1/plans/{planId}/versions
- POST /api/v1/notes/rewrite

Il contratto frontend esatto è in docs/frontend-api.md.

## Esempio rapido

Salvare un RAW con POST /api/v1/plans, quindi avviare la processazione con:

    curl -X POST http://127.0.0.1:8796/api/v1/plans/demo-2x3/process -H 'X-GE360-API-Key: YOUR_KEY'

Leggere lo stato con:

    curl http://127.0.0.1:8796/api/v1/plans/demo-2x3 -H 'X-GE360-API-Key: YOUR_KEY'

Il frontend esistente può continuare a usare POST /api/v1/plans/refine: il backend salva il RAW e restituisce subito jobId e PROCESSING.

## Storage

Per ogni planId:

- raw/original.json: primo payload, immutabile.
- raw/latest.json: payload più recente.
- raw/received-*.json: invii successivi immutabili.
- current/: ultima versione pubblicata.
- versions/001, 002, ...: elaborazioni precedenti.
- logs/processing.jsonl: hash input, solver operations, proposte IA accettate/rifiutate, score, tempi, warning ed errori.

I file grandi restano sul filesystem; SQLite memorizza stato e metadati.

## Test

Installare le dipendenze di sviluppo ed eseguire:

    pip install -r requirements-dev.txt
    pytest -q

La suite copre:
- A: rettangolo 2x3 = 6 m²;
- B: rettangolo disegnato storto;
- C: piccoli gap;
- D: diagonale reale;
- E: porta 80 cm, offset 120 cm;
- F: finestra;
- G: forma a L;
- H: due stanze con muro condiviso;
- I: tre ambienti;
- J: misure incompatibili -> NEEDS_REVIEW senza alterazione;
- K: schizzo molto sproporzionato;
- stanza 2x3 in 3D;
- lettura reale JSON/SVG/DXF/PNG/PDF/GLB;
- API key, polling, versioni e compatibilità /plans/refine.

## Viewer 3D

viewer/index.html usa Three.js e OrbitControls. Il parametro glb può puntare a /api/v1/plans/<planId>/glb.

## Dipendenze esterne studiate

archit-app e openPlan3D sono stati valutati con licenza MIT. Non vengono copiati nel core. La decisione è documentata in docs/dependency-decisions.md. FreeCAD/OpenCascade restano opzionali per evoluzioni CAD/BIM future.

## Troubleshooting

401 Invalid API key: controllare GE360_API_KEY e l'header.
503 GE360_API_KEY not configured: impostare la chiave e riavviare.
NEEDS_REVIEW: leggere current/processed-plan.json e logs/processing.jsonl; il backend non ha trovato una soluzione coerente senza violare misure/vincoli.
GLB 404: GLB è opzionale; JSON e output 2D restano validi.
Ollama non raggiungibile: disabilitare GE360_AI_ENABLED o avviare Ollama; la pipeline deterministica continua comunque.
