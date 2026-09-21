# GE360 Qwen3 autonomous floorplan agent

Target runtime: **Ollama + qwen3:8b**.

Le istruzioni dell'agente sono versionate in:
- backend/agent/instructions/handbook.md
- backend/agent/examples/geometry-cases.json

Il loader è backend/agent/prompt_loader.py.

Principio architetturale:
- libertà strategica al modello;
- solver deterministico come autorità geometrica;
- misure utente immutabili;
- auto-repair proattivo con tolleranza massima del 30% di elementi problematici/incerti; il 30% non limita il numero di tentativi e non è la tolleranza metrica delle misure;
- sandbox + validation + rollback;
- esempi selezionati dinamicamente;
- NEEDS_REVIEW quando servono troppe assunzioni;
- capability gap esplicito quando manca un tool deterministico.

I dati reali di esperienza devono restare fuori da Git finché non vengono curati. Vedi backend/agent/training/README.md.
