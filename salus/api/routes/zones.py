"""
Disaster zone management endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from salus.models.zone import DisasterZone, ZonePriority
from salus.raft.log_entry import CommandType

router = APIRouter(prefix="/zones", tags=["Zones"])


class RegisterZoneRequest(BaseModel):
    zone: DisasterZone


class UpdateZonePriorityRequest(BaseModel):
    priority: ZonePriority
    priority_score: float
    reason: str = ""


@router.get("")
async def list_zones(request: Request) -> dict[str, Any]:
    """List all registered disaster zones."""
    sm = getattr(request.app.state, "state_machine", None)
    if sm is None:
        return {"zones": [], "count": 0}

    zones_list = [z.model_dump(mode="json") for z in sm.zones.values()]
    return {"zones": zones_list, "count": len(zones_list)}


@router.get("/{zone_id}")
async def get_zone(zone_id: str, request: Request) -> dict[str, Any]:
    """Get details for a specific disaster zone."""
    sm = getattr(request.app.state, "state_machine", None)
    if sm is None or zone_id not in sm.zones:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id} not found")

    return {"zone": sm.zones[zone_id].model_dump(mode="json")}


@router.post("")
async def register_zone(body: RegisterZoneRequest, request: Request) -> dict[str, Any]:
    """Register a new disaster zone into the replicated state machine via Raft."""
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
            CommandType.ZONE_REGISTER,
            body.zone.model_dump(mode="json"),
        )
        broadcaster = getattr(request.app.state, "broadcaster", None)
        if broadcaster:
            await broadcaster.broadcast_event(
                "zone_registered",
                {"zone_id": body.zone.id, "name": body.zone.name, "priority": body.zone.priority},
            )
        return {"status": "accepted", "log_index": res["log_index"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
