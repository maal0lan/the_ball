"""Local Whisper speech-to-text with lazy model loading."""
import logging
import threading

import numpy as np
import torch

log = logging.getLogger("backend.stt")
MODEL_ID = "openai/whisper-tiny"
_lock = threading.Lock()
_processor = None
_model = None


def _load():
    global _processor, _model
    if _model is not None:
        return
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

    log.info("Loading local speech model %s (first use may download it)…", MODEL_ID)
    _processor = AutoProcessor.from_pretrained(MODEL_ID)
    _model = AutoModelForSpeechSeq2Seq.from_pretrained(MODEL_ID, dtype=torch.float32)
    _model.to("cpu")
    _model.eval()
    log.info("Local speech model is ready")


def transcribe_pcm16(pcm: bytes, language: str = "en-US") -> str:
    """Transcribe little-endian, mono 16 kHz PCM16 bytes using local Whisper."""
    if not pcm or len(pcm) > 480_000 or len(pcm) % 2:
        raise ValueError("Voice clip must be between 1 sample and 15 seconds.")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    lang = (language or "en").split("-", 1)[0].lower()
    with _lock:
        _load()
        inputs = _processor(samples, sampling_rate=16_000, return_tensors="pt")
        with torch.inference_mode():
            ids = _model.generate(inputs.input_features, language=lang, task="transcribe")
        text = _processor.batch_decode(
            ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0].strip()
    return text
