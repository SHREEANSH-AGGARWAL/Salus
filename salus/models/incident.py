"""
Incident data model.

Represents a disaster event (earthquake, flood, wildfire, etc.) and
the overall coordination context. An incident contains multiple zones
and triggers the dispatch of resources.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class IncidentType(StrEnum):
    """Types of disaster incidents."""

    EARTHQUAKE = "earthquake"
    FLOOD = "flood"
    WILDFIRE = "wildfire"
    CYCLONE = "cyclone"
    TSUNAMI = "tsunami"
    INDUSTRIAL_ACCIDENT = "industrial_accident"
    HAZMAT_SPILL = "hazmat_spill"
    BUILDING_COLLAPSE = "building_collapse"
    LANDSLIDE = "landslide"
    MASS_CASUALTY = "mass_casualty"
    MULTI_HAZARD = "multi_hazard"


class IncidentSeverity(StrEnum):
    """Overall incident severity — determines resource mobilization level."""

    LEVEL_1 = "level_1"    # Local — single agency can handle
    LEVEL_2 = "level_2"    # Regional — multiple agencies needed
    LEVEL_3 = "level_3"    # State — state-level mobilization
    LEVEL_4 = "level_4"    # National — national disaster declaration
    LEVEL_5 = "level_5"    # International — UN/international assistance


class IncidentStatus(StrEnum):
    """Lifecycle status of an incident."""

    DECLARED = "declared"          # Incident declared, mobilization starting
    ACTIVE = "active"              # Active response operations ongoing
    CONTAINED = "contained"        # Situation stabilized, response winding down
    RECOVERY = "recovery"          # Immediate threat over, recovery operations
    CLOSED = "closed"              # Incident closed


class IncidentSummary(BaseModel):
    """Aggregated statistics for an incident."""

    total_zones: int = Field(0, ge=0)
    zones_critical: int = Field(0, ge=0, description="P1 zones")
    zones_high: int = Field(0, ge=0, description="P2 zones")
    zones_unserved: int = Field(0, ge=0, description="Zones with no resources assigned")
    total_resources_deployed: int = Field(0, ge=0)
    total_resources_available: int = Field(0, ge=0)
    estimated_affected_population: int = Field(0, ge=0)
    estimated_casualties: int = Field(0, ge=0)
    dispatches_completed: int = Field(0, ge=0)
    double_dispatches: int = Field(0, ge=0, description="Should always be 0 under Raft")


class Incident(BaseModel):
    """A disaster incident — the top-level coordination entity.

    An incident is the context for everything: it contains zones,
    triggers resource dispatch, and is managed by a Unified Command
    structure across multiple agencies.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique incident ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Identity
    name: str = Field(..., min_length=1, description="Incident name (e.g., '2026 Delhi Earthquake')")
    incident_type: IncidentType = Field(..., description="Type of disaster")
    severity: IncidentSeverity = Field(IncidentSeverity.LEVEL_2, description="Severity level")
    status: IncidentStatus = Field(IncidentStatus.DECLARED, description="Current status")

    # Description
    description: str = Field("", description="Detailed incident description")
    location_description: str = Field("", description="General location of the incident")

    # Scope
    zone_ids: list[str] = Field(default_factory=list, description="Zones within this incident")
    responding_agency_ids: list[str] = Field(
        default_factory=list,
        description="Agencies responding to this incident",
    )

    # Command
    incident_commander_id: str | None = Field(
        None, description="Current Incident Commander (IC)"
    )
    unified_command: bool = Field(
        False, description="True if multiple agencies in Unified Command"
    )

    # Statistics (updated periodically)
    summary: IncidentSummary = Field(
        default_factory=IncidentSummary,
        description="Aggregated incident statistics",
    )

    # Timeline
    declared_at: datetime = Field(default_factory=datetime.utcnow)
    contained_at: datetime | None = Field(None)
    closed_at: datetime | None = Field(None)

    model_config = {"json_schema_extra": {"examples": [
        {
            "name": "2026 Delhi NCR Earthquake",
            "incident_type": "earthquake",
            "severity": "level_3",
            "status": "active",
            "description": "7.2 magnitude earthquake, epicenter 40km NW of Delhi. "
            "Multiple building collapses in Old Delhi and East Delhi. "
            "Infrastructure damage to roads, bridges, and utilities.",
            "location_description": "Delhi National Capital Region",
            "unified_command": True,
        }
    ]}}
