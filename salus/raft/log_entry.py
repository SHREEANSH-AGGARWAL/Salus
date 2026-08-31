"""
Raft log entry — the atomic unit of the replicated log.

This is an INTERFACE CONTRACT (C1) — S1 and S2 must agree on this
schema before writing any Raft implementation code. All Raft modules
depend on this definition.

Reference: Ongaro & Ousterhout (2014), §5.3
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CommandType(StrEnum):
    """Types of commands that can be committed to the Raft log.

    Each command type maps to a state machine operation in the
    disaster response dispatch domain.
    """

    # Resource state transitions
    RESOURCE_REGISTER = "resource_register"
    RESOURCE_DISPATCH = "resource_dispatch"
    RESOURCE_ARRIVE = "resource_arrive"
    RESOURCE_RETURN = "resource_return"
    RESOURCE_RESUPPLY_REQUEST = "resource_resupply_request"
    RESOURCE_RESUPPLY_COMPLETE = "resource_resupply_complete"
    RESOURCE_MAINTENANCE = "resource_maintenance"
    RESOURCE_RESTORE = "resource_restore"
    RESOURCE_CANCEL_DISPATCH = "resource_cancel_dispatch"

    # Zone management
    ZONE_REGISTER = "zone_register"
    ZONE_UPDATE = "zone_update"
    ZONE_PRIORITY_UPDATE = "zone_priority_update"

    # Incident management
    INCIDENT_REPORT = "incident_report"
    INCIDENT_UPDATE = "incident_update"
    INCIDENT_RESOLVE = "incident_resolve"

    # Dispatch orders
    DISPATCH_ORDER = "dispatch_order"
    DISPATCH_CONFIRM = "dispatch_confirm"
    DISPATCH_REJECT = "dispatch_reject"
    DISPATCH_OVERRIDE = "dispatch_override"

    # ICP / Agency management
    ICP_REGISTER = "icp_register"
    ICP_UPDATE = "icp_update"

    # No-op (used for leader confirmation on read-index)
    NOOP = "noop"


class LogEntry(BaseModel):
    """A single entry in the Raft replicated log.

    Once committed (acknowledged by quorum), a log entry is immutable
    and will never be overwritten or removed. The state machine applies
    committed entries in log-index order to produce the current state.

    Fields:
        term: The Raft term when this entry was created by the leader.
        index: Position in the log (1-indexed, monotonically increasing).
        command_type: What kind of state machine operation this represents.
        payload: Serialized command data (JSON string).
        timestamp: When the entry was created.
    """

    term: int = Field(..., ge=0, description="Raft term when entry was created")
    index: int = Field(..., ge=0, description="Log position (0=sentinel, 1+ = real entries)")
    command_type: CommandType = Field(..., description="State machine command type")
    payload: str = Field(..., description="JSON-serialized command payload")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Populated after commit
    committed: bool = Field(False, description="True after quorum acknowledgment")

    def __repr__(self) -> str:
        status = "✓" if self.committed else "○"
        return f"LogEntry({status} term={self.term} idx={self.index} cmd={self.command_type})"
