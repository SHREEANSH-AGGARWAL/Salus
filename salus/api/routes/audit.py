"""
Audit trail inspection endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from salus.dispatch.audit import DispatchAuditLog

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("")
async def query_audit_trail(
    request: Request,
    action: str | None = Query(None, description="Filter by action type"),
    resource_id: str | None = Query(None, description="Filter by resource ID"),
    zone_id: str | None = Query(None, description="Filter by zone ID"),
    limit: int = Query(100, ge=1, le=1000, description="Max entries to return"),
) -> dict[str, Any]:
    """Retrieve immutable dispatch audit log entries for post-incident review."""
    audit: DispatchAuditLog | None = getattr(request.app.state, "audit_log", None)
    if audit is None:
        return {"entries": [], "total": 0}

    entries = audit.entries

    if action:
        entries = [e for e in entries if e.action == action]
    if resource_id:
        entries = [e for e in entries if e.resource_id == resource_id]
    if zone_id:
        entries = [e for e in entries if e.zone_id == zone_id]

    entries = entries[:limit]

    serialized = [e.model_dump(mode="json") for e in entries]
    return {
        "entries": serialized,
        "total": len(serialized),
    }
