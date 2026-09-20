# GE360 Rilievi Backend — Input schema v4

Schema additivo rispetto a v3.

## Feature flags

```json
{
  "metadata": {
    "schemaVersion": 4,
    "features": [
      "architectural-openings",
      "structured-interventions",
      "automatic-rooms",
      "linked-local-photos",
      "directional-photos",
      "progressive-takeoff",
      "worksite-archive"
    ]
  }
}
```

## Cantiere

Più rilievi possono condividere lo stesso `siteId`.

```json
{
  "siteId": "site-123",
  "site": {
    "id": "site-123",
    "title": "Bagno Rossi",
    "clientName": "Mario Rossi",
    "address": "Via Esempio 10, Trieste",
    "phone": "+39...",
    "email": "cliente@example.it",
    "status": "survey",
    "notes": "",
    "createdAt": "2026-09-20T20:00:00Z",
    "updatedAt": "2026-09-20T21:00:00Z"
  }
}
```

Stati iniziali: `lead`, `survey`, `quote`, `active`, `paused`, `done`.

Il backend deve conservare sia `siteId` sia lo snapshot `site`. Report e
PDF possono usare lo snapshot per intestazione cliente/cantiere.

## Foto direzionali

```json
{
  "id": "photo-1",
  "targetType": "wall",
  "targetId": "w2",
  "targetLabel": "Muro B · Bagno",
  "cameraPoint": { "x": 124.2, "y": 88.5 },
  "targetPoint": { "x": 201.0, "y": 91.1 },
  "directionDeg": 1.94,
  "localOnly": true
}
```

- `cameraPoint`: posizione del fotografo nel sistema locale della pianta.
- `targetPoint`: soggetto fotografato.
- `directionDeg`: angolo dal punto camera al soggetto.
- `localOnly=true`: il blob non è ancora disponibile al backend.

Quando genera un elaborato grafico, il backend può rappresentare la foto con
icona camera e freccia orientata.

## Backup

Gli snapshot automatici locali non fanno parte del payload backend. Sono
conservati sul dispositivo in IndexedDB, con massimo 20 versioni per rilievo.
Le versioni backend restano un sistema distinto.

## Compatibilità

Tutti i campi v2/v3 restano validi. Lo schema v4 aggiunge soltanto archivio
cantiere e direzione fotografica.
