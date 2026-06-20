from __future__ import annotations

import base64
import errno
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
SESSIONS_DIR = ROOT / "sessions"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3.6:latest")
    ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m").strip()
    ollama_num_predict: int = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
    ollama_temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.4"))
    ollama_disable_thinking: bool = os.getenv("OLLAMA_DISABLE_THINKING", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    whisper_model: str = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx")
    stt_provider: str = os.getenv("STT_PROVIDER", "browser").strip().lower()
    stt_language: str = os.getenv("STT_LANGUAGE", "").strip()
    browser_stt_local: bool = os.getenv("BROWSER_STT_LOCAL", "1").strip().lower() in {"1", "true", "yes", "on"}
    apple_stt_binary: str = os.getenv("APPLE_STT_BINARY", "bin/apple_stt").strip()
    apple_live_stt_binary: str = os.getenv("APPLE_LIVE_STT_BINARY", "bin/apple_live_stt").strip()
    apple_stt_timeout: int = int(os.getenv("APPLE_STT_TIMEOUT", "60"))
    apple_live_stt_timeout: int = int(os.getenv("APPLE_LIVE_STT_TIMEOUT", "300"))
    stt_fp16: bool = os.getenv("STT_FP16", "1").strip().lower() in {"1", "true", "yes", "on"}
    stt_temperature: float = float(os.getenv("STT_TEMPERATURE", "0"))
    stt_condition_on_previous_text: bool = os.getenv("STT_CONDITION_ON_PREVIOUS_TEXT", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    stt_offline: bool = os.getenv("STT_OFFLINE", "0").strip().lower() in {"1", "true", "yes", "on"}
    stt_disable_progress: bool = os.getenv("STT_DISABLE_PROGRESS", "1").strip().lower() in {"1", "true", "yes", "on"}
    stt_command: str = os.getenv("STT_COMMAND", "").strip()
    system_prompt: str = os.getenv(
        "SYSTEM_PROMPT",
        "Du bist ein lokaler Voice-Chat-Assistent. Antworte knapp, direkt und in der Sprache des Nutzers. "
        "Wenn du Deutsch sprichst, duze den Nutzer immer und verwende nie die Sie-Form.",
    )
    tts_voice: str = os.getenv("TTS_VOICE", "").strip()
    tts_rate: str = os.getenv("TTS_RATE", "185")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))


settings = Settings()
messages: list[dict[str, str]] = [{"role": "system", "content": settings.system_prompt}]
live_stt_lock = threading.Lock()
live_stt_process: subprocess.Popen[str] | None = None
session_log_lock = threading.Lock()
session_started_at = datetime.now()
session_log_path = SESSIONS_DIR / f"{session_started_at:%Y-%m-%d-%H-%M-%S}.txt"


class HttpError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


