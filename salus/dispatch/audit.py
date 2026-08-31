"""
Immutable dispatch audit log.

Every AI recommendation, Incident Commander decision, override,
and resource state transition is logged here. Append-only — entries
are never modified or deleted.

This audit log exists alongside the Raft log but serves a different
purpose: the Raft log is the replicated state machine journal, while
this audit log provides human-readable decision traceability for
post-incident analysis.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class AuditAction(StrEnum):
    """Types of auditable actions."""

    # AI pipeline
    AI_DAMAGE_ASSESSMENT = "ai_damage_assessment"
    AI_RESOURCE_MATCH = "ai_resource_match"
    AI_ROUTE_PLAN = "ai_route_plan"
    AI_PROTOCOL_LOOKUP = "ai_protocol_lookup"
    AI_DECISION = "ai_decision"
    AI_FALLBACK = "ai_fallback"  # Circuit-breaker activated

    # IC gate
    IC_CONFIRM = "ic_confirm"
    IC_REJECT = "ic_reject"
    IC_OVERRIDE = "ic_override"
    IC_TIMEOUT = "ic_timeout"

    # Resource transitions
    RESOURCE_DISPATCHED = "resource_dispatched"
    RESOURCE_ARRIVED = "resource_arrived"
    RESOURCE_RETURNED = "resource_returned"
    RESOURCE_RESUPPLY = "resource_resupply"

    # System
    SYSTEM_ERROR = "system_error"
    PARTITION_DETECTED = "partition_detected"
    PARTITION_HEALED = "partition_healed"


class AuditEntry(BaseModel):
    """A single entry in the dispatch audit log.

    Immutable once created. Captures the full context of a decision
    or action for post-incident review.
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action: AuditAction = Field(..., description="Type of action")

    # Context
    actor_id: str = Field(..., description="Who/what performed this action")
    actor_type: str = Field("system", description="'commander', 'agent', 'system'")
    icp_id: str = Field("", description="ICP where this action occurred")

    # References
    resource_id: str | None = Field(None)
    zone_id: str | None = Field(None)
    incident_id: str | None = Field(None)
    dispatch_id: str | None = Field(None)

    # Decision details
    reasoning: str = Field("", description="Why this action was taken")
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    ai_recommendation: str | None = Field(None, description="What the AI recommended")
    commander_override: bool = Field(False)
    override_reason: str | None = Field(None)

    # Raft context
    raft_log_index: int | None = Field(None)
    raft_term: int | None = Field(None)


class DispatchAuditLog:
    """Append-only audit log for dispatch decisions.

    Stores all entries in memory for the prototype. In production,
    this would be backed by a durable append-only store.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def log(
        self,
        action: AuditAction,
        actor_id: str,
        actor_type: str = "system",
        icp_id: str = "",
        resource_id: str | None = None,
        zone_id: str | None = None,
        incident_id: str | None = None,
        dispatch_id: str | None = None,
        reasoning: str = "",
        confidence: float | None = None,
        ai_recommendation: str | None = None,
        commander_override: bool = False,
        override_reason: str | None = None,
        raft_log_index: int | None = None,
        raft_term: int | None = None,
    ) -> AuditEntry:
        """Append an entry to the audit log.

        Args:
            action: The type of action being logged.
            actor_id: Who performed the action.
            actor_type: Type of actor (commander, agent, system).
            icp_id: ICP where this action occurred.
            resource_id: Resource involved (if any).
            zone_id: Zone involved (if any).
            incident_id: Incident involved (if any).
            dispatch_id: Dispatch order involved (if any).
            reasoning: Why this action was taken.
            confidence: AI confidence score (if applicable).
            ai_recommendation: What the AI recommended.
            commander_override: Whether IC overrode the AI.
            override_reason: IC's reason for override.
            raft_log_index: Raft log index of the commit.
            raft_term: Raft term of the commit.

        Returns:
            The created audit entry.
        """
        entry = AuditEntry(
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            icp_id=icp_id,
            resource_id=resource_id,
            zone_id=zone_id,
            incident_id=incident_id,
            dispatch_id=dispatch_id,
            reasoning=reasoning,
            confidence=confidence,
            ai_recommendation=ai_recommendation,
            commander_override=commander_override,
            override_reason=override_reason,
            raft_log_index=raft_log_index,
            raft_term=raft_term,
        )
        self._entries.append(entry)

        logger.debug(
            "audit_entry",
            action=action,
            actor=actor_id,
            resource=resource_id,
            zone=zone_id,
        )

        return entry

    @property
    def entries(self) -> list[AuditEntry]:
        """Return all audit entries (read-only view)."""
        return list(self._entries)

    def get_by_resource(self, resource_id: str) -> list[AuditEntry]:
        """Get all audit entries for a specific resource."""
        return [e for e in self._entries if e.resource_id == resource_id]

    def get_by_zone(self, zone_id: str) -> list[AuditEntry]:
        """Get all audit entries for a specific zone."""
        return [e for e in self._entries if e.zone_id == zone_id]

    def get_by_dispatch(self, dispatch_id: str) -> list[AuditEntry]:
        """Get all audit entries for a specific dispatch order."""
        return [e for e in self._entries if e.dispatch_id == dispatch_id]

    def get_by_action(self, action: AuditAction) -> list[AuditEntry]:
        """Get all audit entries of a specific action type."""
        return [e for e in self._entries if e.action == action]

    def get_overrides(self) -> list[AuditEntry]:
        """Get all entries where the IC overrode the AI."""
        return [e for e in self._entries if e.commander_override]

    def count(self) -> int:
        """Return total number of audit entries."""
        return len(self._entries)
