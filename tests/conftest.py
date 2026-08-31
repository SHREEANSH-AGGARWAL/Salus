"""
Shared test fixtures for Salus disaster response.

Provides realistic test data factories for resources, zones, agencies,
incidents, and dispatch orders. Used across unit, integration, and chaos tests.
"""

from __future__ import annotations

import pytest

from salus.models.agency import Agency, AgencyType, ICPStatus
from salus.models.common import GeoLocation
from salus.models.dispatch import DispatchOrder, DispatchStatus
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
    ZoneBoundary,
    ZoneNeeds,
    ZonePriority,
)


# ============================================================================
# Resource Fixtures
# ============================================================================


@pytest.fixture
def available_helicopter() -> Resource:
    """An available transport helicopter."""
    return Resource(
        name="Helo-3",
        callsign="HELO-3",
        resource_type=ResourceType.HELICOPTER_TRANSPORT,
        owning_agency_id="agency-fire",
        capabilities=ResourceCapabilities(
            personnel_count=4,
            passenger_capacity=12,
            cargo_capacity_kg=2500.0,
            can_access_air=True,
            max_range_km=600.0,
            fuel_hours_remaining=4.0,
        ),
        home_base=GeoLocation(latitude=28.5672, longitude=77.2100),
        status=ResourceStatus.AVAILABLE,
    )


@pytest.fixture
def dispatched_rescue_team() -> Resource:
    """A dispatched urban SAR team."""
    return Resource(
        name="SAR Team Alpha",
        callsign="ALPHA-7",
        resource_type=ResourceType.SAR_TEAM_URBAN,
        owning_agency_id="agency-ndrf",
        capabilities=ResourceCapabilities(
            personnel_count=12,
            has_medical_personnel=True,
            can_perform_sar=True,
            has_listening_devices=True,
            has_thermal_imaging=True,
            can_access_rough_terrain=True,
            max_range_km=200.0,
            fuel_hours_remaining=8.0,
        ),
        home_base=GeoLocation(latitude=28.5500, longitude=77.1900),
        status=ResourceStatus.DISPATCHED,
        assigned_zone_id="zone-007",
        assigned_incident_id="inc-001",
        dispatched_by="cmd-vikram",
    )


@pytest.fixture
def sample_ambulance() -> Resource:
    """An available ALS ambulance."""
    return Resource(
        name="ALS-Ambulance-1",
        callsign="ALS-1",
        resource_type=ResourceType.AMBULANCE_ALS,
        owning_agency_id="agency-ems",
        capabilities=ResourceCapabilities(
            personnel_count=3,
            has_medical_personnel=True,
            passenger_capacity=2,
            can_perform_medical=True,
            max_range_km=300.0,
            fuel_hours_remaining=10.0,
        ),
        home_base=GeoLocation(latitude=28.5700, longitude=77.2200),
        status=ResourceStatus.AVAILABLE,
    )


@pytest.fixture
def sample_resources(
    available_helicopter: Resource,
    dispatched_rescue_team: Resource,
    sample_ambulance: Resource,
) -> list[Resource]:
    """A mixed set of resources in various states."""
    fire_engine = Resource(
        name="Engine-5",
        callsign="ENG-5",
        resource_type=ResourceType.FIRE_ENGINE,
        owning_agency_id="agency-fire",
        capabilities=ResourceCapabilities(
            personnel_count=6,
            can_perform_firefighting=True,
            can_access_rough_terrain=True,
            max_range_km=200.0,
            fuel_hours_remaining=8.0,
        ),
        home_base=GeoLocation(latitude=28.5600, longitude=77.2050),
        status=ResourceStatus.AVAILABLE,
    )
    maintenance_gen = Resource(
        name="GenSet-2",
        callsign="GEN-2",
        resource_type=ResourceType.GENERATOR,
        owning_agency_id="agency-fire",
        capabilities=ResourceCapabilities(personnel_count=2),
        home_base=GeoLocation(latitude=28.5550, longitude=77.2000),
        status=ResourceStatus.MAINTENANCE,
    )
    return [
        available_helicopter,
        dispatched_rescue_team,
        sample_ambulance,
        fire_engine,
        maintenance_gen,
    ]


# ============================================================================
# Zone Fixtures
# ============================================================================


