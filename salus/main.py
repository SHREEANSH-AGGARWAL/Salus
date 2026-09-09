"""
Salus ICP node entry point.

Starts the Raft consensus module, gRPC server, and FastAPI REST server
for a single Incident Command Post (ICP) node in the cluster.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from pathlib import Path

import structlog
import uvicorn

from salus.api.app import create_app
from salus.api.websocket import WebSocketBroadcaster
from salus.config import NodeConfig
from salus.dispatch.audit import DispatchAuditLog
from salus.dispatch.commander_gate import CommanderGate
from salus.dispatch.state_machine import DispatchStateMachine
from salus.raft.node import RaftNode
from salus.raft.wal import WALManager
from salus.transport.client import GRPCClientPool
from salus.transport.server import create_grpc_server

logger = structlog.get_logger()


async def start_node(config: NodeConfig) -> None:
    """Start all services for this Salus ICP node."""
    logger.info(
        "starting_salus_icp",
        node_id=config.node_id,
        icp=config.icp_name,
        agency=config.agency_name,
        agency_type=config.agency_type,
        grpc_port=config.grpc.port,
        api_port=config.api.port,
        peers=[p.node_id for p in config.peers],
    )

    # 1. State Machine & Persistence
    wal_dir = Path(config.wal_dir)
    wal_dir.mkdir(parents=True, exist_ok=True)
    wal = WALManager(db_dir=wal_dir, node_id=config.node_id)
    state_machine = DispatchStateMachine()

    # 2. Inter-node gRPC Client Pool
    peer_ids = [p.node_id for p in config.peers]
    client_pool = GRPCClientPool(
        peer_addresses=config.peers,
        request_timeout_ms=config.grpc.request_timeout_ms,
        connect_timeout_ms=config.grpc.connect_timeout_ms,
        max_message_size=config.grpc.max_message_size_bytes,
        snapshot_chunk_size=config.raft.snapshot_chunk_size_bytes,
    )

    # 3. Raft Consensus Node
    node = RaftNode(
        node_id=config.node_id,
        peer_ids=peer_ids,
        state_machine=state_machine,
        election_timeout_min_ms=config.raft.election_timeout_min_ms,
        election_timeout_max_ms=config.raft.election_timeout_max_ms,
        heartbeat_interval_ms=config.raft.heartbeat_interval_ms,
        send_rpc=client_pool.send_rpc,
        wal=wal,
    )

    # 4. Domain & Safety Layers
    gate = CommanderGate(timeout_seconds=120)
    audit_log = DispatchAuditLog()
    broadcaster = WebSocketBroadcaster()

    # 4.5 AI Pipeline (optional — gracefully skipped if AI extras not installed)
    pipeline = None
    try:
        from salus.agents.pipeline import DispatchPipeline

        pipeline = await DispatchPipeline.create_and_ingest(
            llm_config=config.llm,
            rag_config=config.rag,
            state_machine=state_machine,
            icp_id=config.node_id,
            data_dir=Path("data"),
        )
        logger.info("ai_pipeline_ready", provider=config.llm.provider, model=config.llm.model)
    except ImportError:
        logger.warning(
            "ai_pipeline_skipped",
            reason="AI extras not installed. Run: pip install 'salus[ai]'",
        )
    except Exception:
        logger.exception("ai_pipeline_init_failed")

    # 5. REST & WebSocket API App
    app = create_app(
        node=node,
        state_machine=state_machine,
        gate=gate,
        audit_log=audit_log,
        broadcaster=broadcaster,
        cors_origins=config.api.cors_origins,
    )
    # Attach pipeline to app state so route handlers can access it
    app.state.pipeline = pipeline

    # 6. gRPC Server
    grpc_server = await create_grpc_server(
        node=node,
        host=config.grpc.host,
        port=config.grpc.port,
        max_message_size=config.grpc.max_message_size_bytes,
    )
    await grpc_server.start()
    logger.info("grpc_server_started", host=config.grpc.host, port=config.grpc.port)

    # 7. FastAPI Uvicorn Server
    uvicorn_config = uvicorn.Config(
        app=app,
        host=config.api.host,
        port=config.api.port,
        log_level="warning",
        access_log=False,
    )
    api_server = uvicorn.Server(uvicorn_config)
    api_task = asyncio.create_task(api_server.serve())
    logger.info("api_server_started", host=config.api.host, port=config.api.port)

    # 8. Start Raft consensus engine (starts election timers)
    await node.start()
    logger.info("salus_icp_started", node_id=config.node_id)

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("shutdown_signal_received", signal=sig.name)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handle_signal, sig)

    try:
        await stop_event.wait()
    finally:
        logger.info("shutting_down_salus_icp", node_id=config.node_id)
        # Graceful shutdown sequence
        await node.stop()
        api_server.should_exit = True
        await api_task
        await grpc_server.stop(grace=1.0)
        await client_pool.close()
        logger.info("salus_icp_stopped", node_id=config.node_id)


def main() -> None:
    """CLI entry point for salus-node."""
    config = NodeConfig()

    logger.info(
        "salus_config_loaded",
        node_id=config.node_id,
        icp=config.icp_name,
        agency=config.agency_name,
    )

    try:
        asyncio.run(start_node(config))
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
        sys.exit(0)


if __name__ == "__main__":
    main()
