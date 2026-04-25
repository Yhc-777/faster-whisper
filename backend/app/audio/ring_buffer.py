from __future__ import annotations

import numpy as np


class RingBuffer:
    """A mono PCM int16 ring buffer addressed by absolute audio time."""

    def __init__(self, sample_rate: int, max_seconds: float) -> None:
        self.sample_rate = sample_rate
        self.max_samples = int(sample_rate * max_seconds)
        self._samples = np.empty(0, dtype=np.int16)
        self._start_sample = 0
        self._total_samples = 0

    @property
    def duration(self) -> float:
        return self._samples.size / self.sample_rate

    @property
    def start_time(self) -> float:
        return self._start_sample / self.sample_rate

    @property
    def end_time(self) -> float:
        return self._total_samples / self.sample_rate

    def append_pcm16(self, payload: bytes) -> None:
        if not payload:
            return
        samples = np.frombuffer(payload, dtype="<i2").copy()
        self._samples = np.concatenate((self._samples, samples))
        self._total_samples += samples.size
        self._trim()

    def get_window(self, start_time: float, end_time: float) -> np.ndarray:
        start_sample = max(int(start_time * self.sample_rate), self._start_sample)
        end_sample = min(int(end_time * self.sample_rate), self._total_samples)
        if end_sample <= start_sample:
            return np.empty(0, dtype=np.int16)

        local_start = start_sample - self._start_sample
        local_end = end_sample - self._start_sample
        return self._samples[local_start:local_end].copy()

    def get_all(self) -> tuple[np.ndarray, float, float]:
        return self._samples.copy(), self.start_time, self.end_time

    def _trim(self) -> None:
        if self._samples.size <= self.max_samples:
            return

        overflow = self._samples.size - self.max_samples
        self._samples = self._samples[overflow:]
        self._start_sample += overflow

