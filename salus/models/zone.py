"""
Disaster zone data model.

Represents a geographic zone affected by a disaster, with damage assessment,
priority scoring, and resource needs tracking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field

from salus.models.common import GeoLocation


class ZonePriority(IntEnum):
    """Zone priority levels (P1–P5) based on damage assessment.

    P1: Critical — immediate life threat, active entrapment, mass casualties.
    P2: High — significant casualties, structural collapse, urgent needs.
    P3: Moderate — infrastructure damage, displaced population, no immediate life threat.
    P4: Low — minor damage, self-sufficient population, can wait.
    P5: Minimal — cosmetic damage, no intervention needed.
    """

    CRITICAL = 1
    HIGH = 2
    MODERATE = 3
    LOW = 4
    MINIMAL = 5


class DamageLevel(StrEnum):
    """Structural damage assessment categories."""

    CATASTROPHIC = "catastrophic"    # >70% structures collapsed/destroyed
    SEVERE = "severe"                # 40-70% structures damaged significantly
    MODERATE = "moderate"            # 10-40% structures with damage
    LIGHT = "light"                  # <10% structures with minor damage
    NONE = "none"                    # No visible damage
    UNKNOWN = "unknown"              # Not yet assessed


class AccessStatus(StrEnum):
    """How accessible is this zone for response teams."""

    OPEN = "open"                    # Roads clear, full access
    RESTRICTED = "restricted"        # Some routes blocked, alternative available
    AIR_ONLY = "air_only"            # Ground routes blocked, helicopter access only
    WATER_ONLY = "water_only"        # Flooded, boat access only
    CUT_OFF = "cut_off"              # No known access route — requires engineering
    UNKNOWN = "unknown"              # Not yet assessed


class ZoneNeeds(BaseModel):
    """What this zone needs right now — used for resource matching."""

    needs_sar: bool = Field(False, description="Active search and rescue needed")
    needs_medical: bool = Field(False, description="Medical teams needed")
    needs_evacuation: bool = Field(False, description="Evacuation of population needed")
    needs_water: bool = Field(False, description="Potable water supply needed")
    needs_food: bool = Field(False, description="Food supply needed")
    needs_shelter: bool = Field(False, description="Temporary shelter needed")
    needs_power: bool = Field(False, description="Power/generators needed")
    needs_hazmat: bool = Field(False, description="HAZMAT decontamination needed")
    needs_firefighting: bool = Field(False, description="Fire suppression needed")
    needs_engineering: bool = Field(False, description="Road clearing, debris removal")
    needs_communication: bool = Field(False, description="Communication equipment needed")

    estimated_trapped: int = Field(0, ge=0, description="Estimated people trapped")
    estimated_injured: int = Field(0, ge=0, description="Estimated people injured")
    estimated_displaced: int = Field(0, ge=0, description="Estimated people displaced")
    estimated_population: int = Field(0, ge=0, description="Total zone population")


class ZoneBoundary(BaseModel):
    """Zone boundary defined as a bounding box for simplicity."""

    center: GeoLocation = Field(..., description="Zone center point")
    radius_km: float = Field(1.0, gt=0, description="Approximate zone radius in km")


class DisasterZone(BaseModel):
    """A geographic zone affected by a disaster.

    Zones are the allocation targets — resources are dispatched TO zones.
    Zone priority and needs are assessed by the Damage Assessment Agent
    and updated as the situation evolves.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique zone ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Identity
    name: str = Field(..., min_length=1, description="Zone name (e.g., 'Sector 7 — Old City')")
    zone_code: str = Field(..., min_length=1, max_length=10, description="Short code (e.g., 'Z-07')")

    # Geography
    boundary: ZoneBoundary
    address_description: str = Field("", description="Human-readable location description")

    # Assessment
    priority: ZonePriority = Field(ZonePriority.MODERATE, description="Response priority (P1–P5)")
    damage_level: DamageLevel = Field(DamageLevel.UNKNOWN, description="Structural damage level")
    access_status: AccessStatus = Field(AccessStatus.UNKNOWN, description="Current accessibility")
    needs: ZoneNeeds = Field(default_factory=ZoneNeeds, description="Current resource needs")

    # Assessment metadata
    last_assessed_at: datetime | None = Field(None, description="When zone was last assessed")
    last_assessed_by: str | None = Field(None, description="Who/what performed last assessment")
    assessment_confidence: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Confidence in current assessment (0=unknown, 1=verified on-ground)"
    )

    # Time tracking
    time_since_last_contact_minutes: int = Field(
        0, ge=0,
        description="Minutes since last communication with this zone. "
        "Long gaps increase priority — no contact ≠ no need."
    )

    # Resource tracking (populated from Raft state)
    assigned_resource_ids: list[str] = Field(
        default_factory=list,
        description="Resources currently assigned to this zone",
    )
    resources_on_scene: int = Field(0, ge=0, description="Count of resources ON_SCENE")
    resources_en_route: int = Field(0, ge=0, description="Count of resources DISPATCHED (en route)")

    @property
    def is_critical(self) -> bool:
        """True if zone needs immediate attention."""
        return self.priority == ZonePriority.CRITICAL

    @property
    def is_unserved(self) -> bool:
        """True if no resources are assigned or en route."""
        return len(self.assigned_resource_ids) == 0

    @property
    def has_trapped_persons(self) -> bool:
        """True if there are estimated trapped persons."""
        return self.needs.estimated_trapped > 0

    model_config = {"json_schema_extra": {"examples": [
        {
            "name": "Sector 7 — Old City Market",
            "zone_code": "Z-07",
            "boundary": {
                "center": {"latitude": 28.6562, "longitude": 77.2310},
                "radius_km": 1.5,
            },
            "address_description": "Old Delhi market area, densely populated, narrow streets",
            "priority": 1,
            "damage_level": "catastrophic",
            "access_status": "restricted",
            "needs": {
                "needs_sar": True,
                "needs_medical": True,
                "estimated_trapped": 45,
                "estimated_injured": 120,
                "estimated_displaced": 2000,
                "estimated_population": 15000,
            },
        }
    ]}}
