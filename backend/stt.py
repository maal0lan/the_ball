"""Local speech-to-text with faster-whisper (int8, CPU). Model loads once, in the background."""
import logging
import os
import threading

import numpy as np

log = logging.getLogger("backend.stt")
_lock = threading.Lock()
_models: dict = {}


def _model_name(lang: str) -> str:
    return "tiny.en" if lang == "en" else "base"      # tiny.en is English-only


def get_model(name: str):
    from faster_whisper import WhisperModel
    with _lock:
        if name not in _models:
            log.info("Loading speech model %s…", name)
            _models[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                         cpu_threads=max(2, (os.cpu_count() or 4) // 2))
            log.info("Speech model %s ready", name)
        return _models[name]


def preload() -> None:
    try:
        get_model("tiny.en")
    except Exception:
        log.exception("Speech model preload failed")


def transcribe_pcm16(pcm: bytes, language: str = "en-US") -> str:
    if not pcm or len(pcm) > 480_000 or len(pcm) % 2:
        raise ValueError("Voice clip must be between 1 sample and 15 seconds.")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    lang = (language or "en").split("-", 1)[0].lower()
    segments, _ = get_model(_model_name(lang)).transcribe(
        samples, language=lang, beam_size=1, vad_filter=True,
        condition_on_previous_text=False, without_timestamps=True)
    return " ".join(s.text.strip() for s in segments).strip()