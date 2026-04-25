from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuntimeMetrics:
    active_sessions: int = 0
    rejected_sessions: int = 0
    queued_requests: int = 0
    inference_errors: int = 0


metrics = RuntimeMetrics()

