"""
Text cleanup, sentence splitting, and the Phonon TTS engine.

NOTE: the Phonon calls below are carried over unchanged from your original main.py
(AutoProcessor / AutoModelForTextToWaveform / default-voice.safetensors). They depend
on the pinned Transformers revision in requirements.txt and could not be executed in
the environment this project was written in — see docs "Known unverified parts".
"""
import asyncio
import io
import logging
import re
import threading
import wave

import numpy as np

from config import settings

log = logging.getLogger("backend.tts")

_CODE_BLOCK = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_MD_MARK = re.compile(r"(^|\s)[#>*\-+]+\s+|[*_~]{1,3}")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")
_SENT_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+|\n{1,}")


def clean_for_speech(text: str) -> str:
    if settings.get("voice.skipCode"):
        text = _CODE_BLOCK.sub(" code omitted. ", text)
    if settings.get("voice.stripMarkdown"):
        text = _LINK.sub(r"\1", text)
        text = _INLINE_CODE.sub(r"\1", text)
        text = _MD_MARK.sub(r"\1", text)
    text = _URL.sub("link", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


class SentenceSplitter:
    """Feed streamed text; get complete sentences back (long ones split at commas/spaces)."""

    def __init__(self) -> None:
        self.buf = ""

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out: list[str] = []
        while True:
            m = _SENT_END.search(self.buf)
            if not m:
                break
            piece, self.buf = self.buf[:m.start()].strip(), self.buf[m.end():]
            if piece:
                out.append(piece)
        limit = int(settings.get("voice.maxChunkChars"))
        while len(self.buf) > limit * 1.5:
            cut = max(self.buf.rfind(", ", 0, limit), self.buf.rfind(" ", 0, limit))
            cut = cut if cut > 20 else limit
            out.append(self.buf[:cut].strip())
            self.buf = self.buf[cut:].lstrip(", ")
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []


class PhononTTS:
    def __init__(self) -> None:
        self.model_id: str | None = None
        self.processor = None
        self.model = None
        self.voice_latents = None
        self.lock = threading.Lock()
        self.loaded_ms = 0

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def unload(self) -> None:
        with self.lock:
            self.model = self.processor = self.voice_latents = None
            self.model_id = None
        log.info("Phonon unloaded")

    def _load(self) -> None:
        want = str(settings.get("voice.model"))
        if self.model is not None and self.model_id == want:
            return
        import time
        t0 = time.time()
        try:
            from transformers import AutoProcessor, AutoModelForTextToWaveform
        except ImportError as exc:
            raise RuntimeError("Transformers is missing Gradium Phonon support. "
                               "Reinstall backend/requirements.txt.") from exc
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        import torch
        log.info("Loading Phonon model %s (first time can download several hundred MB)…", want)
        dev = str(settings.get("voice.device"))
        kwargs = {"device_map": "auto"} if dev == "auto" else {}
        self.processor = AutoProcessor.from_pretrained(want)
        self.model = AutoModelForTextToWaveform.from_pretrained(want, **kwargs)
        if dev != "auto":
            self.model = self.model.to(dev)
        voice_path = hf_hub_download(want, "default-voice.safetensors")
        self.voice_latents = load_file(voice_path)["speaker_wavs"][0].T.float()
        self.model.eval()
        self.model_id = want
        self.loaded_ms = int((time.time() - t0) * 1000)
        log.info("Phonon ready in %.1fs on %s", self.loaded_ms / 1000, getattr(self.model, "device", "?"))

    def _synth(self, text: str) -> bytes:
        import torch
        with self.lock:
            self._load()
            conv = [{"role": "user", "content": [{"type": "audio"}, {"type": "text", "text": text}]}]
            inputs = self.processor.apply_chat_template(
                conv, tokenize=True, return_dict=True, add_generation_prompt=True,
                processor_kwargs={"audio_prompt_latents": [self.voice_latents]},
            ).to(self.model.device)
            with torch.inference_mode():
                out = self.model.generate(**inputs)
                audio = self.processor.decode(out.audio_latents, out.audio_latents_mask)
        if isinstance(audio, (list, tuple)):
            audio = audio[0]
        if hasattr(audio, "detach"):
            audio = audio.detach().float().cpu().numpy()
        samples = np.asarray(audio, dtype=np.float32).squeeze()
        if samples.size == 0:
            raise RuntimeError("Phonon produced empty audio.")
        speed = float(settings.get("voice.speed"))
        if speed and abs(speed - 1.0) > 1e-3:
            n = max(1, int(samples.size / speed))
            samples = np.interp(np.linspace(0, samples.size - 1, n), np.arange(samples.size), samples).astype(np.float32)
        return samples_to_wav(samples, int(settings.get("voice.sampleRate")))

    async def synthesize(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synth, text)


def samples_to_wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


phonon = PhononTTS()
