"""Unit tests for damage-aware Route Planning Engine (M10)."""

from __future__ import annotations

import pytest

from salus.models.resource import Resource, ResourceCapabilities, ResourceStatus, ResourceType
from salus.models.zone import (
    AccessStatus,
    DisasterZone,
    GeoLocation,
    ZoneBoundary,
)
from salus.routing.pathfinder import RoutePlanner


@pytest.fixture
def planner() -> RoutePlanner:
    return RoutePlanner()


@pytest.fixture
def ground_resource() -> Resource:
    return Resource(
        name="Ambulance-1",
        callsign="AMB-1",
        resource_type=ResourceType.AMBULANCE_ALS,
        owning_agency_id="agency-ems",
        home_base=GeoLocation(latitude=28.6000, longitude=77.2000),
        capabilities=ResourceCapabilities(
            personnel_count=3,
            has_medical_personnel=True,
            passenger_capacity=2,
            max_range_km=300.0,
            fuel_hours_remaining=8.0,
        ),
        status=ResourceStatus.AVAILABLE,
    )


@pytest.fixture
def air_resource() -> Resource:
    return Resource(
        name="Helo-1",
        callsign="HELO-1",
        resource_type=ResourceType.HELICOPTER_MEDICAL,
        owning_agency_id="agency-fire",
        home_base=GeoLocation(latitude=28.6000, longitude=77.2000),
        capabilities=ResourceCapabilities(
            personnel_count=4,
            can_access_air=True,
            max_range_km=500.0,
            fuel_hours_remaining=4.0,
        ),
        status=ResourceStatus.AVAILABLE,
    )


def test_ground_route_open(planner: RoutePlanner, ground_resource: Resource) -> None:
    zone = DisasterZone(
        name="Sector 1",
        zone_code="Z-01",
        boundary=ZoneBoundary(center=GeoLocation(latitude=28.6500, longitude=77.2500)),
        access_status=AccessStatus.OPEN,
    )
    result = planner.plan_route(ground_resource, zone)
    assert not result.requires_air
    assert result.estimated_travel_time_minutes > 0
    assert result.distance_km > 0
    assert "Standard surface convoy route" in result.route_description


def test_air_only_zone(
    planner: RoutePlanner, ground_resource: Resource, air_resource: Resource
) -> None:
    zone = DisasterZone(
        name="Mountain Sector",
        zone_code="Z-99",
        boundary=ZoneBoundary(center=GeoLocation(latitude=28.7000, longitude=77.3000)),
        access_status=AccessStatus.AIR_ONLY,
    )
    ground_result = planner.plan_route(ground_resource, zone)
    assert ground_result.estimated_travel_time_minutes == float("inf")
    assert "INACCESSIBLE" in ground_result.route_description

    air_result = planner.plan_route(air_resource, zone)
    assert air_result.requires_air
    assert air_result.estimated_travel_time_minutes < float("inf")
    assert "Air corridor direct" in air_result.route_description


def test_restricted_zone_detours(planner: RoutePlanner, ground_resource: Resource) -> None:
    zone = DisasterZone(
        name="Old City",
        zone_code="Z-02",
        boundary=ZoneBoundary(center=GeoLocation(latitude=28.6500, longitude=77.2500)),
        access_status=AccessStatus.RESTRICTED,
    )
    result = planner.plan_route(ground_resource, zone)
    assert not result.requires_air
    assert len(result.obstacles) > 0
    assert "urban detours" in result.route_description
