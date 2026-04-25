import type {
  ClientStartMessage,
  ClientStopMessage,
  ServerMessage
} from "./protocol";

export type MessageHandler = (message: ServerMessage) => void;

export class StreamingAsrClient {
  private socket?: WebSocket;

  connect(url: string, startMessage: ClientStartMessage, onMessage: MessageHandler): Promise<void> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      socket.binaryType = "arraybuffer";

      socket.onopen = () => {
        socket.send(JSON.stringify(startMessage));
        resolve();
      };

      socket.onerror = () => {
        reject(new Error("WebSocket connection failed."));
      };

      socket.onmessage = (event) => {
        if (typeof event.data !== "string") {
          return;
        }
        onMessage(JSON.parse(event.data) as ServerMessage);
      };

      this.socket = socket;
    });
  }

  sendAudio(chunk: ArrayBuffer): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(chunk);
    }
  }

  stop(): void {
    const message: ClientStopMessage = { type: "stop" };
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  close(): void {
    this.socket?.close();
    this.socket = undefined;
  }
}

