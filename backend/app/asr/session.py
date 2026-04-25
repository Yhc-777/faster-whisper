from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from uuid import uuid4

import numpy as np

from backend.app.asr.engine import InferenceRequest, build_request
from backend.app.asr.stitcher import TranscriptStitcher
from backend.app.audio.ring_buffer import RingBuffer
from backend.app.audio.vad import EnergyVad
from backend.app.config import Settings
from backend.app.schemas.messages import StartMessage


@dataclass
class Window:
    audio: np.ndarray
    start: float
    end: float
    is_final: bool


class StreamingSession:
    def __init__(self, start: StartMessage, settings: Settings) -> None:
        self.id = start.session_id or str(uuid4())
        self.settings = settings
        self.sample_rate = start.sample_rate
        self.language = start.language or settings.language
        self.task = start.task or settings.task
        self.window_sec = start.window_sec or settings.window_sec
        self.hop_sec = start.hop_sec or settings.hop_sec

        self.buffer = RingBuffer(
            sample_rate=self.sample_rate,
            max_seconds=settings.max_buffer_sec,
        )
        self.vad = EnergyVad(sample_rate=self.sample_rate)
        self.stitcher = TranscriptStitcher()
        self.results: asyncio.Queue = asyncio.Queue()
        self.final_sent = asyncio.Event()
        self.created_at = time.time()
        self.last_partial_end = 0.0
        self.closed = False

    def append_audio(self, payload: bytes) -> None:
        self.buffer.append_pcm16(payload)
        latest_start = max(self.buffer.end_time - self.settings.chunk_ms / 1000, 0)
        latest = self.buffer.get_window(latest_start, self.buffer.end_time)
        self.vad.update(latest)

    def next_partial_request(self) -> InferenceRequest | None:
        window = self._next_partial_window()
        if window is None:
            return None
        return build_request(
            session_id=self.id,
            audio=window.audio,
            start=window.start,
            end=window.end,
            is_final=False,
            language=self.language,
            task=self.task,
            result_queue=self.results,
        )

    def final_request(self) -> InferenceRequest | None:
        samples, start, end = self.buffer.get_all()
        return build_request(
            session_id=self.id,
            audio=samples,
            start=start,
            end=end,
            is_final=True,
            language=self.language,
            task=self.task,
            result_queue=self.results,
        )

    def _next_partial_window(self) -> Window | None:
        end = self.buffer.end_time
        if end < self.window_sec:
            return None
        if end - self.last_partial_end < self.hop_sec:
            return None

        start = max(end - self.window_sec, self.buffer.start_time)
        samples = self.buffer.get_window(start, end)
        if samples.size < int(self.sample_rate * min(self.window_sec, end) * 0.5):
            return None

        self.last_partial_end = end
        return Window(audio=samples, start=start, end=end, is_final=False)

