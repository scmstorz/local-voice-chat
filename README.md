# Local Ollama Voice Chat

Lokaler Voice-Chat-Prototyp:

`Browser-Mikrofon -> lokale Transkription -> Ollama Chat -> lokale Sprachausgabe -> Browser`

## Voraussetzungen

- macOS auf einem Mac mit Apple Silicon ist empfohlen
- Ollama läuft lokal auf `http://localhost:11434`
- Ein Chat-Modell ist in Ollama installiert, hier voreingestellt: `qwen3.6:latest`
- Xcode Command Line Tools sind installiert, damit Swift-Helper gebaut werden können
- `ffmpeg` ist installiert
- macOS `say` ist vorhanden für die erste TTS-Version
- Optional: `mlx-whisper`/`mlx_whisper` ist in der Python-Umgebung installiert

## Installation auf einem MacBook

### 1. Repository auschecken

```bash
git clone https://github.com/scmstorz/local-voice-chat.git
cd local-voice-chat
```

### 2. System-Tools installieren

Falls noch nicht vorhanden:

```bash
xcode-select --install
```

Mit Homebrew:

```bash
brew install ollama ffmpeg
```

Ollama starten:

```bash
ollama serve
```

In einem zweiten Terminal das Chat-Modell laden. Der Default dieses Projekts ist:

```bash
ollama pull qwen3.6:latest
```

Wenn du dieses Modell nicht hast, nimm ein anderes lokales Ollama-Modell und setze
später `OLLAMA_MODEL` in `.env`.

### 3. Python-Umgebung einrichten

