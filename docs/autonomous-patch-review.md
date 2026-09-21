# Verifica patch agente autonomo

Base: main, commit 449ff41f9ad74b69206b9504fb039800ec58cb4b.
Patch ricevuta: backend-agente-autonomo (1).patch, tre commit.

Integrati: dipendenza systemd dal firewall Bridge, motore deterministico delle
ipotesi, Monte Carlo delle superfici, modello degli errori e registro decisioni.
Il collegamento WireGuard e la dashboard esistente sono preservati.

Correzioni durante la verifica:
- Esportati realmente `walls[].resolvedBy` e `usedLengthMm`, anche per gli outlier.
- Una decisione di compromesso o forma non nasconde residui fuori tolleranza;
  le diagonali non esplicitamente escluse continuano a richiedere revisione.
- Apprendimento serializzato fra thread/processi, ricaricato sotto lock e
  deduplicato per revisione; errori I/O dell'apprendimento non bloccano gli export.
- Campioni Monte Carlo limitati a 200; associazione delle stanze per pareti,
  evitando di confondere stanze vicine in base al solo centroide.
- Versione API e pacchetto allineata a 1.5.0.

Verifica locale: 114 test passati, compilazione Python, smoke HTTP con export
JSON/PNG/SVG/PDF/DXF/3D, sintassi shell Bridge e `git diff --check`.
Due avvisi di deprecazione provengono da Starlette/AnyIO nel client di test.

Limiti: pesi delle ipotesi non calibrati come probabilità di correttezza;
intervalli condizionati al modello di rumore e alle alternative considerate.
Non eseguiti installazione systemd/WireGuard su host reale, prova APK o E2E
con la repository frontend esterna. L'installazione sul server Linux resta separata.
