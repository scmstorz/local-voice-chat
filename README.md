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
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Passe in `.env` mindestens `OLLAMA_MODEL` an den Namen aus `ollama list` an.

## Start

```bash
source .venv/bin/activate
python server/app.py
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

Der voreingestellte Voice-Chat-Default ist schnell statt maximal genau:

```env
STT_PROVIDER=browser
WHISPER_MODEL=mlx-community/whisper-tiny
STT_LANGUAGE=de
STT_FP16=1
STT_TEMPERATURE=0
STT_CONDITION_ON_PREVIOUS_TEXT=0
```

`STT_PROVIDER=browser` nutzt die Web-Speech-API mit Live-Interim-Resultaten.
Das ist deutlich interaktiver, weil nicht erst die komplette Audiodatei an den
Server geschickt und mit Whisper transkribiert werden muss. Wenn der Browser die
API nicht bereitstellt, fällt die Oberfläche automatisch auf den MLX-Whisper-Pfad
zurück.

Wenn du explizit MLX-Whisper erzwingen willst:

```env
STT_PROVIDER=mlx
```

Für bessere Genauigkeit, aber höhere Latenz:

```env
WHISPER_MODEL=mlx-community/whisper-large-v3-mlx
```

Nach jeder Voice-Anfrage schreibt der Server Timing-Zeilen ins Terminal:

```text
voice timings: convert=... stt=... ollama=... tts=... total=...
```

Wenn `stt` dominiert, ist das Whisper-Modell der Engpass. Wenn `ollama` dominiert,
ist das Chat-Modell bzw. dessen Antwortlänge der Engpass.

## Ollama-Latenz

Die Standardwerte sind auf kurze Voice-Chat-Antworten getrimmt:

```env
OLLAMA_KEEP_ALIVE=30m
OLLAMA_NUM_PREDICT=256
OLLAMA_NUM_CTX=4096
OLLAMA_TEMPERATURE=0.4
OLLAMA_DISABLE_THINKING=1
```

Nach jeder Ollama-Anfrage schreibt der Server:

```text
ollama timings: wall=... load=... prompt_tokens=... prompt_tps=... eval_tokens=... eval_tps=...
```

- Hoher `load`-Wert: Ollama lädt das Modell neu. `OLLAMA_KEEP_ALIVE=30m` sollte das nach der ersten Anfrage vermeiden.
- Sehr niedriger `eval_tps`-Wert: Das Modell ist für die Hardware/Quantisierung zu schwer oder läuft nicht schnell genug im Speicher.
- Viele `eval_tokens`: Die Antwort ist zu lang. `OLLAMA_NUM_PREDICT` kleiner setzen, z. B. `80`.
- Leerer `content` mit viel `thinking`: Qwen hat das Token-Budget im Denkmodus verbraucht. `OLLAMA_DISABLE_THINKING=1` muss aktiv sein; alternativ `OLLAMA_NUM_PREDICT` erhöhen.

Zum Vergleich ein kleineres Ollama-Modell testen:

```bash
ollama pull qwen3:1.7b
```

Dann in `.env`:

```env
OLLAMA_MODEL=qwen3:1.7b
```

Wenn der Server mit `No module named 'mlx_whisper'` scheitert, läuft er nicht mit der Projekt-venv
oder `mlx-whisper` wurde darin noch nicht installiert.

Prüfen:

```bash
source .venv/bin/activate
which python
python -c "import mlx_whisper; print('mlx_whisper ok')"
```

Falls du eine andere Python-Umgebung verwenden willst, in der `mlx_whisper` schon funktioniert:

```env
STT_COMMAND=/pfad/zum/python scripts/transcribe_mlx.py {file}
```

Den Pfad findest du in der funktionierenden Umgebung mit:

```bash
which python
```

`STT_COMMAND` bekommt die Audio-Datei über `{file}` und muss den erkannten Text auf stdout schreiben.

Beispiel:

```env
STT_COMMAND=/Users/deinname/meine-whisper-env/bin/python scripts/transcribe_mlx.py {file}
```

### Modell-Cache und Offline-Betrieb

`WHISPER_MODEL=mlx-community/whisper-large-v3-mlx` ist kein lokaler Dateipfad,
sondern ein Hugging-Face-Modellname. `mlx-whisper` lädt bzw. prüft diese
Modelldateien beim ersten Transkribieren im Hugging-Face-Cache.

Wenn die Konsole so etwas zeigt:

```text
Fetching 4 files: 100%
Download complete: 0.00B
```

dann ist das die Modell-/Cache-Auflösung von `mlx-whisper`, nicht Ollama.
`0.00B` bedeutet typischerweise, dass die Dateien schon im lokalen Cache lagen.

Für Offline-Betrieb nach dem Vorladen:

```env
STT_OFFLINE=1
STT_DISABLE_PROGRESS=1
```

Dann setzt der Server `HF_HUB_OFFLINE=1`; fehlt das Modell lokal, schlägt die
Transkription fehl statt während des Betriebs etwas aus dem Netz zu holen.
`STT_DISABLE_PROGRESS=1` unterdrückt die Hugging-Face-Progressanzeige, die auch
bei reiner Cache-Prüfung wie ein Download aussehen kann.

## API

- `GET /api/health`
- `GET /api/config`
- `POST /api/chat` mit JSON `{ "message": "..." }`
- `POST /api/voice` mit Multipart-Feld `audio`
