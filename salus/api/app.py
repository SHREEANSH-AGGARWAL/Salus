"""
FastAPI application factory for Salus Incident Command Post.

Provides REST endpoints and WebSocket event streams for the Salus Command Dashboard.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from salus.api.routes import (
    audit_router,
    cluster_router,
    dispatch_router,
    resources_router,
    zones_router,
)
from salus.api.websocket import WebSocketBroadcaster
from salus.dispatch.audit import DispatchAuditLog
from salus.dispatch.commander_gate import CommanderGate
from salus.dispatch.state_machine import DispatchStateMachine

logger = structlog.get_logger()


def create_app(
    node: Any = None,
    state_machine: DispatchStateMachine | None = None,
    gate: CommanderGate | None = None,
    audit_log: DispatchAuditLog | None = None,
    broadcaster: WebSocketBroadcaster | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Wires together state machine, Raft node, Incident Commander gate,
    audit trail, and WebSocket broadcaster onto app.state.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("salus_api_startup")
        yield
        logger.info("salus_api_shutdown")

    app = FastAPI(
        title="Salus Incident Command Post API",
        description="Distributed Disaster Response Resource Consensus Network API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Attach core dependencies to app.state
    app.state.node = node
    app.state.state_machine = state_machine if state_machine is not None else DispatchStateMachine()
    app.state.gate = gate if gate is not None else CommanderGate()
    app.state.audit_log = audit_log if audit_log is not None else DispatchAuditLog()
    app.state.broadcaster = broadcaster if broadcaster is not None else WebSocketBroadcaster()

    # CORS
    origins = cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount REST Routers
    api_v1_prefix = "/api/v1"
    app.include_router(cluster_router, prefix=api_v1_prefix)
    app.include_router(resources_router, prefix=api_v1_prefix)
    app.include_router(zones_router, prefix=api_v1_prefix)
    app.include_router(dispatch_router, prefix=api_v1_prefix)
    app.include_router(audit_router, prefix=api_v1_prefix)

    # Real-time WebSocket endpoint
    @app.websocket("/ws/events")
    async def websocket_events_endpoint(websocket: WebSocket) -> None:
        bc: WebSocketBroadcaster = app.state.broadcaster
        await bc.connect(websocket)
        try:
            while True:
                # Keepalive / ping-pong
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            await bc.disconnect(websocket)
        except Exception as e:
            logger.debug("websocket_exception", error=str(e))
            await bc.disconnect(websocket)

    # Root welcome / health check
    @app.get("/")
    async def root_status() -> dict[str, Any]:
        node_status = app.state.node.get_status() if app.state.node else {}
        return {
            "name": "Salus ICP Node",
            "version": "0.1.0",
            "node_id": node_status.get("node_id", "unassigned"),
            "state": node_status.get("state", "uninitialized"),
            "endpoints": {
                "docs": "/docs",
                "cluster": "/api/v1/cluster/status",
                "resources": "/api/v1/resources",
                "zones": "/api/v1/zones",
                "dispatch": "/api/v1/dispatch/pending",
                "audit": "/api/v1/audit",
                "events_ws": "/ws/events",
            },
        }

    return app
