"""
Unit tests for Salus disaster response data models.

Tests Pydantic validation, resource state machine transitions,
and data model invariants.
"""

from __future__ import annotations

import pytest

from salus.models.agency import Agency, AgencyType, ICPStatus
from salus.models.dispatch import DispatchOrder, DispatchStatus
from salus.models.incident import Incident, IncidentSeverity, IncidentStatus, IncidentType
from salus.models.resource import (
    ConfirmationSource,
    GeoLocation,
    Resource,
    ResourceCapabilities,
    ResourceStatus,
    ResourceStateTransition,
    ResourceType,
    is_valid_transition,
)
from salus.models.zone import (
    AccessStatus,
    DamageLevel,
    DisasterZone,
    ZoneBoundary,
    ZoneNeeds,
    ZonePriority,
)
from salus.models.zone import GeoLocation as ZoneGeoLocation


# ============================================================================
# Resource Model Tests
# ============================================================================


class TestResourceType:
    """Test resource type enum."""

    def test_all_types_defined(self) -> None:
        types = list(ResourceType)
        assert len(types) >= 8  # Roadmap requires 8+ types

    def test_type_values(self) -> None:
        assert ResourceType.HELICOPTER_TRANSPORT == "helicopter_transport"
        assert ResourceType.SAR_TEAM_URBAN == "sar_team_urban"
        assert ResourceType.K9_UNIT == "k9_unit"


class TestResourceStatus:
    """Test resource status enum."""

    def test_all_states_defined(self) -> None:
        assert ResourceStatus.AVAILABLE == "available"
        assert ResourceStatus.DISPATCHED == "dispatched"
        assert ResourceStatus.ON_SCENE == "on_scene"
        assert ResourceStatus.RETURNING == "returning"
        assert ResourceStatus.NEEDS_RESUPPLY == "needs_resupply"
        assert ResourceStatus.RESUPPLYING == "resupplying"
        assert ResourceStatus.MAINTENANCE == "maintenance"


class TestResource:
    """Test resource entity model."""

    def test_create_resource(self, available_helicopter: Resource) -> None:
        assert available_helicopter.name == "Helo-3"
        assert available_helicopter.resource_type == ResourceType.HELICOPTER_TRANSPORT
        assert available_helicopter.status == ResourceStatus.AVAILABLE

    def test_default_status_is_available(self) -> None:
        resource = Resource(
            name="Test",
            callsign="TST-1",
            resource_type=ResourceType.AMBULANCE_ALS,
            owning_agency_id="agency-1",
            home_base=GeoLocation(latitude=28.5, longitude=77.2),
        )
        assert resource.status == ResourceStatus.AVAILABLE

    def test_resource_id_auto_generated(self) -> None:
        r1 = Resource(
            name="R1", callsign="R-1", resource_type=ResourceType.FIRE_ENGINE,
            owning_agency_id="a1", home_base=GeoLocation(latitude=28.5, longitude=77.2),
        )
        r2 = Resource(
            name="R2", callsign="R-2", resource_type=ResourceType.FIRE_ENGINE,
            owning_agency_id="a1", home_base=GeoLocation(latitude=28.5, longitude=77.2),
        )
        assert r1.id != r2.id

    def test_is_available_property(self, available_helicopter: Resource) -> None:
        assert available_helicopter.is_available is True

    def test_is_not_available_when_dispatched(self, dispatched_rescue_team: Resource) -> None:
        assert dispatched_rescue_team.is_available is False

    def test_fatigue_detection(self) -> None:
        resource = Resource(
            name="Tired", callsign="TRD-1",
            resource_type=ResourceType.SAR_TEAM_URBAN,
            owning_agency_id="a1",
            home_base=GeoLocation(latitude=28.5, longitude=77.2),
            hours_deployed=14.0,
            max_shift_hours=12.0,
        )
        assert resource.is_fatigued is True

    def test_serialization_roundtrip(self, available_helicopter: Resource) -> None:
        json_str = available_helicopter.model_dump_json()
        restored = Resource.model_validate_json(json_str)
        assert restored.name == available_helicopter.name
        assert restored.status == available_helicopter.status
        assert restored.resource_type == available_helicopter.resource_type


# ============================================================================
# Zone Model Tests
# ============================================================================


class TestZonePriority:
    """Test zone priority enum."""

    def test_priority_ordering(self) -> None:
        assert ZonePriority.CRITICAL < ZonePriority.HIGH
        assert ZonePriority.HIGH < ZonePriority.MODERATE
        assert ZonePriority.MODERATE < ZonePriority.LOW
        assert ZonePriority.LOW < ZonePriority.MINIMAL

    def test_priority_values(self) -> None:
        assert ZonePriority.CRITICAL == 1
        assert ZonePriority.MINIMAL == 5