```bash
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Prüfe deine Ollama-Modellnamen:

```bash
ollama list
```

Passe in `.env` mindestens `OLLAMA_MODEL` an, falls dein Modell anders heißt.

### 4. Apple-STT-Helper bauen

```bash
bash scripts/build_apple_stt.sh
```

Danach sollten diese Dateien existieren:

```text
bin/apple_stt
bin/apple_live_stt
```

### 5. Deutsche lokale Apple-STT prüfen

```bash
bin/apple_stt --check --locale de-DE --timeout 10
```

Gutes Ergebnis:

```text
recognizer=yes locale=de-DE available=true
```

Wenn macOS nach Berechtigungen fragt, erlauben. Falls der Check danach weiterhin
mit `authorization failed with status denied` scheitert:

```text
System Settings -> Privacy & Security -> Speech Recognition
```

Dort Terminal, iTerm, Python oder die App aktivieren, aus der du
`python server/app.py` startest.

Für den Live-STT-Modus braucht dieselbe App zusätzlich Mikrofonrechte:

```text
System Settings -> Privacy & Security -> Microphone
```

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

Pro Serverstart wird ein Session-Log angelegt:

```text
sessions/yyyy-mm-dd-hh-mm-ss.txt
```

Darin stehen alle Nutzerfragen und Assistentenantworten dieser Sitzung.

## Standard-Konfiguration für Deutsch

Die wichtigsten Defaults aus `.env.example`:

```env
OLLAMA_MODEL=qwen3.6:latest
OLLAMA_DISABLE_THINKING=1
STT_PROVIDER=apple
STT_LANGUAGE=de
APPLE_STT_BINARY=bin/apple_stt
APPLE_LIVE_STT_BINARY=bin/apple_live_stt
TTS_VOICE=
```

`STT_PROVIDER=apple` ist der lokale deutsche Standard: Apple Speech Framework,
On-Device-Erkennung erzwungen, Live-Interims über `bin/apple_live_stt`.

`TTS_VOICE=` bedeutet: macOS verwendet die aktuelle Systemstimme. Die Ausgabe
läuft über `say` lokal. Wenn du eine bestimmte installierte Stimme willst:

```env
TTS_VOICE=Anna
```

## Transkription

Standardmäßig versucht der Server:

```python
import mlx_whisper
mlx_whisper.transcribe(...)
```

Der voreingestellte Voice-Chat-Default ist schnell statt maximal genau:

```env
STT_PROVIDER=apple
WHISPER_MODEL=mlx-community/whisper-tiny
STT_LANGUAGE=de
BROWSER_STT_LOCAL=1
APPLE_STT_BINARY=bin/apple_stt
APPLE_STT_TIMEOUT=60
STT_FP16=1
STT_TEMPERATURE=0
STT_CONDITION_ON_PREVIOUS_TEXT=0
```

`STT_PROVIDER=apple` nutzt einen kleinen Swift-Helper mit Apples
`Speech.framework`. Der Helper setzt `requiresOnDeviceRecognition = true`.
Wenn deutsche On-Device-Erkennung nicht verfügbar ist, schlägt die Transkription
fehl statt auf Cloud-STT zurückzufallen. Beim ersten Start kann macOS nach
Speech-Recognition-Berechtigung für Terminal/Python fragen.

Im Apple-Modus nutzt die UI den Streaming-Helper `bin/apple_live_stt`: Der Helper
nimmt das Mac-Mikrofon direkt auf und streamt partielle Transkripte an den
Browser. Beim Stop wird der letzte erkannte Text an Ollama geschickt. Dafuer
braucht die startende App, also Terminal/iTerm/Python, sowohl Mikrofon- als auch
Speech-Recognition-Rechte.

Der Helper wird bei der ersten Verwendung automatisch gebaut. Manuell:

```bash
bash scripts/build_apple_stt.sh
```

Preflight fuer Berechtigung und deutsche Recognizer-Verfuegbarkeit:

```bash
bin/apple_stt --check --locale de-DE --timeout 10
```

Wenn `authorization failed with status denied` erscheint, in macOS oeffnen:

```text
System Settings -> Privacy & Security -> Speech Recognition
```

Dort Terminal, iTerm, Python oder die App aktivieren, aus der `python server/app.py`
gestartet wird. Das ist getrennt von der Browser-Mikrofonberechtigung.

### Deutsche Besonderheiten

- `STT_LANGUAGE=de` wird intern zu `de-DE`.
- Lokale Browser-STT für Deutsch kann mit `language-not-supported` fehlschlagen.
  Das ist der Grund, warum der Standard nicht Web-Speech, sondern Apple
  `Speech.framework` ist.
- Apple On-Device-STT ist lokal, aber nur verfügbar, wenn macOS den deutschen
  Recognizer lokal unterstützt. Der Preflight oben prüft das.
- Die Browser-Mikrofonberechtigung reicht für den Apple-Live-Modus nicht aus.
  Terminal/iTerm/Python braucht ebenfalls Mikrofon- und Speech-Recognition-Rechte.

### English Setup

For English speech recognition, change `.env`:

```env
STT_LANGUAGE=en
SYSTEM_PROMPT=You are a local voice chat assistant. Answer briefly and directly in the user's language. Output only the final answer.
```

`STT_LANGUAGE=en` is mapped internally to `en-US`.

Check Apple on-device English STT:

```bash
bin/apple_stt --check --locale en-US --timeout 10
```

Expected:

```text
recognizer=yes locale=en-US available=true
```

`STT_PROVIDER=browser` nutzt die Web-Speech-API mit Live-Interim-Resultaten.
Das ist deutlich interaktiver, weil nicht erst die komplette Audiodatei an den
Server geschickt und mit Whisper transkribiert werden muss. Wenn der Browser die
API nicht bereitstellt, fällt die Oberfläche automatisch auf den MLX-Whisper-Pfad
zurück.

`BROWSER_STT_LOCAL=1` setzt, falls vom Browser unterstützt,
`SpeechRecognition.processLocally = true`. Wenn der Browser lokale STT oder das
benötigte Sprachpaket nicht bereitstellt, fällt die Oberfläche auf normale
Browser-STT zurück und zeigt das im Chat an.

Wenn du explizit MLX-Whisper erzwingen willst:

```env
STT_PROVIDER=mlx
```

Wenn du explizit Browser-STT erzwingen willst:

```env
STT_PROVIDER=browser
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
