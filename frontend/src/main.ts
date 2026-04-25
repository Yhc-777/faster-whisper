import { StreamingAsrClient } from "./asr/client";
import type { ClientStartMessage } from "./asr/protocol";
import { MicrophoneCapture } from "./audio/capture";
import { LiveTranscript } from "./components/LiveTranscript";
import "./styles.css";

document.querySelector<HTMLDivElement>("#app")!.innerHTML = `
  <main class="page">
    <section class="panel">
      <h1>Streaming ASR</h1>
      <p class="hint">浏览器采集麦克风音频，发送 16kHz mono PCM 到 faster-whisper 后端。</p>

      <div class="controls">
        <label>
          WebSocket
          <input id="ws-url" value="${defaultWebSocketUrl()}" />
        </label>
        <label>
          语言
          <input id="language" value="zh" />
        </label>
        <label>
          窗口秒数
          <input id="window-sec" type="number" min="1" step="0.5" value="3" />
        </label>
        <label>
          Hop 秒数
          <input id="hop-sec" type="number" min="0.2" step="0.1" value="1" />
        </label>
      </div>

      <div class="buttons">
        <button id="start">开始识别</button>
        <button id="stop" disabled>停止</button>
      </div>

      <dl class="status-grid">
        <div>
          <dt>状态</dt>
          <dd id="status">未连接</dd>
        </div>
        <div>
          <dt>最近延迟</dt>
          <dd id="latency">-</dd>
        </div>
      </dl>

      <section class="transcript">
        <h2>Final</h2>
        <p id="final-text"></p>
        <h2>Partial</h2>
        <p id="partial-text"></p>
      </section>
    </section>
  </main>
`;

const startButton = document.querySelector<HTMLButtonElement>("#start")!;
const stopButton = document.querySelector<HTMLButtonElement>("#stop")!;
const wsUrlInput = document.querySelector<HTMLInputElement>("#ws-url")!;
const languageInput = document.querySelector<HTMLInputElement>("#language")!;
const windowSecInput = document.querySelector<HTMLInputElement>("#window-sec")!;
const hopSecInput = document.querySelector<HTMLInputElement>("#hop-sec")!;

const view = new LiveTranscript(
  document.querySelector<HTMLElement>("#status")!,
  document.querySelector<HTMLElement>("#final-text")!,
  document.querySelector<HTMLElement>("#partial-text")!,
  document.querySelector<HTMLElement>("#latency")!
);

let client: StreamingAsrClient | undefined;
let capture: MicrophoneCapture | undefined;
let pendingStop = false;

startButton.addEventListener("click", async () => {
  view.reset();
  view.setStatus("正在连接...");
  startButton.disabled = true;

  try {
    client = new StreamingAsrClient();
    const startMessage: ClientStartMessage = {
      type: "start",
      session_id: crypto.randomUUID(),
      sample_rate: 16000,
      channels: 1,
      encoding: "pcm_s16le",
      language: languageInput.value || "zh",
      task: "transcribe",
      window_sec: Number(windowSecInput.value || 3),
      hop_sec: Number(hopSecInput.value || 1)
    };

    await client.connect(wsUrlInput.value, startMessage, (message) => {
      view.handle(message);
      if (pendingStop && message.type === "final") {
        pendingStop = false;
        client?.close();
        client = undefined;
        startButton.disabled = false;
        view.setStatus("已停止");
      }
    });

    capture = new MicrophoneCapture();
    await capture.start((chunk) => client?.sendAudio(chunk));

    view.setStatus("正在识别...");
    stopButton.disabled = false;
  } catch (error) {
    view.setStatus(error instanceof Error ? error.message : String(error));
    startButton.disabled = false;
    stopButton.disabled = true;
    client?.close();
    client = undefined;
  }
});

stopButton.addEventListener("click", async () => {
  stopButton.disabled = true;
  view.setStatus("正在生成 final...");
  await capture?.stop();
  capture = undefined;
  pendingStop = true;
  client?.stop();
  window.setTimeout(() => {
    if (!pendingStop) {
      return;
    }
    pendingStop = false;
    client?.close();
    client = undefined;
    startButton.disabled = false;
    view.setStatus("已停止，未收到 final 或等待超时");
  }, 60000);
});

function defaultWebSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/asr/stream`;
}

