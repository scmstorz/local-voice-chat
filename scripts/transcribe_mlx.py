from __future__ import annotations

import os
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/transcribe_mlx.py /path/to/audio.wav", file=sys.stderr)
        return 2

    try:
        import mlx_whisper  # type: ignore
    except Exception as exc:
        print(f"Could not import mlx_whisper: {exc}", file=sys.stderr)
        return 1

    audio_path = sys.argv[1]
    model = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx")
    language = os.getenv("STT_LANGUAGE", "").strip()
    fp16 = os.getenv("STT_FP16", "1").strip().lower() in {"1", "true", "yes", "on"}
    temperature = float(os.getenv("STT_TEMPERATURE", "0"))
    condition_on_previous_text = os.getenv("STT_CONDITION_ON_PREVIOUS_TEXT", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if os.getenv("STT_OFFLINE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if os.getenv("STT_DISABLE_PROGRESS", "1").strip().lower() in {"1", "true", "yes", "on"}:
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        os.environ["HF_HUB_VERBOSITY"] = "error"

    try:
        try:
            kwargs = {
                "path_or_hf_repo": model,
                "fp16": fp16,
                "temperature": temperature,
                "condition_on_previous_text": condition_on_previous_text,
                "verbose": None,
            }
            if language:
                kwargs["language"] = language
            result = mlx_whisper.transcribe(audio_path, **kwargs)
        except TypeError:
            result = mlx_whisper.transcribe(audio_path, model)
    except Exception as exc:
        print(f"Transcription failed: {exc}", file=sys.stderr)
        return 1

    if isinstance(result, dict):
        print(str(result.get("text", "")).strip())
    else:
        print(str(result).strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
