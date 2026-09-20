# GE360 Rilievi Backend — Input schema v3

Schema coordinato con `ge360-open-plan3d` per rilievi mobile, ambienti
automatici, foto collegate e computo progressivo.

## Principi

- `walls[].lengthCm` resta autoritativo.
- Le aperture metriche restano definite da `widthCm`, `offsetCm` e
  `referenceEnd`.
- Gli ambienti possono essere rilevati automaticamente, ma il backend non deve
  inventare il nome se `needsNaming=true`.
- Le foto sono locali finché non esiste un endpoint media dedicato.
- Il computo frontend è progressivo e va validato/ricalcolato dal backend quando
  la geometria autoritativa è disponibile.

## Feature flags

```json
{
  "metadata": {
    "schemaVersion": 3,
    "features": [
      "architectural-openings",
      "structured-interventions",
      "automatic-rooms",
      "linked-local-photos",
      "progressive-takeoff"
    ]
  }
}
```

## Ambienti automatici

```json
{
  "id": "room-1",
  "name": "Ambiente 1",
  "wallIds": ["w1", "w2", "w3", "w4"],
  "faceKey": "w1|w2|w3|w4",
  "autoDetected": true,
  "needsNaming": true,
  "detectedQuality": "ok"
}
```

Se l'utente assegna un nome reale, `needsNaming` diventa `false`.

## Foto

Il payload contiene metadati, non il blob:

```json
{
  "id": "photo-1",
  "targetType": "wall",
  "targetId": "w2",
  "targetLabel": "Muro B · Bagno",
  "roomName": "Bagno",
  "name": "IMG_001.jpg",
  "mime": "image/jpeg",
  "size": 481223,
  "createdAt": "2026-09-20T20:00:00Z",
  "localOnly": true
}
```

`targetType` può essere `wall`, `opening`, `room` o `plan`.

Quando `localOnly=true` il backend deve conservare il riferimento ma non deve
tentare di scaricare il file.

## Computo progressivo

```json
{
  "takeoff": {
    "rows": [
      {
        "code": "floor_tile",
        "label": "POSA PIASTRELLE",
        "category": "finish",
        "value": 6.82,
        "unit": "m²",
        "basis": "floor_area",
        "targets": 1,
        "estimated": false,
        "rooms": ["Bagno"]
      }
    ],
    "unresolved": [],
    "totals": {
      "rows": 1,
      "interventions": 1,
      "unresolved": 0
    }
  }
}
```

Basi iniziali:

- `floor_area`
- `ceiling_area`
- `wall_area`
- `walls_ceiling_area`
- `perimeter`
- `count`

Le righe `estimated=true` devono restare distinguibili dalle quantità
confermate.

## Compatibilità

Lo schema v3 è additivo rispetto allo schema v2. Porte, finestre,
`interventions`, `notes` e tutte le quote metriche restano compatibili.
