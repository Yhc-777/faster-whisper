from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class StartMessage(BaseModel):
    type: Literal["start"]
    session_id: Optional[str] = None
    sample_rate: int = 16000
    channels: int = 1
    encoding: Literal["pcm_s16le"] = "pcm_s16le"
    language: Optional[str] = None
    task: Literal["transcribe", "translate"] = "transcribe"
    window_sec: Optional[float] = Field(default=None, gt=0)
    hop_sec: Optional[float] = Field(default=None, gt=0)


class StopMessage(BaseModel):
    type: Literal["stop"]


class PingMessage(BaseModel):
    type: Literal["ping"]
    timestamp: Optional[float] = None


class TranscriptMessage(BaseModel):
    type: Literal["partial", "final"]
    session_id: str
    text: str
    start: float
    end: float
    revision: int
    latency_ms: int


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str

