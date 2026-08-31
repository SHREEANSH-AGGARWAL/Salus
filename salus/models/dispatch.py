"""
Dispatch order data model.

Represents the full decision record from the 5-agent pipeline — the
complete audit trail for a single resource dispatch from incident report
through AI recommendation to Incident Commander confirmation to Raft commit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from salus.models.resource import ConfirmationSource
from salus.models.zone import ZonePriority


class DispatchStatus(StrEnum):
    """Status of a dispatch order as it moves through the pipeline."""

    PENDING = "pending"                          # Incident reported, awaiting assessment
    ASSESSING = "assessing"                      # Damage Assessment Agent running
    MATCHING = "matching"                        # Resource Matching Agent running
    ROUTING = "routing"                          # Routing Agent running
    RECOMMENDING = "recommending"                # Decision Agent producing recommendation
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # Waiting for IC gate
    CONFIRMED = "confirmed"                      # IC confirmed dispatch
    REJECTED = "rejected"                        # IC rejected recommendation
    OVERRIDDEN = "overridden"                    # IC overrode with different assignment
    COMMITTED = "committed"                      # Raft log committed — resource dispatched
    DISPATCHED = "dispatched"                    # Resource en route
    ON_SCENE = "on_scene"                        # Resource arrived at zone
    COMPLETED = "completed"                      # Mission completed, resource returning
    FAILED = "failed"                            # Pipeline failed
    FALLBACK = "fallback"                        # Circuit-breaker activated, rule-based dispatch


class DamageAssessmentResult(BaseModel):
    """Output of the Damage Assessment Agent."""

    zone_id: str = Field(..., description="Zone assessed")
    priority: ZonePriority = Field(..., description="Recommended priority (P1–P5)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Assessment confidence")
    reasoning: str = Field(..., description="Agent's reasoning")
    key_factors: list[str] = Field(default_factory=list, description="Critical factors identified")
    estimated_trapped: int = Field(0, ge=0, description="Estimated trapped persons")
    estimated_injured: int = Field(0, ge=0, description="Estimated injured persons")
    assessed_at: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: float = Field(0.0, ge=0, description="Assessment time (ms)")


class ResourceMatchResult(BaseModel):
    """Output of the Resource Matching Agent."""

    recommended_resource_id: str = Field(..., description="Best matching resource")
    recommended_resource_name: str = Field("", description="Resource name for display")
    match_score: float = Field(..., ge=0.0, le=1.0, description="Capability match score")
    reasoning: str = Field(..., description="Why this resource was chosen")
    alternative_resource_ids: list[str] = Field(
        default_factory=list,
        description="Alternative resources if primary unavailable",
    )
    capability_gaps: list[str] = Field(
        default_factory=list,
        description="Capabilities needed but not available in recommended resource",
    )
    latency_ms: float = Field(0.0, ge=0, description="Matching time (ms)")


class RouteResult(BaseModel):
    """Output of the Routing Agent."""

    resource_id: str = Field(..., description="Resource being routed")
    zone_id: str = Field(..., description="Destination zone")
    route_description: str = Field("", description="Human-readable route")
    estimated_travel_time_minutes: float = Field(
        0.0, ge=0, description="Estimated travel time"
    )
    distance_km: float = Field(0.0, ge=0, description="Route distance")
    obstacles: list[str] = Field(
        default_factory=list, description="Obstacles on route (blocked roads, bridges down)"
    )
    requires_air: bool = Field(False, description="Ground route blocked, needs airlift")
    latency_ms: float = Field(0.0, ge=0, description="Routing time (ms)")


class DispatchOrder(BaseModel):
    """Complete dispatch decision record — the full audit trail.

    This is the primary entity that flows through the 5-agent pipeline
    and records every decision, recommendation, override, and outcome.
    Immutable once committed to the Raft log.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Dispatch order ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Input — what triggered this dispatch
    incident_id: str = Field(..., description="Parent incident")
    zone_id: str = Field(..., description="Target zone")
    requesting_icp_id: str = Field(..., description="ICP that initiated the dispatch request")

    # Pipeline status
    status: DispatchStatus = Field(DispatchStatus.PENDING)

    # Agent outputs (populated as pipeline progresses)
    damage_assessment: DamageAssessmentResult | None = Field(
        None, description="Damage Assessment Agent output"
    )
    resource_match: ResourceMatchResult | None = Field(
        None, description="Resource Matching Agent output"
    )
    route: RouteResult | None = Field(
        None, description="Routing Agent output"
    )
    protocol_recommendation: str | None = Field(
        None, description="Protocol Agent — recommended ICS procedure"
    )
    decision_summary: str | None = Field(
        None, description="Decision Agent — final dispatch recommendation"
    )
    decision_confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Decision Agent confidence"
    )

    # Final assignment
    assigned_resource_id: str | None = Field(
        None, description="Resource actually dispatched (may differ from recommendation if overridden)"
    )
    assigned_resource_name: str | None = Field(None, description="Resource name for display")

    # Incident Commander gate
    commander_id: str | None = Field(None, description="Confirming IC")
    commander_agency_id: str | None = Field(None, description="IC's agency")
    confirmation_source: ConfirmationSource | None = Field(None, description="Confirmation type")
    commander_notes: str | None = Field(None, description="IC's notes on the decision")

    # Raft commit
    raft_log_index: int | None = Field(None, description="Log index after commit")
    committed_at: datetime | None = Field(None, description="Timestamp of Raft commit")

    # Performance
    total_latency_ms: float = Field(0.0, ge=0, description="End-to-end pipeline latency (ms)")
    used_fallback: bool = Field(False, description="True if circuit-breaker activated")
    error: str | None = Field(None, description="Error message if pipeline failed")

    model_config = {"json_schema_extra": {"examples": [
        {
            "incident_id": "inc-001",
            "zone_id": "zone-007",
            "requesting_icp_id": "icp-alpha",
            "status": "committed",
            "assigned_resource_id": "res-alpha-7",
            "assigned_resource_name": "SAR Team Alpha",
            "commander_id": "cmd-vikram",
            "confirmation_source": "commander",
        }
    ]}}
