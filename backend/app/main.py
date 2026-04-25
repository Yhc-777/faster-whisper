from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.websocket import router as websocket_router
from backend.app.asr.engine import FasterWhisperEngine, InferenceManager
from backend.app.config import settings
from backend.app.observability.metrics import metrics


app = FastAPI(title="Streaming faster-whisper ASR", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    engine = FasterWhisperEngine(settings)
    manager = InferenceManager(engine, max_queue_size=settings.queue_size)
    manager.start(settings.worker_count)
    app.state.inference_manager = manager


@app.on_event("shutdown")
async def shutdown() -> None:
    manager: InferenceManager | None = getattr(app.state, "inference_manager", None)
    if manager is not None:
        await manager.stop()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model_path": settings.model_path,
        "device": settings.device,
        "compute_type": settings.compute_type,
        "active_sessions": metrics.active_sessions,
    }


@app.get("/metrics")
async def runtime_metrics() -> dict:
    manager: InferenceManager | None = getattr(app.state, "inference_manager", None)
    queue_size = manager.queue.qsize() if manager is not None else 0
    return {
        "active_sessions": metrics.active_sessions,
        "rejected_sessions": metrics.rejected_sessions,
        "inference_errors": metrics.inference_errors,
        "inference_queue_size": queue_size,
    }


app.include_router(websocket_router)

frontend_dist = Path(settings.frontend_dist)
if (frontend_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")


@app.get("/", response_model=None)
async def index():
    index_path = frontend_dist / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {
        "message": "Streaming ASR backend is running. Build frontend to enable UI.",
        "websocket": "/api/v1/asr/stream",
    }

