'use strict';

class LocalSpeechInput {
  constructor(onTranscript, onError, onRecordingEnd = () => {}) {
    this.onTranscript = onTranscript;
    this.onError = onError;
    this.onRecordingEnd = onRecordingEnd;
    this.stream = null;
    this.context = null;
    this.source = null;
    this.processor = null;
    this.chunks = [];
    this.samples = 0;
    this.active = false;
    this.stopping = false;
    this.maxSamples = 15 * 16000;
    this.language = 'en-US';
    this.transcribe = false;
  }

  async start() {
    if (this.active) return;
    this.stopping = false;
    this.chunks = [];
    this.samples = 0;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('Microphone capture is unavailable in this build.');
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    try {
      this.context = new AudioContext();
      await this.context.resume();
      this.source = this.context.createMediaStreamSource(this.stream);
      this.processor = this.context.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = event => this.capture(event);
      this.sink = this.context.createGain();
      this.sink.gain.value = 0;
      this.source.connect(this.processor);
      this.processor.connect(this.sink);
      this.sink.connect(this.context.destination);
      this.active = true;
    } catch (error) {
      this.cleanup();
      throw error;
    }
  }

  capture(event) {
    if (!this.active) return;
    const input = event.inputBuffer.getChannelData(0);
    const ratio = 16000 / this.context.sampleRate;
    const targetLength = Math.floor(input.length * ratio);
    const output = new Float32Array(targetLength);
    for (let i = 0; i < targetLength; i++) {
      const sourcePosition = i / ratio;
      const left = Math.floor(sourcePosition);
      const fraction = sourcePosition - left;
      output[i] = input[left] * (1 - fraction) + input[Math.min(left + 1, input.length - 1)] * fraction;
    }
    const count = Math.min(targetLength, this.maxSamples - this.samples);
    const pcm = new Int16Array(count);
    for (let i = 0; i < count; i++) pcm[i] = Math.max(-1, Math.min(1, output[i])) * 32767;
    this.chunks.push(pcm);
    this.samples += pcm.length;
    if (this.samples >= this.maxSamples) this.stop(true);
  }

  async stop(transcribe = false) {
    if (!this.active || this.stopping) return;
    this.transcribe = transcribe;
    this.stopping = true;
    this.active = false;
    this.onRecordingEnd();
    this.cleanup();
    try {
      if (!this.samples) throw new Error('No audio was captured. Try again and speak closer to the microphone.');
      const pcm = new Int16Array(this.samples);
      let offset = 0;
      for (const chunk of this.chunks) { pcm.set(chunk, offset); offset += chunk.length; }
      const text = await window.crystal.backend.transcribe(pcm.buffer, this.language);
      if (text.trim() && this.transcribe) this.onTranscript(text.trim());
      else if (this.transcribe) throw new Error('No speech was detected. Try again.');
    } catch (error) {
      this.onError(error);
    } finally {
      this.chunks = [];
      this.samples = 0;
      this.stopping = false;
      this.transcribe = false;
    }
  }

  cleanup() {
    if (this.processor) { this.processor.disconnect(); this.processor.onaudioprocess = null; this.processor = null; }
    if (this.source) { this.source.disconnect(); this.source = null; }
    if (this.sink) { this.sink.disconnect(); this.sink = null; }
    if (this.stream) { this.stream.getTracks().forEach(track => track.stop()); this.stream = null; }
    if (this.context) { this.context.close().catch(() => {}); this.context = null; }
  }
}

window.LocalSpeechInput = LocalSpeechInput;
