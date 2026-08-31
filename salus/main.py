"""
Salus ICP node entry point.

Starts the Raft consensus module, gRPC server, and FastAPI REST server
for a single Incident Command Post (ICP) node in the cluster.
"""

from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from salus.config import NodeConfig

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

    # TODO: Phase 2 — Start Raft consensus module
    # TODO: Phase 2 — Start gRPC server
    # TODO: Phase 2 — Start FastAPI server

    logger.info("salus_icp_started", node_id=config.node_id)

    # Keep running until shutdown signal
    stop_event = asyncio.Event()

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("shutdown_signal_received", signal=sig.name)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    await stop_event.wait()
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
