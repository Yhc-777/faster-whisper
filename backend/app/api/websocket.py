from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from backend.app.asr.engine import InferenceManager, InferenceResult
from backend.app.asr.session import StreamingSession
from backend.app.config import settings
from backend.app.observability.metrics import metrics
from backend.app.schemas.messages import ErrorMessage, PingMessage, StartMessage


router = APIRouter()


@router.websocket("/api/v1/asr/stream")
async def stream_asr(websocket: WebSocket) -> None:
    manager: InferenceManager = websocket.app.state.inference_manager
    await websocket.accept()

    if metrics.active_sessions >= settings.max_sessions:
        await _send_error(websocket, "TOO_MANY_SESSIONS", "Too many active sessions.")
        await websocket.close(code=1013)
        metrics.rejected_sessions += 1
        return

    session: StreamingSession | None = None
    sender: asyncio.Task | None = None
    metrics.active_sessions += 1

    try:
        start = await _receive_start(websocket)
        if start.sample_rate != settings.sample_rate or start.channels != 1:
            await _send_error(
                websocket,
                "AUDIO_FORMAT_UNSUPPORTED",
                "Only 16kHz mono pcm_s16le is supported.",
            )
            await websocket.close(code=1003)
            return

        session = StreamingSession(start, settings)
        await websocket.send_json({"type": "ready", "session_id": session.id})
        sender = asyncio.create_task(_send_results(websocket, session))

        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"] is not None:
                session.append_audio(message["bytes"])
                request = session.next_partial_request()
                if request is not None and not await manager.submit(request):
                    await _send_error(
                        websocket,
                        "INFERENCE_QUEUE_FULL",
                        "Inference queue is full; partial result was dropped.",
                    )
                continue

            if "text" in message and message["text"] is not None:
                should_stop = await _handle_text_message(
                    websocket,
                    manager,
                    session,
                    message["text"],
                )
                if should_stop:
                    try:
                        await asyncio.wait_for(session.final_sent.wait(), timeout=60)
                    except asyncio.TimeoutError:
                        await _send_error(
                            websocket,
                            "FINAL_TIMEOUT",
                            "Timed out while waiting for final result.",
                        )
                    break
    except WebSocketDisconnect:
        pass
    except ValidationError as exc:
        await _send_error(websocket, "BAD_MESSAGE", str(exc))
    finally:
        if session is not None:
            session.closed = True
        if sender is not None:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        metrics.active_sessions -= 1


async def _receive_start(websocket: WebSocket) -> StartMessage:
    first = await websocket.receive_text()
    payload = json.loads(first)
    return StartMessage(**payload)


async def _handle_text_message(
    websocket: WebSocket,
    manager: InferenceManager,
    session: StreamingSession,
    raw: str,
) -> bool:
    payload = json.loads(raw)
    message_type = payload.get("type")

    if message_type == "ping":
        PingMessage(**payload)
        await websocket.send_json({"type": "pong", "timestamp": time.time()})
        return False

    if message_type == "stop":
        request = session.final_request()
        if request is not None:
            submitted = await manager.submit(request)
            if not submitted:
                await _send_error(
                    websocket,
                    "INFERENCE_QUEUE_FULL",
                    "Inference queue is full; final result could not be submitted.",
                )
                session.final_sent.set()
        else:
            session.final_sent.set()
        return True

    await _send_error(websocket, "UNKNOWN_MESSAGE", f"Unknown message type: {message_type}")
    return False


async def _send_results(websocket: WebSocket, session: StreamingSession) -> None:
    while True:
        item = await session.results.get()
        if isinstance(item, Exception):
            metrics.inference_errors += 1
            await _send_error(websocket, "INFERENCE_FAILED", str(item))
            continue

        result: InferenceResult = item
        if result.is_final:
            text, revision = session.stitcher.apply_final(
                result.text,
                result.start,
                result.end,
            )
            message_type = "final"
        else:
            text, revision = session.stitcher.apply_partial(
                result.text,
                result.start,
                result.end,
            )
            message_type = "partial"

        await websocket.send_json(
            {
                "type": message_type,
                "session_id": result.session_id,
                "text": text,
                "start": result.start,
                "end": result.end,
                "revision": revision,
                "latency_ms": result.inference_ms + result.queue_wait_ms,
            }
        )
        if result.is_final:
            session.final_sent.set()


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    await websocket.send_json(ErrorMessage(code=code, message=message).dict())

