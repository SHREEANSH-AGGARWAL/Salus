"""Salus data models — Pydantic v2 schemas for all domain entities.

Models:
    - Resource: Deployable disaster response resource (helicopter, SAR team, etc.)
    - DisasterZone: Geographic zone affected by a disaster
    - Incident: Top-level disaster event
    - Agency: Responding agency and its ICP (Incident Command Post)
    - DispatchOrder: Full decision record from the 5-agent pipeline
"""

from salus.models.common import GeoLocation

from salus.models.agency import Agency, AgencyType, ICPStatus
from salus.models.dispatch import (
    DamageAssessmentResult,
    DispatchOrder,
    DispatchStatus,
    ResourceMatchResult,
    RouteResult,
)
from salus.models.incident import Incident, IncidentSeverity, IncidentStatus, IncidentType
from salus.models.resource import (
    ConfirmationSource,
    Resource,
    ResourceCapabilities,
    ResourceStatus,
    ResourceStateTransition,
    ResourceType,
)
from salus.models.zone import (
    AccessStatus,
    DamageLevel,
    DisasterZone,
    ZoneNeeds,
    ZonePriority,
)

__all__ = [
    # Resource
    "Resource",
    "ResourceType",
    "ResourceStatus",
    "ResourceCapabilities",
    "ResourceStateTransition",
    "ConfirmationSource",
    # Zone
    "DisasterZone",
    "ZonePriority",
    "DamageLevel",
    "AccessStatus",
    "ZoneNeeds",
    # Incident
    "Incident",
    "IncidentType",
    "IncidentSeverity",
    "IncidentStatus",
    # Agency
    "Agency",
    "AgencyType",
    "ICPStatus",
    # Dispatch
    "DispatchOrder",
    "DispatchStatus",
    "DamageAssessmentResult",
    "ResourceMatchResult",
    "RouteResult",
]
