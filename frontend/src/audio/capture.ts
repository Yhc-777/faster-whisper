import { floatToPcm16 } from "./pcm";
import { downsampleTo16k } from "./resample";

export type AudioChunkHandler = (chunk: ArrayBuffer) => void;

export class MicrophoneCapture {
  private audioContext?: AudioContext;
  private source?: MediaStreamAudioSourceNode;
  private processor?: AudioWorkletNode;
  private stream?: MediaStream;
  private pendingSamples: number[] = [];
  private readonly outputChunkSamples = 1600;

  async start(onChunk: AudioChunkHandler): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    this.audioContext = new AudioContext();
    await this.audioContext.audioWorklet.addModule(
      new URL("./pcm-worklet.js", import.meta.url)
    );
    this.source = this.audioContext.createMediaStreamSource(this.stream);
    this.processor = new AudioWorkletNode(
      this.audioContext,
      "pcm-capture-processor"
    );
    this.processor.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (!this.audioContext) {
        return;
      }
      const downsampled = downsampleTo16k(event.data, this.audioContext.sampleRate);
      this.emitFixedChunks(downsampled, onChunk);
    };

    this.source.connect(this.processor);
    this.processor.connect(this.audioContext.destination);
  }

  async stop(): Promise<void> {
    this.processor?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    await this.audioContext?.close();

    this.processor = undefined;
    this.source = undefined;
    this.stream = undefined;
    this.audioContext = undefined;
    this.pendingSamples = [];
  }

  private emitFixedChunks(samples: Float32Array, onChunk: AudioChunkHandler): void {
    for (const sample of samples) {
      this.pendingSamples.push(sample);
    }

    while (this.pendingSamples.length >= this.outputChunkSamples) {
      const chunk = this.pendingSamples.slice(0, this.outputChunkSamples);
      this.pendingSamples = this.pendingSamples.slice(this.outputChunkSamples);
      onChunk(floatToPcm16(Float32Array.from(chunk)));
    }
  }
}

