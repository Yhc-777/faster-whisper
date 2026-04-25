import type { ServerMessage, ServerTranscriptMessage } from "../asr/protocol";

export class LiveTranscript {
  private committed = "";
  private partial = "";

  constructor(
    private readonly status: HTMLElement,
    private readonly finalText: HTMLElement,
    private readonly partialText: HTMLElement,
    private readonly latency: HTMLElement
  ) {}

  handle(message: ServerMessage): void {
    if (message.type === "ready") {
      this.status.textContent = `已连接：${message.session_id}`;
      return;
    }

    if (message.type === "error") {
      this.status.textContent = `错误：${message.code} ${message.message}`;
      return;
    }

    if (message.type === "partial" || message.type === "final") {
      this.renderTranscript(message);
    }
  }

  setStatus(text: string): void {
    this.status.textContent = text;
  }

  reset(): void {
    this.committed = "";
    this.partial = "";
    this.finalText.textContent = "";
    this.partialText.textContent = "";
    this.latency.textContent = "-";
  }

  private renderTranscript(message: ServerTranscriptMessage): void {
    if (message.type === "final") {
      this.committed = message.text;
      this.partial = "";
    } else {
      this.partial = message.text;
    }

    this.finalText.textContent = this.committed;
    this.partialText.textContent = this.partial;
    this.latency.textContent = `${message.latency_ms} ms`;
  }
}

