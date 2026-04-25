from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class VadState:
    is_speaking: bool = False
    speech_seconds: float = 0.0
    silence_seconds: float = 0.0


class EnergyVad:
    """A lightweight energy VAD for stream control, not a replacement for model VAD."""

    def __init__(
        self,
        sample_rate: int,
        threshold: float = 0.008,
        min_speech_sec: float = 0.3,
        min_silence_sec: float = 0.8,
    ) -> None:
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_speech_sec = min_speech_sec
        self.min_silence_sec = min_silence_sec
        self.state = VadState()

    def update(self, samples: np.ndarray) -> VadState:
        if samples.size == 0:
            return self.state

        seconds = samples.size / self.sample_rate
        rms = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768.0) ** 2)))
        if rms >= self.threshold:
            self.state.speech_seconds += seconds
            self.state.silence_seconds = 0.0
            if self.state.speech_seconds >= self.min_speech_sec:
                self.state.is_speaking = True
        else:
            self.state.silence_seconds += seconds
            if self.state.silence_seconds >= self.min_silence_sec:
                self.state.is_speaking = False
                self.state.speech_seconds = 0.0

        return self.state