class VoiceChatHandler(BaseHTTPRequestHandler):
    server_version = "LocalVoiceChat/0.1"

    def do_GET(self) -> None:
        try:
            if self.path == "/":
                self.send_file(STATIC_DIR / "index.html")
            elif self.path.startswith("/static/"):
                relative = self.path.removeprefix("/static/").split("?", 1)[0]
                self.send_file(STATIC_DIR / relative)
            elif self.path == "/api/health":
                self.send_json(health())
            elif self.path == "/api/config":
                self.send_json(config())
            elif self.path == "/api/apple-live/events":
                self.handle_apple_live_events()
            else:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Not found.")
        except HttpError as exc:
            self.send_error_json(exc.status, exc.detail)
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        try:
            if self.path == "/api/chat":
                payload = self.read_json()
                user_text = str(payload.get("message", "")).strip()
                if not user_text:
                    raise HttpError(HTTPStatus.BAD_REQUEST, "Message is empty.")
                assistant_text = ask_ollama(user_text)
                audio = synthesize_speech(assistant_text)
                self.send_json(chat_response(user_text, assistant_text, audio))
            elif self.path == "/api/voice":
                audio_bytes, filename, content_type = self.read_multipart_file("audio")
                self.handle_voice(audio_bytes, filename, content_type)
            elif self.path == "/api/apple-live/start":
                self.send_json(start_apple_live_stt())
            elif self.path == "/api/apple-live/stop":
                self.send_json(stop_apple_live_stt())
            else:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Not found.")
        except HttpError as exc:
            self.send_error_json(exc.status, exc.detail)
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def handle_voice(self, audio_bytes: bytes, filename: str | None, content_type: str | None) -> None:
        suffix = guess_suffix(filename, content_type)
        with tempfile.TemporaryDirectory(prefix="voice-chat-") as tmp_dir:
            tmp = Path(tmp_dir)
            raw_path = tmp / f"input{suffix}"
            raw_path.write_bytes(audio_bytes)
            started = time.perf_counter()
            wav_path = normalize_audio(raw_path, tmp / "input.wav")
            converted_at = time.perf_counter()
            transcript = transcribe_audio(wav_path).strip()
            transcribed_at = time.perf_counter()
            if not transcript:
                raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, "No speech was transcribed.")
            assistant_text = ask_ollama(transcript)
            answered_at = time.perf_counter()
            audio = synthesize_speech(assistant_text, tmp)
            finished_at = time.perf_counter()
            print(
                "voice timings: "
                f"convert={converted_at - started:.2f}s "
                f"stt={transcribed_at - converted_at:.2f}s "
                f"ollama={answered_at - transcribed_at:.2f}s "
                f"tts={finished_at - answered_at:.2f}s "
                f"total={finished_at - started:.2f}s"
            )
            self.send_json(chat_response(transcript, assistant_text, audio))

    def handle_apple_live_events(self) -> None:
        process = current_live_stt_process()
        if process is None or process.stdout is None:
            raise HttpError(HTTPStatus.CONFLICT, "Apple live STT is not running.")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if process.poll() is not None:
                clear_live_stt_process(process)

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def read_json(self) -> dict[str, Any]:
        try:
            return json.loads(self.read_body().decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HttpError(HTTPStatus.BAD_REQUEST, "Invalid JSON.") from exc

    def read_multipart_file(self, field_name: str) -> tuple[bytes, str | None, str | None]:
        content_type = self.headers.get("Content-Type", "")
        match = re.search(r'boundary="?([^";]+)"?', content_type)
        if not match:
            raise HttpError(HTTPStatus.BAD_REQUEST, "Missing multipart boundary.")

        boundary = ("--" + match.group(1)).encode("utf-8")
        body = self.read_body()

        for part in body.split(boundary):
            if not part or part in (b"--\r\n", b"--"):
                continue
            part = part.strip(b"\r\n")
            if part.endswith(b"--"):
                part = part[:-2].strip(b"\r\n")
            if b"\r\n\r\n" not in part:
                continue

            raw_headers, data = part.split(b"\r\n\r\n", 1)
            headers = raw_headers.decode("utf-8", errors="replace")
            disposition = next((line for line in headers.split("\r\n") if line.lower().startswith("content-disposition:")), "")
            if f'name="{field_name}"' not in disposition:
                continue

            filename_match = re.search(r'filename="([^"]*)"', disposition)
            type_match = re.search(r"content-type:\s*([^\r\n]+)", headers, flags=re.IGNORECASE)
            return (
                data,
                filename_match.group(1) if filename_match else None,
                type_match.group(1).strip() if type_match else None,
            )

        raise HttpError(HTTPStatus.BAD_REQUEST, f"Multipart field '{field_name}' not found.")

    def send_file(self, path: Path) -> None:
        resolved = path.resolve()
        if STATIC_DIR not in resolved.parents and resolved != STATIC_DIR / "index.html":
            raise HttpError(HTTPStatus.FORBIDDEN, "Forbidden.")
        if not resolved.exists() or not resolved.is_file():
            raise HttpError(HTTPStatus.NOT_FOUND, "File not found.")
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, status: int, detail: str) -> None:
        self.send_json({"detail": detail}, status)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "ollama_base_url": settings.ollama_base_url,
        "ollama_model": settings.ollama_model,
        "ollama_keep_alive": settings.ollama_keep_alive,
        "ollama_num_predict": settings.ollama_num_predict,
        "ollama_num_ctx": settings.ollama_num_ctx,
        "ollama_disable_thinking": settings.ollama_disable_thinking,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "say": bool(shutil.which("say")),
        "afconvert": bool(shutil.which("afconvert")),
    }


