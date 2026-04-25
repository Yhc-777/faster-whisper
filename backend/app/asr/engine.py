from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Optional

import numpy as np

from backend.app.asr.postprocess import clean_asr_text
from backend.app.config import Settings


@dataclass(order=True)
class InferenceRequest:
    priority: int
    created_at: float
    session_id: str = field(compare=False)
    audio: np.ndarray = field(compare=False)
    start: float = field(compare=False)
    end: float = field(compare=False)
    is_final: bool = field(compare=False)
    language: str = field(compare=False)
    task: str = field(compare=False)
    result_queue: asyncio.Queue = field(compare=False)


@dataclass
class InferenceResult:
    session_id: str
    text: str
    start: float
    end: float
    is_final: bool
    inference_ms: int
    queue_wait_ms: int


class FasterWhisperEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._load_lock = asyncio.Lock()

    async def transcribe(self, request: InferenceRequest) -> InferenceResult:
        started = time.perf_counter()
        model = await self._get_model()
        audio = _pcm16_to_float32(request.audio)
        beam_size = (
            self.settings.beam_size_final
            if request.is_final
            else self.settings.beam_size_partial
        )

        text = await asyncio.to_thread(
            self._transcribe_sync,
            model,
            audio,
            request.language,
            request.task,
            beam_size,
            request.is_final,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        queue_wait_ms = int((started - request.created_at) * 1000)
        return InferenceResult(
            session_id=request.session_id,
            text=text,
            start=request.start,
            end=request.end,
            is_final=request.is_final,
            inference_ms=elapsed_ms,
            queue_wait_ms=queue_wait_ms,
        )

    async def _get_model(self):
        if self._model is not None:
            return self._model

        async with self._load_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = await asyncio.to_thread(
                    WhisperModel,
                    self.settings.model_path,
                    device=self.settings.device,
                    compute_type=self.settings.compute_type,
                )
        return self._model

    def _transcribe_sync(
        self,
        model,
        audio: np.ndarray,
        language: str,
        task: str,
        beam_size: int,
        is_final: bool,
    ) -> str:
        segments, _ = model.transcribe(
            audio,
            task=task,
            language=language,
            beam_size=beam_size,
            best_of=1,
            temperature=0.0,
            vad_filter=self.settings.vad_filter if is_final else False,
            condition_on_previous_text=self.settings.condition_on_previous_text,
            word_timestamps=self.settings.enable_word_timestamps,
        )
        return clean_asr_text("".join(segment.text for segment in segments))


class InferenceManager:
    def __init__(self, engine: FasterWhisperEngine, max_queue_size: int) -> None:
        self.engine = engine
        self.queue: asyncio.PriorityQueue[InferenceRequest] = asyncio.PriorityQueue(
            maxsize=max_queue_size
        )
        self._workers: list[asyncio.Task] = []

    def start(self, worker_count: int) -> None:
        if self._workers:
            return
        for index in range(worker_count):
            self._workers.append(asyncio.create_task(self._run_worker(index)))

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def submit(self, request: InferenceRequest) -> bool:
        try:
            self.queue.put_nowait(request)
            return True
        except asyncio.QueueFull:
            return False

    async def _run_worker(self, index: int) -> None:
        while True:
            request = await self.queue.get()
            try:
                result = await self.engine.transcribe(request)
                await request.result_queue.put(result)
            except Exception as exc:  # noqa: BLE001 - keep stream alive on inference errors.
                await request.result_queue.put(exc)
            finally:
                self.queue.task_done()


def build_request(
    *,
    session_id: str,
    audio: np.ndarray,
    start: float,
    end: float,
    is_final: bool,
    language: str,
    task: str,
    result_queue: asyncio.Queue,
) -> Optional[InferenceRequest]:
    if audio.size == 0:
        return None
    return InferenceRequest(
        priority=0 if is_final else 10,
        created_at=time.perf_counter(),
        session_id=session_id,
        audio=audio,
        start=start,
        end=end,
        is_final=is_final,
        language=language,
        task=task,
        result_queue=result_queue,
    )


def _pcm16_to_float32(samples: np.ndarray) -> np.ndarray:
    return samples.astype(np.float32) / 32768.0

