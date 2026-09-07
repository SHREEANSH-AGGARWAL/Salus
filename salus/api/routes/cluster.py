"""
Cluster management and monitoring endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/cluster", tags=["Cluster"])


@router.get("/status")
async def get_cluster_status(request: Request) -> dict[str, Any]:
    """Get the Raft node consensus status and cluster membership."""
    node = getattr(request.app.state, "node", None)
    if node is None:
        return {"status": "uninitialized"}

    status = node.get_status()
    # Serialize enum if needed
    if hasattr(status.get("state"), "value"):
        status["state"] = status["state"].value
    return status


@router.get("/health")
async def get_health(request: Request) -> dict[str, Any]:
    """Liveness and readiness check."""
    node = getattr(request.app.state, "node", None)
    if node is None:
        return {"status": "starting", "ready": False}

    is_partitioned = node.is_partitioned
    return {
        "status": "healthy" if not is_partitioned else "degraded",
        "ready": True,
        "node_id": node.node_id,
        "is_partitioned": is_partitioned,
        "state": node.state.value if hasattr(node.state, "value") else str(node.state),
    }


@router.get("/peers")
async def get_peers(request: Request) -> dict[str, Any]:
    """Get connected peer list and cluster configuration."""
    node = getattr(request.app.state, "node", None)
    if node is None:
        return {"peers": []}

    return {
        "node_id": node.node_id,
        "peers": node.peer_ids,
        "cluster_size": node.cluster_size,
        "quorum_size": node.quorum_size,
        "next_index": getattr(node, "next_index", {}),
        "match_index": getattr(node, "match_index", {}),
    }
