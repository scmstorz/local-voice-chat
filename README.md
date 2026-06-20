# Local Ollama Voice Chat

Lokaler Voice-Chat-Prototyp:

`Browser-Mikrofon -> lokale Transkription -> Ollama Chat -> lokale Sprachausgabe -> Browser`

## Voraussetzungen

- Ollama läuft lokal auf `http://localhost:11434`
- Ein Chat-Modell ist in Ollama installiert, hier voreingestellt: `qwen3.6:latest`
- `ffmpeg` ist installiert
- macOS `say` ist vorhanden für die erste TTS-Version
- Optional: `mlx-whisper`/`mlx_whisper` ist in der Python-Umgebung installiert

## Setup

```bash
cp .env.example .env
```

Passe in `.env` mindestens `OLLAMA_MODEL` an den Namen aus `ollama list` an.

## Start

```bash
python3 server/app.py
```

Der Server versucht zuerst den Port aus `.env`, standardmäßig `8000`.
Falls der Port belegt ist, nimmt er automatisch den nächsten freien Port.
Öffne die URL, die im Terminal ausgegeben wird, zum Beispiel:

```text
http://127.0.0.1:8000
```

## Transkription

Standardmäßig versucht der Server:

```python
import mlx_whisper
mlx_whisper.transcribe(...)
```

Wenn deine lokale Installation anders funktioniert, setze `STT_COMMAND` in `.env`.
Das Kommando bekommt die Audio-Datei über `{file}` und muss den erkannten Text auf stdout schreiben.

Beispiel:

```env
STT_COMMAND=python -m mlx_whisper.transcribe --path_or_hf_repo mlx-community/whisper-large-v3-mlx {file}
```

## API

- `GET /api/health`
- `GET /api/config`
- `POST /api/chat` mit JSON `{ "message": "..." }`
- `POST /api/voice` mit Multipart-Feld `audio`