@pytest.fixture
def critical_zone() -> DisasterZone:
    """P1 critical zone — active entrapment, mass casualties."""
    return DisasterZone(
        name="Sector 7 — Old City Market",
        zone_code="Z-07",
        boundary=ZoneBoundary(
            center=GeoLocation(latitude=28.6562, longitude=77.2310),
            radius_km=1.5,
        ),
        address_description="Old Delhi market area, densely populated, narrow streets",
        priority=ZonePriority.CRITICAL,
        damage_level=DamageLevel.CATASTROPHIC,
        access_status=AccessStatus.RESTRICTED,
        needs=ZoneNeeds(
            needs_sar=True,
            needs_medical=True,
            needs_evacuation=True,
            estimated_trapped=45,
            estimated_injured=120,
            estimated_displaced=2000,
            estimated_population=15000,
        ),
        time_since_last_contact_minutes=25,
        assessment_confidence=0.85,
    )


@pytest.fixture
def low_priority_zone() -> DisasterZone:
    """P4 low-priority zone — minor damage."""
    return DisasterZone(
        name="Sector 13 — Suburban West",
        zone_code="Z-13",
        boundary=ZoneBoundary(
            center=GeoLocation(latitude=28.5800, longitude=77.1500),
            radius_km=2.5,
        ),
        address_description="Low-density housing, good road access",
        priority=ZonePriority.LOW,
        damage_level=DamageLevel.LIGHT,
        access_status=AccessStatus.OPEN,
        needs=ZoneNeeds(
            needs_water=True,
            needs_power=True,
            estimated_displaced=150,
            estimated_population=8000,
        ),
        time_since_last_contact_minutes=5,
        assessment_confidence=0.95,
    )


@pytest.fixture
def air_only_zone() -> DisasterZone:
    """Zone accessible only by air — ground routes blocked."""
    return DisasterZone(
        name="Sector 5 — Riverside Colony",
        zone_code="Z-05",
        boundary=ZoneBoundary(
            center=GeoLocation(latitude=28.6200, longitude=77.2400),
            radius_km=1.0,
        ),
        address_description="Flood-prone area along river",
        priority=ZonePriority.HIGH,
        damage_level=DamageLevel.SEVERE,
        access_status=AccessStatus.AIR_ONLY,
        needs=ZoneNeeds(
            needs_sar=True,
            needs_medical=True,
            needs_evacuation=True,
            estimated_trapped=15,
            estimated_injured=40,
            estimated_displaced=800,
            estimated_population=5000,
        ),
        time_since_last_contact_minutes=90,
    )


# ============================================================================
# Agency Fixtures
# ============================================================================


@pytest.fixture
def fire_department_agency() -> Agency:
    """Fire department agency with ICP."""
    return Agency(
        name="Fire Department",
        code="FD-1",
        agency_type=AgencyType.FIRE_DEPARTMENT,
        incident_commander="Chief Rajesh Kumar",
        commander_contact="VHF-CH-1",
        icp_location=GeoLocation(latitude=28.5500, longitude=77.2000),
        icp_status=ICPStatus.OPERATIONAL,
        raft_node_id="node-alpha",
        grpc_address="icp-alpha:50051",
        api_address="icp-alpha:8000",
    )


@pytest.fixture
def ems_agency() -> Agency:
    """EMS agency with ICP."""
    return Agency(
        name="Emergency Medical Services",
        code="EMS-1",
        agency_type=AgencyType.EMS,
        incident_commander="Dr. Priya Sharma",
        commander_contact="SAT-CH-3",
        icp_location=GeoLocation(latitude=28.5700, longitude=77.2200),
        icp_status=ICPStatus.OPERATIONAL,
        raft_node_id="node-bravo",
        grpc_address="icp-bravo:50051",
    )


# ============================================================================
# Incident Fixtures
# ============================================================================


@pytest.fixture
def earthquake_incident() -> Incident:
    """Active earthquake incident."""
    return Incident(
        name="2026 Delhi NCR Earthquake",
        incident_type=IncidentType.EARTHQUAKE,
        severity=IncidentSeverity.LEVEL_3,
        status=IncidentStatus.ACTIVE,
        description=(
            "7.2 magnitude earthquake, epicenter 40km NW of Delhi. "
            "Multiple building collapses in Old Delhi and East Delhi."
        ),
        location_description="Delhi National Capital Region",
        unified_command=True,
    )


# ============================================================================
# Dispatch Fixtures
# ============================================================================


@pytest.fixture
def sample_dispatch_order() -> DispatchOrder:
    """A pending dispatch order."""
    return DispatchOrder(
        incident_id="inc-001",
        zone_id="zone-007",
        requesting_icp_id="icp-alpha",
        status=DispatchStatus.PENDING,
    )
