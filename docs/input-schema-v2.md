# GE360 Rilievi Backend — Input schema v2

Questo documento definisce il contratto che il backend dovrà implementare per
ricevere i rilievi da `ge360-open-plan3d`.

## Principio

Il backend non deve reinterpretare le misure come pixel.

- `walls[].lengthCm` è autoritativo.
- `openings[].widthCm` e `offsetCm` sono metrici.
- `interventions` descrive le lavorazioni di cantiere.
- lo schizzo serve per forma, topologia e orientamento.
- se le misure sono incompatibili, il risultato deve essere marcato
  `NEEDS_REVIEW`, non corretto inventando quote.

## Payload

```json
{
  "version": 4,
  "kind": "ge360-rough-survey",
  "planId": "plan-123",
  "name": "Bagno",
  "sourceRevision": "src-...",
  "walls": [],
  "openings": [],
  "rooms": [],
  "notes": [],
  "interventions": [],
  "wallHeightM": 2.7,
  "metadata": {
    "client": "ge360-open-plan3d",
    "schemaVersion": 2,
    "features": [
      "architectural-openings",
      "structured-interventions"
    ]
  }
}
```

## Aperture architettoniche

Esempio porta:

```json
{
  "id": "d-1",
  "type": "door",
  "wallId": "w-3",
  "widthCm": 80,
  "offsetCm": 42,
  "referenceEnd": "a",
  "position": 0.31,
  "swingSide": 1
}
```

Esempio finestra:

```json
{
  "id": "f-1",
  "type": "window",
  "wallId": "w-2",
  "widthCm": 120,
  "offsetCm": 65,
  "referenceEnd": "b",
  "position": 0.68
}
```

Regole backend:

1. porta/finestra = vuoto reale nella parete;
2. SVG/PDF/DXF/PNG devono interrompere il tratto del muro nel vano;
3. la porta può avere anta + arco di apertura;
4. la finestra può avere doppia/tripla linea;
5. `position` è fallback visuale;
6. se sono presenti `widthCm`, `offsetCm`, `referenceEnd`, questi prevalgono.

## Interventi

Il frontend invia `interventions` e mantiene `notes` per retrocompatibilità.
Il backend deve preferire `interventions` quando presente.

```json
{
  "id": "note-1",
  "kind": "intervention",
  "targetType": "floor",
  "targetId": "room-2",
  "targetLabel": "Pavimento · Bagno",
  "roomName": "Bagno",
  "displayStyle": "callout",
  "workItems": [
    {
      "code": "floor_demolish",
      "label": "DEMOLIRE PAVIMENTO",
      "category": "demolition"
    },
    {
      "code": "floor_tile",
      "label": "POSA PIASTRELLE",
      "category": "finish"
    }
  ],
  "rawText": "Nuovo gres 60x120",
  "context": {
    "areaM2": 6.8,
    "wallHeightM": 2.7
  }
}
```

### Target

- `wall`
- `floor`
- `ceiling`
- `room`
- `opening`

### Categorie

- `demolition`
- `construction`
- `finish`
- `general`

### Display

- `callout`: vignetta con richiamo;
- `text`: testo in pianta.

## Codici iniziali supportati

### Muri

- `wall_demolish`
- `wall_new`
- `wall_opening_new`
- `wall_opening_close`
- `wall_tile`
- `wall_plaster_paint`
- `wall_drywall`

### Pavimenti

- `floor_demolish`
- `floor_demolish_rebuild`
- `floor_tile`
- `floor_spc`
- `floor_level`
- `floor_screed`

### Soffitti

- `ceiling_false`
- `ceiling_cove`
- `ceiling_demolish`
- `ceiling_plaster`
- `ceiling_paint`

### Ambienti

- `room_complete`
- `room_demolition`
- `room_plaster`
- `room_paint`

### Porte e finestre

- `opening_remove`
- `opening_replace`
- `opening_widen`
- `opening_close`

## Futuro computo metrico

Il backend dovrà poter derivare righe di computo senza NLP quando il dato
strutturato è sufficiente.

Esempi:

- `floor_demolish` + `context.areaM2=6.8` → 6,8 m² demolizione pavimento;
- `floor_tile` + `context.areaM2=6.8` → 6,8 m² posa piastrelle;
- `wall_demolish` + `context.grossAreaM2` → superficie muro da demolire;
- `ceiling_false` + `context.ceilingM2` → m² controsoffitto.

Il testo libero resta utile per dettagli, materiali e note particolari, ma non
deve sostituire i dati strutturati quando questi esistono.
