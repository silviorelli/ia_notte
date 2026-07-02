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

## Uso

1. Tocca uno dei personaggi preimpostati, oppure scrivi un personaggio a piacere
   e tocca "Genera storia".
2. Attendi la generazione (testo + audio, fino a un minuto).
3. Ascolta con il pulsante grande play/pausa; regola la velocità di lettura con il
   cursore (0,60x - 1,00x, predefinita 0,85x). La velocità agisce subito, senza
   rigenerare l'audio, e viene ricordata tra una sessione e l'altra.
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
