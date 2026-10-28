# Room for Improvement

## Making speech start sooner

The local Phonon model can take several seconds to synthesize a chunk, especially on CPU.
Use **Settings → Voice → Test voice** to measure TTS by itself and compare it with the time
spent waiting for the assistant's text.

Recommended checks:

- Set **Voice engine** to `system` for the fastest response, then choose an installed OS voice.
  Windows' installed voices may include feminine-sounding options; exact availability depends
  on the Windows language and speech packages. Test a few voices rather than relying on a
  gender label, which the OS voice API does not provide consistently.
- If you prefer Phonon, turn on **Preload voice model at start**. Model loading is moved to
  backend startup, so the first reply does not have to pay the whole cold-load cost.
- Keep **Speak while thinking** enabled. Try **Max characters per spoken chunk** around
  `100–140` if long sentences are slow to begin; smaller chunks can sound less natural.
- Use `auto` for **Compute device** unless you have verified that the installed PyTorch build
  supports your GPU. On a supported NVIDIA setup, `cuda` can improve synthesis time.
- Keep replies concise and include natural sentence breaks. TTS only receives a sentence once
  the model has emitted its punctuation; it cannot start speaking an unfinished sentence.

If voice testing itself takes 5–10 seconds repeatedly, the bottleneck is model inference rather
than the LLM's response generation. `system` is the available low-latency option today. Phonon
currently has one bundled speaker; selectable Phonon speakers/styles require a model that
provides additional speaker conditioning.

## Later improvements

- Add per-sentence timing diagnostics and compare cold vs. warm Phonon inference.
- Evaluate a lower-latency local TTS engine with multiple licensed speakers.
- Explore streaming/chunked audio synthesis so playback can start before a full sentence is
  synthesized, while preserving natural prosody.
- Store voice credentials using the operating system's secure credential store instead of
  plain-text settings.
