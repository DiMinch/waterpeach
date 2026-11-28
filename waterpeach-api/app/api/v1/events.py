import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.schemas.common import UserRole
from app.services.realtime import Subscription, get_event_bus

router = APIRouter(tags=["Realtime"])

SSE_KEEPALIVE_SECONDS = 15.0


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket, role: UserRole | None = None) -> None:
    """Realtime envelope stream; ``?role=`` keeps only events targeting that role."""
    await websocket.accept()
    bus = get_event_bus()
    sub = bus.subscribe(role)

    async def pump() -> None:
        while True:
            event = await sub.queue.get()
            await websocket.send_text(event.model_dump_json())

    async def drain_client() -> None:
        while True:
            await websocket.receive_text()

    tasks = {asyncio.create_task(pump()), asyncio.create_task(drain_client())}
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc
    finally:
        for task in tasks:
            task.cancel()
        bus.unsubscribe(sub)


async def sse_stream(request: Request, sub: Subscription) -> AsyncIterator[str]:
    try:
        yield ": connected\n\n"
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(sub.queue.get(), SSE_KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"
    finally:
        get_event_bus().unsubscribe(sub)


@router.get("/events/stream")
async def sse_events(request: Request, role: UserRole | None = None) -> StreamingResponse:
    """Server-Sent Events fallback with the same envelope as the WebSocket."""
    sub = get_event_bus().subscribe(role)
    return StreamingResponse(
        sse_stream(request, sub),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
