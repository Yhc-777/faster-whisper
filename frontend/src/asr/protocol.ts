export type ClientStartMessage = {
  type: "start";
  session_id: string;
  sample_rate: 16000;
  channels: 1;
  encoding: "pcm_s16le";
  language: string;
  task: "transcribe" | "translate";
  window_sec: number;
  hop_sec: number;
};

export type ClientStopMessage = {
  type: "stop";
};

export type ServerReadyMessage = {
  type: "ready";
  session_id: string;
};

export type ServerTranscriptMessage = {
  type: "partial" | "final";
  session_id: string;
  text: string;
  start: number;
  end: number;
  revision: number;
  latency_ms: number;
};

export type ServerErrorMessage = {
  type: "error";
  code: string;
  message: string;
};

export type ServerMessage =
  | ServerReadyMessage
  | ServerTranscriptMessage
  | ServerErrorMessage
  | { type: "pong"; timestamp: number };

