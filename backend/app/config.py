from dataclasses import dataclass
import os


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    model_path: str = os.getenv(
        "ASR_MODEL_PATH",
        "/media/u/bak1/6t/haochen/faster-whisper/models/faster-whisper-large-v3",
    )
    device: str = os.getenv("ASR_DEVICE", "cuda")
    compute_type: str = os.getenv("ASR_COMPUTE_TYPE", "float16")
    language: str = os.getenv("ASR_LANGUAGE", "zh")
    task: str = os.getenv("ASR_TASK", "transcribe")

    sample_rate: int = int(os.getenv("ASR_SAMPLE_RATE", "16000"))
    chunk_ms: int = int(os.getenv("ASR_CHUNK_MS", "100"))
    window_sec: float = float(os.getenv("ASR_WINDOW_SEC", "3.0"))
    hop_sec: float = float(os.getenv("ASR_HOP_SEC", "1.0"))
    overlap_sec: float = float(os.getenv("ASR_OVERLAP_SEC", "1.0"))
    max_buffer_sec: float = float(os.getenv("ASR_MAX_BUFFER_SEC", "30.0"))

    beam_size_partial: int = int(os.getenv("ASR_BEAM_SIZE_PARTIAL", "1"))
    beam_size_final: int = int(os.getenv("ASR_BEAM_SIZE_FINAL", "5"))
    condition_on_previous_text: bool = _get_bool(
        "ASR_CONDITION_ON_PREVIOUS_TEXT", False
    )
    enable_word_timestamps: bool = _get_bool("ASR_ENABLE_WORD_TIMESTAMPS", True)
    vad_filter: bool = _get_bool("ASR_VAD_FILTER", False)

    max_sessions: int = int(os.getenv("ASR_MAX_SESSIONS", "8"))
    queue_size: int = int(os.getenv("ASR_QUEUE_SIZE", "32"))
    worker_count: int = int(os.getenv("ASR_WORKER_COUNT", "1"))

    frontend_dist: str = os.getenv(
        "ASR_FRONTEND_DIST",
        "/media/u/bak1/6t/haochen/faster-whisper/frontend/dist",
    )


settings = Settings()

