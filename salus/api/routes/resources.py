"""
Resource inventory and status endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from salus.models.resource import Resource
from salus.raft.log_entry import CommandType

router = APIRouter(prefix="/resources", tags=["Resources"])


class RegisterResourceRequest(BaseModel):
    resource: Resource


@router.get("")
async def list_resources(request: Request) -> dict[str, Any]:
    """List all disaster resources.

    DEGRADED MODE INVARIANT (§3.2):
    If this node is partitioned from the cluster quorum, resource states
    are strictly reported as 'uncertain' so the Incident Commander cannot
    act on stale data.
    """
    sm = getattr(request.app.state, "state_machine", None)
    node = getattr(request.app.state, "node", None)

    if sm is None:
        return {"resources": [], "count": 0, "partitioned": False}

    is_partitioned = node.is_partitioned if node else False
    resources_list = []

    for r in sm.resources.values():
        r_dict = r.model_dump(mode="json")
        if is_partitioned:
            r_dict["original_status"] = r_dict["status"]
            r_dict["status"] = "uncertain"
            r_dict["is_uncertain"] = True
        else:
            r_dict["is_uncertain"] = False
        resources_list.append(r_dict)

    return {
        "resources": resources_list,
        "count": len(resources_list),
        "partitioned": is_partitioned,
        "degraded_mode": is_partitioned,
    }


@router.get("/{resource_id}")
async def get_resource(resource_id: str, request: Request) -> dict[str, Any]:
    """Get detail for a specific resource."""
    sm = getattr(request.app.state, "state_machine", None)
    node = getattr(request.app.state, "node", None)

    if sm is None or resource_id not in sm.resources:
        raise HTTPException(status_code=404, detail=f"Resource {resource_id} not found")

    r = sm.resources[resource_id]
    r_dict = r.model_dump(mode="json")
    is_partitioned = node.is_partitioned if node else False
    if is_partitioned:
        r_dict["original_status"] = r_dict["status"]
        r_dict["status"] = "uncertain"
        r_dict["is_uncertain"] = True
    else:
        r_dict["is_uncertain"] = False

    return {"resource": r_dict, "partitioned": is_partitioned}


@router.post("")
async def register_resource(body: RegisterResourceRequest, request: Request) -> dict[str, Any]:
    """Register a new resource into the replicated state machine via Raft."""
    node = getattr(request.app.state, "node", None)
    if node is None:
        raise HTTPException(status_code=503, detail="Raft node not initialized")

    if not node.is_leader:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Not the leader. Redirect to leader.",
                "leader_id": node.leader_id,
            },
        )

    try:
        res = await node.submit_command(
            CommandType.RESOURCE_REGISTER,
            body.resource.model_dump(mode="json"),
        )
        # Notify connected dashboard clients
        broadcaster = getattr(request.app.state, "broadcaster", None)
        if broadcaster:
            await broadcaster.broadcast_event(
                "resource_registered",
                {"resource_id": body.resource.id, "name": body.resource.name},
            )
        return {"status": "accepted", "log_index": res["log_index"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
