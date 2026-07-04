# IA notte

Applicazione web per generare e leggere ad alta voce storie della buonanotte per bambini,
pensata per essere usata da un genitore al buio, dal telefono. Le storie sono generate con
Google Gemini e narrate con Gemini TTS in italiano, con voce calda e velocità regolabile.

Progetto personale per uso in famiglia.

## Requisiti

- [uv](https://docs.astral.sh/uv/) (gestisce Python e le dipendenze automaticamente)
- Una chiave API di Google Gemini: https://aistudio.google.com/apikey

## Installazione

```bash
cp .env.example .env
# apri .env e incolla la tua chiave in GEMINI_API_KEY
```

La chiave resta solo sul backend: il frontend non la vede mai.

## Avvio

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Poi apri http://localhost:8000 — oppure, dal telefono sulla stessa rete Wi-Fi,
`http://<ip-del-computer>:8000`.

### Avvio con Docker

```bash
docker compose up -d --build
```

L'app è su http://localhost:8082. Le storie restano in un volume Docker
(`ia_notte_stories`), separato da `data/stories/` usata dall'avvio con uv.

Il deploy in produzione (istanza OCI, porta 8082) è gestito dal repo di
infrastruttura `infra_relli` con `scripts/deploy-ia-notte.sh`.

## Uso

1. Tocca uno dei personaggi preimpostati, oppure scrivi un personaggio a piacere
   e tocca "Genera storia". I personaggi scritti a mano passano prima da un
   controllo di idoneità per i bambini: se non vanno bene, l'app lo dice con
   gentilezza e non genera nulla.
2. Il testo appare dopo pochi secondi; la voce viene preparata a capitoli in
   parallelo e la riproduzione può iniziare dopo circa 20 secondi, mentre il
   resto si completa in sottofondo. Nota: con una chiave sul piano gratuito
   (3 richieste al minuto per modello TTS) i capitoli successivi possono
   impiegare qualche minuto; l'app attende e riprova da sola.
3. Ascolta con il pulsante grande play/pausa. I capitoli della storia compaiono
   come pulsanti numerati: quelli in preparazione mostrano una rotellina e si
   attivano appena pronti; toccane uno per saltare a quel punto. Sotto trovi la
   barra di avanzamento e i cursori di velocità (0,8x - 1,4x, predefinita 1,0x)
   e volume: agiscono subito e vengono ricordati tra una sessione e l'altra.
4. "Nuova storia" rigenera con lo stesso personaggio; "Storie recenti" fa riascoltare
   le storie già generate senza consumare chiamate API.

## Configurazione

Tutto in `.env` (vedi [.env.example](.env.example)): modelli di testo e TTS (con
fallback automatico in ordine di preferenza), voce, lingua e cartella della cache.
I personaggi preimpostati si cambiano in [app/config.py](app/config.py)
(`PRESET_CHARACTERS`); il prompt della storia e lo stile di lettura sono in
[app/prompts.py](app/prompts.py).

Le storie generate (testo JSON + audio WAV) vengono salvate in `data/stories/`,
esclusa dal versionamento.

## Sviluppo

```bash
uv run pytest          # test (le chiamate a Gemini sono mockate)
uv run ruff check .    # lint
uv run ruff format .   # formattazione
```

Altra documentazione in [documentation/](documentation/): architettura, scelte
tecniche, contratto API (OpenAPI) e cheatsheet dei comandi.
