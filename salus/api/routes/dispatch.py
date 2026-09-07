"""
Incident Commander gate and dispatch control endpoints.

Enforces human-in-the-loop confirmation before any dispatch order
is committed to the Raft consensus log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from salus.dispatch.audit import AuditAction
from salus.dispatch.commander_gate import CommanderGate
from salus.models.resource import ConfirmationSource, ResourceStatus
from salus.raft.log_entry import CommandType

router = APIRouter(prefix="/dispatch", tags=["Dispatch"])


class DispatchRecommendationRequest(BaseModel):
    dispatch_order_id: str
    resource_id: str
    resource_name: str = ""
    zone_id: str
    zone_name: str = ""
    incident_id: str
    ai_confidence: float = 0.0
    ai_reasoning: str = ""
    alternative_resources: list[str] = Field(default_factory=list)


class ConfirmDispatchRequest(BaseModel):
    commander_id: str
    commander_agency_id: str = ""
    notes: str = ""


class OverrideDispatchRequest(BaseModel):
    commander_id: str
    override_resource_id: str
    commander_agency_id: str = ""
    notes: str = ""


class RejectDispatchRequest(BaseModel):
    commander_id: str
    commander_agency_id: str = ""
    reason: str = ""


@router.get("/pending")
async def list_pending_confirmations(request: Request) -> dict[str, Any]:
    """Get all recommendations waiting at the Incident Commander confirmation gate."""
    gate: CommanderGate | None = getattr(request.app.state, "gate", None)
    if gate is None:
        return {"pending": [], "count": 0}

    # Clean up expired entries
    gate.expire_stale()
    pending = [p.model_dump(mode="json") for p in gate.get_pending()]
    return {"pending": pending, "count": len(pending)}


@router.post("/recommend")
async def submit_recommendation(
    body: DispatchRecommendationRequest, request: Request
) -> dict[str, Any]:
    """Submit an AI or rule-based recommendation into the Commander Gate queue."""
    gate: CommanderGate | None = getattr(request.app.state, "gate", None)
    if gate is None:
        raise HTTPException(status_code=503, detail="Commander gate not initialized")

    confirmation = gate.request_confirmation(
        dispatch_order_id=body.dispatch_order_id,
        resource_id=body.resource_id,
        resource_name=body.resource_name,
        zone_id=body.zone_id,
        zone_name=body.zone_name,
        incident_id=body.incident_id,
        ai_confidence=body.ai_confidence,
        ai_reasoning=body.ai_reasoning,
        alternative_resources=body.alternative_resources,
    )

    audit = getattr(request.app.state, "audit_log", None)
    if audit:
        audit.log(
            action=AuditAction.AI_RESOURCE_MATCH,
            actor_id="matching_engine",
            actor_type="agent",
            resource_id=body.resource_id,
            zone_id=body.zone_id,
            incident_id=body.incident_id,
            dispatch_id=body.dispatch_order_id,
            reasoning=body.ai_reasoning,
            confidence=body.ai_confidence,
        )

    broadcaster = getattr(request.app.state, "broadcaster", None)
    if broadcaster:
        await broadcaster.broadcast_event(
            "dispatch_recommendation_queued",
            confirmation.model_dump(mode="json"),
        )

    return {
        "status": "queued_for_review",
        "confirmation_id": confirmation.id,
        "expires_at": confirmation.expires_at.isoformat(),
    }


@router.post("/{confirmation_id}/confirm")
async def confirm_dispatch(
    confirmation_id: str, body: ConfirmDispatchRequest, request: Request
) -> dict[str, Any]:
    """Incident Commander confirms recommendation — triggers Raft consensus commit."""
    gate: CommanderGate | None = getattr(request.app.state, "gate", None)
    node = getattr(request.app.state, "node", None)
    audit = getattr(request.app.state, "audit_log", None)
    broadcaster = getattr(request.app.state, "broadcaster", None)

    if gate is None or node is None:
        raise HTTPException(status_code=503, detail="Services not ready")

    if not node.is_leader:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Not the leader. Redirect to leader.",
                "leader_id": node.leader_id,
            },
        )

    try:
        confirmed = gate.confirm(
            confirmation_id=confirmation_id,
            commander_id=body.commander_id,
            commander_agency_id=body.commander_agency_id,
            notes=body.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Confirmation request not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Construct Raft transition command
    payload = {
        "resource_id": confirmed.resource_id,
        "from_status": ResourceStatus.AVAILABLE.value,
        "to_status": ResourceStatus.DISPATCHED.value,
        "zone_id": confirmed.zone_id,
        "incident_id": confirmed.incident_id,
        "actor_id": body.commander_id,
        "actor_type": "commander",
        "confirmation_source": ConfirmationSource.COMMANDER.value,
        "commander_id": body.commander_id,
        "commander_agency_id": body.commander_agency_id,
        "commander_notes": body.notes,
    }

    try:
        res = await node.submit_command(CommandType.RESOURCE_DISPATCH, payload)
        if audit:
            audit.log(
                action=AuditAction.IC_CONFIRM,
                actor_id=body.commander_id,
                actor_type="commander",
                resource_id=confirmed.resource_id,
                zone_id=confirmed.zone_id,
                incident_id=confirmed.incident_id,
                dispatch_id=confirmed.dispatch_order_id,
                reasoning=body.notes,
                raft_log_index=res["log_index"],
                raft_term=res["term"],
            )

        if broadcaster:
            await broadcaster.broadcast_event(
                "resource_dispatched",
                {
                    "resource_id": confirmed.resource_id,
                    "zone_id": confirmed.zone_id,
                    "commander_id": body.commander_id,
                    "log_index": res["log_index"],
                },
            )

        return {
            "status": "committed",
            "dispatch_order_id": confirmed.dispatch_order_id,
            "resource_id": confirmed.resource_id,
            "zone_id": confirmed.zone_id,
            "log_index": res["log_index"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Raft commit error: {e}")


@router.post("/{confirmation_id}/override")
async def override_dispatch(
    confirmation_id: str, body: OverrideDispatchRequest, request: Request
) -> dict[str, Any]:
    """Incident Commander overrides recommendation with a different resource."""
    gate: CommanderGate | None = getattr(request.app.state, "gate", None)
    node = getattr(request.app.state, "node", None)
    audit = getattr(request.app.state, "audit_log", None)
    broadcaster = getattr(request.app.state, "broadcaster", None)

    if gate is None or node is None:
        raise HTTPException(status_code=503, detail="Services not ready")

    if not node.is_leader:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Not the leader. Redirect to leader.",
                "leader_id": node.leader_id,
            },
        )

    try:
        overridden = gate.override(
            confirmation_id=confirmation_id,
            commander_id=body.commander_id,
            override_resource_id=body.override_resource_id,
            commander_agency_id=body.commander_agency_id,
            notes=body.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Confirmation request not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    payload = {
        "resource_id": body.override_resource_id,
        "from_status": ResourceStatus.AVAILABLE.value,
        "to_status": ResourceStatus.DISPATCHED.value,
        "zone_id": overridden.zone_id,
        "incident_id": overridden.incident_id,
        "actor_id": body.commander_id,
        "actor_type": "commander",
        "confirmation_source": ConfirmationSource.OVERRIDE.value,
        "commander_id": body.commander_id,
        "commander_agency_id": body.commander_agency_id,
        "commander_notes": body.notes,
    }

    try:
        res = await node.submit_command(CommandType.RESOURCE_DISPATCH, payload)
        if audit:
            audit.log(
                action=AuditAction.IC_OVERRIDE,
                actor_id=body.commander_id,
                actor_type="commander",
                resource_id=body.override_resource_id,
                zone_id=overridden.zone_id,
                incident_id=overridden.incident_id,
                dispatch_id=overridden.dispatch_order_id,
                commander_override=True,
                override_reason=body.notes,
                raft_log_index=res["log_index"],
                raft_term=res["term"],
            )

        if broadcaster:
            await broadcaster.broadcast_event(
                "resource_dispatched_override",
                {
                    "resource_id": body.override_resource_id,
                    "original_recommendation": overridden.resource_id,
                    "zone_id": overridden.zone_id,
                    "commander_id": body.commander_id,
                    "log_index": res["log_index"],
                },
            )

        return {
            "status": "committed",
            "dispatch_order_id": overridden.dispatch_order_id,
            "resource_id": body.override_resource_id,
            "zone_id": overridden.zone_id,
            "log_index": res["log_index"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Raft commit error: {e}")


@router.post("/{confirmation_id}/reject")
async def reject_dispatch(
    confirmation_id: str, body: RejectDispatchRequest, request: Request
) -> dict[str, Any]:
    """Incident Commander rejects recommendation."""
    gate: CommanderGate | None = getattr(request.app.state, "gate", None)
    audit = getattr(request.app.state, "audit_log", None)
    broadcaster = getattr(request.app.state, "broadcaster", None)

    if gate is None:
        raise HTTPException(status_code=503, detail="Commander gate not initialized")

    try:
        rejected = gate.reject(
            confirmation_id=confirmation_id,
            commander_id=body.commander_id,
            commander_agency_id=body.commander_agency_id,
            reason=body.reason,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Confirmation request not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if audit:
        audit.log(
            action=AuditAction.IC_REJECT,
            actor_id=body.commander_id,
            actor_type="commander",
            resource_id=rejected.resource_id,
            zone_id=rejected.zone_id,
            incident_id=rejected.incident_id,
            dispatch_id=rejected.dispatch_order_id,
            reasoning=body.reason,
        )

    if broadcaster:
        await broadcaster.broadcast_event(
            "dispatch_rejected",
            {
                "confirmation_id": confirmation_id,
                "commander_id": body.commander_id,
                "reason": body.reason,
            },
        )

    return {"status": "rejected", "confirmation_id": confirmation_id}
