# GE360 Agent Experience / Training

I lavori reali NON devono essere committati automaticamente nella repository.

Runtime store consigliato:

/opt/ge360/data/agent-experience/

Per ogni episodio registra:
- input summary;
- solver warnings;
- proposta Qwen;
- tool tentati;
- tool accettati/rifiutati;
- motivi del validator;
- risultato finale;
- eventuale correzione dell'utente.

Solo casi ripuliti e approvati diventano esempi ufficiali.

Ordine consigliato di evoluzione:
1. few-shot dinamico / retrieval di casi simili;
2. dataset curato;
3. solo dopo sufficiente qualità, LoRA/QLoRA o preference tuning.

Non addestrare direttamente su conversazioni grezze non curate.