class TestDisasterZone:
    """Test disaster zone model."""

    def test_create_zone(self, critical_zone: DisasterZone) -> None:
        assert critical_zone.zone_code == "Z-07"
        assert critical_zone.priority == ZonePriority.CRITICAL
        assert critical_zone.damage_level == DamageLevel.CATASTROPHIC

    def test_is_critical_property(self, critical_zone: DisasterZone) -> None:
        assert critical_zone.is_critical is True

    def test_not_critical(self, low_priority_zone: DisasterZone) -> None:
        assert low_priority_zone.is_critical is False

    def test_is_unserved(self, critical_zone: DisasterZone) -> None:
        assert critical_zone.is_unserved is True

    def test_has_trapped_persons(self, critical_zone: DisasterZone) -> None:
        assert critical_zone.has_trapped_persons is True

    def test_no_trapped_persons(self, low_priority_zone: DisasterZone) -> None:
        assert low_priority_zone.has_trapped_persons is False

    def test_zone_serialization(self, critical_zone: DisasterZone) -> None:
        json_str = critical_zone.model_dump_json()
        restored = DisasterZone.model_validate_json(json_str)
        assert restored.zone_code == critical_zone.zone_code
        assert restored.priority == critical_zone.priority


# ============================================================================
# Incident Model Tests
# ============================================================================


class TestIncident:
    """Test incident model."""

    def test_create_incident(self, earthquake_incident: Incident) -> None:
        assert earthquake_incident.incident_type == IncidentType.EARTHQUAKE
        assert earthquake_incident.severity == IncidentSeverity.LEVEL_3
        assert earthquake_incident.status == IncidentStatus.ACTIVE

    def test_incident_types(self) -> None:
        types = list(IncidentType)
        assert IncidentType.EARTHQUAKE in types
        assert IncidentType.FLOOD in types
        assert IncidentType.BUILDING_COLLAPSE in types
        assert len(types) >= 8

    def test_incident_id_auto_generated(self) -> None:
        i1 = Incident(name="Test 1", incident_type=IncidentType.FLOOD)
        i2 = Incident(name="Test 2", incident_type=IncidentType.FLOOD)
        assert i1.id != i2.id


# ============================================================================
# Agency Model Tests
# ============================================================================


class TestAgency:
    """Test agency model."""

    def test_create_agency(self, fire_department_agency: Agency) -> None:
        assert fire_department_agency.code == "FD-1"
        assert fire_department_agency.agency_type == AgencyType.FIRE_DEPARTMENT
        assert fire_department_agency.icp_status == ICPStatus.OPERATIONAL

    def test_agency_types(self) -> None:
        types = list(AgencyType)
        assert AgencyType.FIRE_DEPARTMENT in types
        assert AgencyType.EMS in types
        assert AgencyType.MILITARY in types
        assert AgencyType.NDRF in types

    def test_icp_status_values(self) -> None:
        assert ICPStatus.OPERATIONAL == "operational"
        assert ICPStatus.PARTITIONED == "partitioned"
        assert ICPStatus.DEGRADED == "degraded"


# ============================================================================
# Dispatch Order Tests
# ============================================================================


class TestDispatchOrder:
    """Test dispatch order model."""

    def test_create_dispatch(self, sample_dispatch_order: DispatchOrder) -> None:
        assert sample_dispatch_order.incident_id == "inc-001"
        assert sample_dispatch_order.zone_id == "zone-007"
        assert sample_dispatch_order.status == DispatchStatus.PENDING

    def test_dispatch_status_lifecycle(self) -> None:
        statuses = list(DispatchStatus)
        assert DispatchStatus.PENDING in statuses
        assert DispatchStatus.AWAITING_CONFIRMATION in statuses
        assert DispatchStatus.CONFIRMED in statuses
        assert DispatchStatus.COMMITTED in statuses
        assert DispatchStatus.REJECTED in statuses
        assert DispatchStatus.FALLBACK in statuses

    def test_dispatch_serialization(self, sample_dispatch_order: DispatchOrder) -> None:
        json_str = sample_dispatch_order.model_dump_json()
        restored = DispatchOrder.model_validate_json(json_str)
        assert restored.incident_id == sample_dispatch_order.incident_id


# ============================================================================
# Resource Capabilities Tests
# ============================================================================


class TestResourceCapabilities:
    """Test resource capabilities model."""

    def test_default_capabilities(self) -> None:
        cap = ResourceCapabilities()
        assert cap.personnel_count == 0
        assert cap.can_perform_sar is False
        assert cap.can_access_air is False

    def test_sar_team_capabilities(self) -> None:
        cap = ResourceCapabilities(
            personnel_count=12,
            can_perform_sar=True,
            has_listening_devices=True,
            has_thermal_imaging=True,
        )
        assert cap.can_perform_sar is True
        assert cap.has_listening_devices is True

    def test_helicopter_capabilities(self) -> None:
        cap = ResourceCapabilities(
            can_access_air=True,
            max_range_km=600.0,
            passenger_capacity=12,
        )
        assert cap.can_access_air is True
        assert cap.max_range_km == 600.0