def config() -> dict[str, Any]:
    ollama_ok = False
    models: list[str] = []
    try:
        data = ollama_request("/api/tags", None, timeout=2)
        models = [item["name"] for item in data.get("models", []) if "name" in item]
        ollama_ok = True
    except Exception:
        pass
    return {
        "ollama_ok": ollama_ok,
        "ollama_model": settings.ollama_model,
        "ollama_keep_alive": settings.ollama_keep_alive,
        "ollama_num_predict": settings.ollama_num_predict,
        "ollama_num_ctx": settings.ollama_num_ctx,
        "ollama_disable_thinking": settings.ollama_disable_thinking,
        "available_models": models,
        "whisper_model": settings.whisper_model,
        "stt_provider": settings.stt_provider,
        "stt_language": settings.stt_language,
        "browser_stt_local": settings.browser_stt_local,
        "apple_stt_binary": settings.apple_stt_binary,
        "apple_live_stt_binary": settings.apple_live_stt_binary,
        "apple_stt_available": apple_stt_binary_path().exists(),
        "apple_live_stt_available": apple_live_stt_binary_path().exists(),
        "stt_offline": settings.stt_offline,
        "stt_disable_progress": settings.stt_disable_progress,
        "stt_command_configured": bool(settings.stt_command),
    }


def chat_response(transcript: str, response: str, audio: dict[str, str] | None) -> dict[str, Any]:
    return {
        "transcript": transcript,
        "response": response,
        "audio_base64": audio["base64"] if audio else None,
        "audio_mime": audio["mime"] if audio else None,
    }


def guess_suffix(filename: str | None, content_type: str | None) -> str:
    if filename and Path(filename).suffix:
        return Path(filename).suffix
    if content_type == "audio/webm":
        return ".webm"
    if content_type == "audio/mp4":
        return ".m4a"
    if content_type == "audio/wav":
        return ".wav"
    return ".audio"


def normalize_audio(input_path: Path, output_path: Path) -> Path:
    if not shutil.which("ffmpeg"):
        return input_path
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-vn",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise HttpError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Audio conversion failed: {proc.stderr[-600:]}")
    return output_path


def transcribe_audio(audio_path: Path) -> str:
    configure_stt_environment()

    if settings.stt_provider == "apple":
        return transcribe_with_apple_speech(audio_path)

    if settings.stt_command:
        return run_stt_command(audio_path)

    try:
        import mlx_whisper  # type: ignore
    except Exception as exc:
        raise HttpError(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "mlx_whisper is not installed in the Python environment that runs the server. "
            "Either install it with `python3 -m pip install mlx-whisper`, or set STT_COMMAND in .env "
            "to a Python interpreter where it is installed, for example: "
            "`STT_COMMAND=/path/to/python scripts/transcribe_mlx.py {file}`. "
            f"Import error: {exc}",
        ) from exc

    try:
        kwargs = {
            "path_or_hf_repo": settings.whisper_model,
            "fp16": settings.stt_fp16,
            "temperature": settings.stt_temperature,
            "condition_on_previous_text": settings.stt_condition_on_previous_text,
            "verbose": None,
        }
        if settings.stt_language:
            kwargs["language"] = settings.stt_language
        result = mlx_whisper.transcribe(str(audio_path), **kwargs)
    except TypeError:
        result = mlx_whisper.transcribe(str(audio_path), settings.whisper_model)
    except Exception as exc:
        raise HttpError(HTTPStatus.INTERNAL_SERVER_ERROR, f"Transcription failed: {exc}") from exc

    if isinstance(result, dict):
        return str(result.get("text", "")).strip()
    return str(result).strip()


def run_stt_command(audio_path: Path) -> str:
    command = settings.stt_command.format(file=str(audio_path))
    proc = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise HttpError(HTTPStatus.INTERNAL_SERVER_ERROR, f"STT command failed: {proc.stderr[-800:]}")
    return proc.stdout.strip()


