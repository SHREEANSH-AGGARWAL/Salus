"""
Unit tests for simulation test data generators.

Verifies that generated data passes model validation,
output counts match requests, and seeded runs are reproducible.
"""

from __future__ import annotations

from simulation.generators import (
    generate_agencies,
    generate_incidents,
    generate_resources,
    generate_zones,
)


class TestGenerateAgencies:
    """Test agency generation."""

    def test_default_generates_three(self) -> None:
        agencies = generate_agencies()
        assert len(agencies) == 3

    def test_custom_count(self) -> None:
        agencies = generate_agencies(n=5)
        assert len(agencies) == 5

    def test_max_count(self) -> None:
        agencies = generate_agencies(n=100)
        assert len(agencies) == 5  # Capped at templates

    def test_all_valid_models(self) -> None:
        agencies = generate_agencies()
        for agency in agencies:
            assert agency.name
            assert agency.code
            assert agency.agency_type
            # Verify serialization works
            agency.model_dump_json()

    def test_unique_ids(self) -> None:
        agencies = generate_agencies()
        ids = [a.id for a in agencies]
        assert len(ids) == len(set(ids))


class TestGenerateZones:
    """Test zone generation."""

    def test_default_generates_ten(self) -> None:
        zones = generate_zones()
        assert len(zones) == 10

    def test_custom_count(self) -> None:
        zones = generate_zones(n=5)
        assert len(zones) == 5

    def test_max_capped(self) -> None:
        zones = generate_zones(n=100)
        assert len(zones) == 15  # Capped at zone name templates

    def test_all_valid_models(self) -> None:
        zones = generate_zones()
        for zone in zones:
            assert zone.name
            assert zone.zone_code
            assert zone.boundary.center.latitude != 0
            # Verify serialization works
            zone.model_dump_json()

    def test_unique_codes(self) -> None:
        zones = generate_zones()
        codes = [z.zone_code for z in zones]
        assert len(codes) == len(set(codes))

    def test_seeded_reproducibility(self) -> None:
        z1 = generate_zones(n=5, seed=42)
        z2 = generate_zones(n=5, seed=42)
        for a, b in zip(z1, z2):
            assert a.zone_code == b.zone_code
            assert a.damage_level == b.damage_level
            assert a.needs.estimated_trapped == b.needs.estimated_trapped

    def test_different_seeds_different_data(self) -> None:
        z1 = generate_zones(n=5, seed=42)
        z2 = generate_zones(n=5, seed=99)
        # At least some data should differ
        damages_1 = [z.damage_level for z in z1]
        damages_2 = [z.damage_level for z in z2]
        assert damages_1 != damages_2


class TestGenerateResources:
    """Test resource generation."""

    def test_default_generates_thirty(self) -> None:
        resources = generate_resources()
        assert len(resources) == 30

    def test_custom_count(self) -> None:
        resources = generate_resources(n=10)
        assert len(resources) == 10

    def test_all_valid_models(self) -> None:
        resources = generate_resources()
        for resource in resources:
            assert resource.name
            assert resource.callsign
            assert resource.resource_type
            assert resource.owning_agency_id
            # Verify serialization works
            resource.model_dump_json()

    def test_distributed_across_agencies(self) -> None:
        resources = generate_resources(n=30)
        agencies = {r.owning_agency_id for r in resources}
        assert len(agencies) >= 2  # Should span multiple agencies

    def test_multiple_resource_types(self) -> None:
        resources = generate_resources(n=30)
        types = {r.resource_type for r in resources}
        assert len(types) >= 4  # Should have variety

    def test_seeded_reproducibility(self) -> None:
        r1 = generate_resources(n=10, seed=42)
        r2 = generate_resources(n=10, seed=42)
        for a, b in zip(r1, r2):
            assert a.name == b.name
            assert a.resource_type == b.resource_type

    def test_custom_agency_ids(self) -> None:
        resources = generate_resources(
            n=10,
            agency_ids=["my-agency-1", "my-agency-2"],
            seed=42,
        )
        for r in resources:
            assert r.owning_agency_id in ("my-agency-1", "my-agency-2")


class TestGenerateIncidents:
    """Test incident generation."""

    def test_generates_incidents(self) -> None:
        zones = generate_zones(n=5, seed=42)
        incidents = generate_incidents(zones, n=5)
        assert len(incidents) == 5

    def test_all_valid_models(self) -> None:
        zones = generate_zones(n=5, seed=42)
        incidents = generate_incidents(zones, n=3)
        for incident in incidents:
            assert incident.name
            assert incident.incident_type
            assert incident.status
            # Verify serialization works
            incident.model_dump_json()

    def test_incidents_linked_to_zones(self) -> None:
        zones = generate_zones(n=5, seed=42)
        zone_ids = {z.id for z in zones}
        incidents = generate_incidents(zones, n=3)
        for incident in incidents:
            for zid in incident.zone_ids:
                assert zid in zone_ids

    def test_seeded_reproducibility(self) -> None:
        zones = generate_zones(n=5, seed=42)
        i1 = generate_incidents(zones, n=3, seed=42)
        i2 = generate_incidents(zones, n=3, seed=42)
        for a, b in zip(i1, i2):
            assert a.incident_type == b.incident_type
