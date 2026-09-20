# GE360 repository invariants

## GE360 DIRECT BRIDGE INVARIANTS

Ogni agente IA o modifica automatica deve rispettare queste regole:

1. non cancellare `/etc/ge360/direct-bridge`;
2. non cancellare `/var/lib/ge360/direct-bridge`;
3. non rigenerare la server WireGuard key se esiste;
4. non modificare gli IP peer senza una migration esplicita;
5. non esporre TCP 9888 direttamente sulla WAN;
6. non committare private key, configurazioni client one-shot o altri segreti;
7. non revocare dispositivi durante update/install;
8. preservare la compatibilità del payload/QR WireGuard;
9. preservare la configurazione GE360 gestita di `wg0`;
10. eseguire i test Bridge dopo modifiche a networking, API, setup o installazione.

Il Bridge è infrastruttura indipendente dal motore CAD, solver geometrico e agente Qwen/Ollama. Non collegare l'LLM alla configurazione WireGuard.
