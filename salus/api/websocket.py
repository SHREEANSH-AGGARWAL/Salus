"""
Real-time WebSocket event broadcaster for the Salus command dashboard.

Pushes live cluster status, resource transitions, zone priority updates,
and dispatch order changes to all connected dashboard clients on /ws/events.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

logger = structlog.get_logger()


class WebSocketBroadcaster:
    """Manages active WebSocket dashboard connections and broadcasts events."""

    def __init__(self) -> None:
        self._active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept incoming connection and register it."""
        await websocket.accept()
        async with self._lock:
            self._active_connections.add(websocket)
        logger.info(
            "websocket_client_connected",
            active_clients=len(self._active_connections),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a disconnected client."""
        async with self._lock:
            self._active_connections.discard(websocket)
        logger.info(
            "websocket_client_disconnected",
            active_clients=len(self._active_connections),
        )

    async def broadcast_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast a structured JSON event to all connected dashboard clients."""
        payload = {
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }
        await self.broadcast(payload)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send raw JSON payload to all active clients, cleaning up dead connections."""
        async with self._lock:
            clients = list(self._active_connections)

        if not clients:
            return

        dead_clients: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_json(payload)
            except (WebSocketDisconnect, RuntimeError, Exception) as e:
                dead_clients.append(ws)
                logger.debug("websocket_send_failed", error=str(e))

        if dead_clients:
            async with self._lock:
                for ws in dead_clients:
                    self._active_connections.discard(ws)
