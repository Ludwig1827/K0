class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._bufferSize = 4096;
    this._buffer = new Float32Array(this._bufferSize);
    this._writeIndex = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const channelData = input[0]; // mono

    for (let i = 0; i < channelData.length; i++) {
      this._buffer[this._writeIndex++] = channelData[i];
      if (this._writeIndex >= this._bufferSize) {
        // Resample from sampleRate to 16000 and convert to 16-bit PCM
        const pcm16 = this._resampleAndConvert(this._buffer);
        this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
        this._buffer = new Float32Array(this._bufferSize);
        this._writeIndex = 0;
      }
    }
    return true;
  }

  _resampleAndConvert(floatData) {
    const inputRate = sampleRate; // global in AudioWorklet scope
    const outputRate = 16000;
    const ratio = inputRate / outputRate;
    const outputLength = Math.floor(floatData.length / ratio);
    const pcm = new Int16Array(outputLength);

    for (let i = 0; i < outputLength; i++) {
      const srcIndex = Math.floor(i * ratio);
      let sample = floatData[srcIndex];
      // Clamp
      sample = Math.max(-1, Math.min(1, sample));
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }
    return pcm;
  }
}

registerProcessor("audio-capture-processor", AudioCaptureProcessor);
