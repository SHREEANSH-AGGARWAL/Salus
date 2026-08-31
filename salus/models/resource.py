"""
Resource data model.

Represents a deployable disaster response resource — helicopters, rescue teams,
ambulances, generators, field hospitals, etc. Each resource has capabilities,
constraints, and a Raft-replicated deployment status.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from salus.models.common import GeoLocation


class ResourceType(StrEnum):
    """Disaster response resource types."""

    HELICOPTER_TRANSPORT = "helicopter_transport"
    HELICOPTER_MEDICAL = "helicopter_medical"
    HELICOPTER_HEAVY_LIFT = "helicopter_heavy_lift"
    SAR_TEAM_URBAN = "sar_team_urban"           # Urban search and rescue
    SAR_TEAM_WATER = "sar_team_water"            # Water/flood rescue
    SAR_TEAM_MOUNTAIN = "sar_team_mountain"      # Mountain/wilderness rescue
    AMBULANCE = "ambulance"
    AMBULANCE_ALS = "ambulance_als"              # Advanced Life Support
    FIRE_ENGINE = "fire_engine"
    HAZMAT_TEAM = "hazmat_team"
    EVACUATION_BUS = "evacuation_bus"
    SUPPLY_TRUCK = "supply_truck"
    WATER_TANKER = "water_tanker"
    GENERATOR = "generator"
    FIELD_HOSPITAL = "field_hospital"
    K9_UNIT = "k9_unit"
    DRONE_TEAM = "drone_team"
    ENGINEERING_UNIT = "engineering_unit"         # Heavy equipment, road clearing


class ResourceStatus(StrEnum):
    """Resource deployment states — each transition is a committed Raft log entry.

    AVAILABLE:       Resource is at base/staging, ready for dispatch.
    DISPATCHED:      Resource has been assigned to a zone. En route.
                     Requires Incident Commander confirmation before commit.
    ON_SCENE:        Resource has arrived at the assigned zone and is operating.
    RETURNING:       Resource is returning to base/staging after completing task.
    NEEDS_RESUPPLY:  Resource is on scene but needs fuel, medical supplies, etc.
    RESUPPLYING:     Resource is at a resupply point, temporarily unavailable.
    MAINTENANCE:     Resource is offline for maintenance or equipment failure.
    """

    AVAILABLE = "available"
    DISPATCHED = "dispatched"
    ON_SCENE = "on_scene"
    RETURNING = "returning"
    NEEDS_RESUPPLY = "needs_resupply"
    RESUPPLYING = "resupplying"
    MAINTENANCE = "maintenance"


class ConfirmationSource(StrEnum):
    """Who confirmed the dispatch — audit trail requirement.

    Every RESOURCE_DISPATCHED log entry MUST carry this field.
    No autonomous dispatch — always commander-confirmed.
    """

    COMMANDER = "commander"          # Incident Commander confirmed
    AUTONOMOUS = "autonomous"        # System auto-confirmed (TESTING/DEMO ONLY)
    OVERRIDE = "override"            # Commander overrode AI recommendation


# Valid state transitions — the dispatch state machine
VALID_TRANSITIONS: dict[ResourceStatus, set[ResourceStatus]] = {
    ResourceStatus.AVAILABLE: {ResourceStatus.DISPATCHED, ResourceStatus.MAINTENANCE},
    ResourceStatus.DISPATCHED: {ResourceStatus.ON_SCENE, ResourceStatus.AVAILABLE},  # AVAILABLE = cancellation
    ResourceStatus.ON_SCENE: {ResourceStatus.RETURNING, ResourceStatus.NEEDS_RESUPPLY},
    ResourceStatus.RETURNING: {ResourceStatus.AVAILABLE},
    ResourceStatus.NEEDS_RESUPPLY: {ResourceStatus.RESUPPLYING, ResourceStatus.RETURNING},
    ResourceStatus.RESUPPLYING: {ResourceStatus.AVAILABLE, ResourceStatus.DISPATCHED},
    ResourceStatus.MAINTENANCE: {ResourceStatus.AVAILABLE},
}


def is_valid_transition(from_status: ResourceStatus, to_status: ResourceStatus) -> bool:
    """Check if a resource state transition is valid per the state machine.

    Args:
        from_status: Current resource state.
        to_status: Desired next state.

    Returns:
        True if the transition is allowed.
    """
    return to_status in VALID_TRANSITIONS.get(from_status, set())


class ResourceCapabilities(BaseModel):
    """What a resource can do — used for resource-to-zone matching."""

    # Personnel
    personnel_count: int = Field(0, ge=0, description="Number of personnel")
    has_medical_personnel: bool = Field(False, description="Includes paramedics/doctors")

    # Transport
    passenger_capacity: int = Field(0, ge=0, description="People that can be evacuated/transported")
    cargo_capacity_kg: float = Field(0.0, ge=0, description="Cargo capacity in kg")

    # Capabilities
    can_perform_sar: bool = Field(False, description="Search and rescue capable")
    can_perform_water_rescue: bool = Field(False, description="Water/flood rescue capable")
    can_perform_hazmat: bool = Field(False, description="HAZMAT decontamination capable")
    can_perform_medical: bool = Field(False, description="On-scene medical treatment")
    can_perform_firefighting: bool = Field(False, description="Fire suppression capable")
    can_clear_debris: bool = Field(False, description="Heavy debris removal")
    has_listening_devices: bool = Field(False, description="Life-detection listening devices")
    has_thermal_imaging: bool = Field(False, description="Thermal imaging for survivor detection")

    # Terrain
    can_access_air: bool = Field(False, description="Can reach zones by air")
    can_access_water: bool = Field(False, description="Can operate on/in water")
    can_access_rough_terrain: bool = Field(False, description="Off-road capable")

    # Constraints
    max_range_km: float = Field(0.0, ge=0, description="Maximum operational range in km")
    fuel_hours_remaining: float = Field(0.0, ge=0, description="Fuel/battery hours remaining")
    requires_runway: bool = Field(False, description="Needs airport/airstrip")


class Resource(BaseModel):
    """A deployable disaster response resource.

    The resource's status field is the critical piece — it is replicated
    across all ICPs via Raft log entries. Every status change is a
    committed state transition requiring quorum ack.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique resource ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Identity
    name: str = Field(..., min_length=1, description="Human-readable name (e.g., 'SAR Team Alpha')")
    callsign: str = Field(..., min_length=1, max_length=20, description="Radio callsign (e.g., 'ALPHA-7')")
    resource_type: ResourceType = Field(..., description="Resource classification")
    owning_agency_id: str = Field(..., description="Agency that owns this resource")

    # Capabilities
    capabilities: ResourceCapabilities = Field(
        default_factory=ResourceCapabilities,
        description="What this resource can do",
    )

    # Location
    home_base: GeoLocation = Field(..., description="Base/staging area location")
    current_location: GeoLocation | None = Field(None, description="Current GPS position (if tracking)")

    # State — replicated via Raft
    status: ResourceStatus = Field(ResourceStatus.AVAILABLE, description="Current deployment state")
    last_transition_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of last state transition",
    )

    # Current assignment (populated when DISPATCHED or ON_SCENE)
    assigned_zone_id: str | None = Field(None, description="Zone this resource is assigned to")
    assigned_incident_id: str | None = Field(None, description="Incident this resource is responding to")
    dispatched_by: str | None = Field(None, description="Commander ID who confirmed dispatch")
    dispatch_expires_at: datetime | None = Field(
        None, description="Dispatch timeout — auto-cancel if not on scene"
    )

    # Operational
    hours_deployed: float = Field(0.0, ge=0, description="Hours deployed in current shift")
    max_shift_hours: float = Field(12.0, ge=1, description="Maximum shift duration before mandatory rest")

    # Raft metadata
    raft_log_index: int | None = Field(
        None, description="Raft log index of the last state transition"
    )

    @property
    def is_available(self) -> bool:
        """True if resource can be dispatched."""
        return self.status == ResourceStatus.AVAILABLE

    @property
    def is_fatigued(self) -> bool:
        """True if resource has exceeded max shift hours."""
        return self.hours_deployed >= self.max_shift_hours

    model_config = {"json_schema_extra": {"examples": [
        {
            "name": "SAR Team Alpha",
            "callsign": "ALPHA-7",
            "resource_type": "sar_team_urban",
            "owning_agency_id": "agency-ndrf",
            "capabilities": {
                "personnel_count": 12,
                "has_medical_personnel": True,
                "can_perform_sar": True,
                "has_listening_devices": True,
                "has_thermal_imaging": True,
                "can_access_rough_terrain": True,
                "max_range_km": 200,
                "fuel_hours_remaining": 8.0,
            },
            "home_base": {"latitude": 28.5672, "longitude": 77.2100},
            "status": "available",
        }
    ]}}