def transcribe_with_apple_speech(audio_path: Path) -> str:
    helper_path = ensure_apple_stt_helper()
    locale = speech_locale(settings.stt_language)
    cmd = [
        str(helper_path),
        "--locale",
        locale,
        "--timeout",
        str(settings.apple_stt_timeout),
        str(audio_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=settings.apple_stt_timeout + 10,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Apple STT failed.").strip()
        raise HttpError(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            f"Apple on-device STT failed for {locale}: {detail}",
        )
    return proc.stdout.strip()


def ensure_apple_stt_helper() -> Path:
    helper_path = apple_stt_binary_path()
    if helper_path.exists():
        return helper_path

    build_script = ROOT / "scripts" / "build_apple_stt.sh"
    if not build_script.exists():
        raise HttpError(HTTPStatus.INTERNAL_SERVER_ERROR, f"Apple STT build script not found: {build_script}")

    proc = subprocess.run(
        ["bash", str(build_script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0 or not helper_path.exists():
        detail = (proc.stderr or proc.stdout or "Build failed.").strip()
        raise HttpError(HTTPStatus.INTERNAL_SERVER_ERROR, f"Could not build Apple STT helper: {detail}")
    return helper_path


def ensure_apple_live_stt_helper() -> Path:
    helper_path = apple_live_stt_binary_path()
    if helper_path.exists():
        return helper_path

    build_script = ROOT / "scripts" / "build_apple_stt.sh"
    if not build_script.exists():
        raise HttpError(HTTPStatus.INTERNAL_SERVER_ERROR, f"Apple STT build script not found: {build_script}")

    proc = subprocess.run(
        ["bash", str(build_script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0 or not helper_path.exists():
        detail = (proc.stderr or proc.stdout or "Build failed.").strip()
        raise HttpError(HTTPStatus.INTERNAL_SERVER_ERROR, f"Could not build Apple live STT helper: {detail}")
    return helper_path


def apple_stt_binary_path() -> Path:
    path = Path(settings.apple_stt_binary)
    if not path.is_absolute():
        path = ROOT / path
    return path


def apple_live_stt_binary_path() -> Path:
    path = Path(settings.apple_live_stt_binary)
    if not path.is_absolute():
        path = ROOT / path
    return path


def start_apple_live_stt() -> dict[str, Any]:
    global live_stt_process
    helper_path = ensure_apple_live_stt_helper()
    locale = speech_locale(settings.stt_language)

    with live_stt_lock:
        if live_stt_process is not None and live_stt_process.poll() is None:
            return {"ok": True, "already_running": True}

        live_stt_process = subprocess.Popen(
            [
                str(helper_path),
                "--locale",
                locale,
                "--timeout",
                str(settings.apple_live_stt_timeout),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    return {"ok": True, "locale": locale}


def stop_apple_live_stt() -> dict[str, Any]:
    process = current_live_stt_process()
    if process is None:
        return {"ok": True, "stopped": False}

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    clear_live_stt_process(process)
    return {"ok": True, "stopped": True}


def current_live_stt_process() -> subprocess.Popen[str] | None:
    with live_stt_lock:
        if live_stt_process is None:
            return None
        if live_stt_process.poll() is not None:
            return None
        return live_stt_process


def clear_live_stt_process(process: subprocess.Popen[str]) -> None:
    global live_stt_process
    with live_stt_lock:
        if live_stt_process is process:
            live_stt_process = None


def speech_locale(language: str) -> str:
    if not language:
        return "de-DE"
    if language == "de":
        return "de-DE"
    if language == "en":
        return "en-US"
    return language


def configure_stt_environment() -> None:
    if settings.stt_offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if settings.stt_disable_progress:
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        os.environ["HF_HUB_VERBOSITY"] = "error"


def ask_ollama(user_text: str) -> str:
    append_session_log("USER", user_text)
    user_message = build_user_message(user_text)
    messages.append({"role": "user", "content": user_message})
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,
        "options": {
            "temperature": settings.ollama_temperature,
            "num_predict": settings.ollama_num_predict,
            "num_ctx": settings.ollama_num_ctx,
        },
    }
    if settings.ollama_disable_thinking:
        payload["think"] = False
    try:
        started = time.perf_counter()
        data = ollama_request("/api/chat", payload, timeout=120)
        finished = time.perf_counter()
    except Exception as exc:
        messages.pop()
        raise HttpError(HTTPStatus.BAD_GATEWAY, f"Could not get Ollama response: {exc}") from exc

    assistant_text = extract_assistant_text(data).strip()
    if not assistant_text:
        messages.pop()
        thinking = extract_assistant_thinking(data).strip()
        hint = ""
        if thinking:
            hint = (
                " The model returned only thinking text. For Qwen thinking models, keep "
                "OLLAMA_DISABLE_THINKING=1 or increase OLLAMA_NUM_PREDICT."
            )
        raise HttpError(HTTPStatus.BAD_GATEWAY, f"Ollama returned no assistant text.{hint} Raw: {json.dumps(data)[:800]}")

    messages.append({"role": "assistant", "content": assistant_text})
    append_session_log("ASSISTANT", assistant_text)
    trim_history()
    print_ollama_timing(data, finished - started)
    return assistant_text


def append_session_log(role: str, text: str) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    normalized = text.strip()
    if not normalized:
        return

    with session_log_lock:
        new_file = not session_log_path.exists()
        with session_log_path.open("a", encoding="utf-8") as handle:
            if new_file:
                handle.write(f"# Local Voice Chat Session\n")
                handle.write(f"Started: {session_started_at:%Y-%m-%d %H:%M:%S}\n")
                handle.write(f"Model: {settings.ollama_model}\n\n")
            handle.write(f"[{timestamp}] {role}\n")
            handle.write(normalized)
            handle.write("\n\n")


def build_user_message(user_text: str) -> str:
    if not settings.ollama_disable_thinking:
        return user_text
    return f"{user_text}\n\n/no_think"


def print_ollama_timing(data: dict[str, Any], wall_time: float) -> None:
    eval_count = int(data.get("eval_count") or 0)
    eval_duration = int(data.get("eval_duration") or 0)
    load_duration = int(data.get("load_duration") or 0)
    prompt_eval_count = int(data.get("prompt_eval_count") or 0)
    prompt_eval_duration = int(data.get("prompt_eval_duration") or 0)

    eval_tps = eval_count / (eval_duration / 1_000_000_000) if eval_count and eval_duration else 0.0
    prompt_tps = (
        prompt_eval_count / (prompt_eval_duration / 1_000_000_000)
        if prompt_eval_count and prompt_eval_duration
        else 0.0
    )

    print(
        "ollama timings: "
        f"wall={wall_time:.2f}s "
        f"load={load_duration / 1_000_000_000:.2f}s "
        f"prompt_tokens={prompt_eval_count} "
        f"prompt_tps={prompt_tps:.1f} "
        f"eval_tokens={eval_count} "
        f"eval_tps={eval_tps:.1f}"
    )


def ollama_request(path: str, payload: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    url = f"{settings.ollama_base_url}{path}"
    if payload is None:
        request = urllib.request.Request(url, method="GET")
    else:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail[-1200:]}") from exc


def extract_assistant_text(data: dict[str, Any]) -> str:
    message = data.get("message")
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(data.get("response", ""))


def extract_assistant_thinking(data: dict[str, Any]) -> str:
    message = data.get("message")
    if isinstance(message, dict):
        return str(message.get("thinking", ""))
    return str(data.get("thinking", ""))


def trim_history(max_non_system_messages: int = 16) -> None:
    global messages
    system = messages[:1]
    rest = messages[1:]
    if len(rest) > max_non_system_messages:
        messages = system + rest[-max_non_system_messages:]


def synthesize_speech(text: str, output_dir: Path | None = None) -> dict[str, str] | None:
    if not shutil.which("say") or not shutil.which("afconvert"):
        return None

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if output_dir is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="voice-chat-tts-")
        base_dir = Path(temp_dir.name)
    else:
        base_dir = output_dir

    try:
        aiff_path = base_dir / "speech.aiff"
        wav_path = base_dir / "speech.wav"
        say_cmd = ["say", "-r", settings.tts_rate, "-o", str(aiff_path)]
        if settings.tts_voice:
            say_cmd.extend(["-v", settings.tts_voice])
        say_cmd.append(text)
        say_proc = subprocess.run(say_cmd, capture_output=True, text=True, check=False)
        if say_proc.returncode != 0:
            return None

        convert_cmd = ["afconvert", "-f", "WAVE", "-d", "LEI16", str(aiff_path), str(wav_path)]
        convert_proc = subprocess.run(convert_cmd, capture_output=True, text=True, check=False)
        if convert_proc.returncode != 0 or not wav_path.exists():
            return None

        return {"base64": base64.b64encode(wav_path.read_bytes()).decode("ascii"), "mime": "audio/wav"}
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main() -> None:
    server, port = bind_server(settings.host, settings.port)
    print(f"Local Voice Chat running at http://{settings.host}:{port}")
    print(f"Ollama: {settings.ollama_base_url} · model: {settings.ollama_model}")
    print(f"Session log: {session_log_path}")
    server.serve_forever()


def bind_server(host: str, preferred_port: int) -> tuple[ThreadingHTTPServer, int]:
    ports = [preferred_port] if preferred_port == 0 else range(preferred_port, preferred_port + 25)
    last_error: OSError | None = None

    for port in ports:
        try:
            return ThreadingHTTPServer((host, port), VoiceChatHandler), port
        except OSError as exc:
            last_error = exc
            if exc.errno != errno.EADDRINUSE:
                raise

    raise RuntimeError(f"No free port found from {preferred_port} to {preferred_port + 24}.") from last_error


if __name__ == "__main__":
    main()