class ResourceStateTransition(BaseModel):
    """A resource state transition — the command written to the Raft log.

    This is the atomic unit of the replicated state machine. Each instance
    becomes a Raft log entry committed by quorum before becoming visible.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Transition ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # What changed
    resource_id: str = Field(..., description="Resource being transitioned")
    from_status: ResourceStatus = Field(..., description="Previous state")
    to_status: ResourceStatus = Field(..., description="New state")

    # Where
    zone_id: str | None = Field(None, description="Target zone (if dispatch)")
    incident_id: str | None = Field(None, description="Related incident")

    # Who / why
    confirmation_source: ConfirmationSource | None = Field(
        None, description="Required for DISPATCHED transitions"
    )
    actor_id: str = Field(..., description="User/system that initiated the transition")
    actor_agency_id: str = Field("", description="Agency of the actor")
    reason: str = Field("", description="Human-readable reason for the transition")

    # AI decision context (audit trail)
    ai_recommendation: str | None = Field(None, description="What the AI agent recommended")
    ai_confidence: float | None = Field(None, ge=0.0, le=1.0, description="AI confidence (0-1)")
    commander_override: bool = Field(False, description="True if commander overrode AI")
    override_reason: str | None = Field(None, description="Commander's reason for override")

    # Raft metadata (populated after commit)
    raft_term: int | None = Field(None, description="Raft term when committed")
    raft_log_index: int | None = Field(None, description="Raft log index after commit")

    def validate_transition(self) -> bool:
        """Validate this transition against the state machine rules.

        Returns:
            True if the transition is valid.

        Raises:
            ValueError: If the transition violates state machine rules.
        """
        if not is_valid_transition(self.from_status, self.to_status):
            raise ValueError(
                f"Invalid resource state transition: {self.from_status} → {self.to_status}. "
                f"Valid transitions from {self.from_status}: "
                f"{VALID_TRANSITIONS.get(self.from_status, set())}"
            )

        # DISPATCHED transitions MUST have a confirmation source
        if self.to_status == ResourceStatus.DISPATCHED and self.confirmation_source is None:
            raise ValueError(
                "RESOURCE_DISPATCHED transitions require a confirmation_source "
                "(Incident Commander confirmation gate). "
                "No autonomous dispatch permitted."
            )

        return True
