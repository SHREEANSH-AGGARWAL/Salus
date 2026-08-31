"""
Test data generators for disaster response simulation.

Generates realistic disaster zones, emergency resources, agencies,
incidents, and damage assessments. All generators use seeded random
for reproducibility.

Usage:
    zones = generate_zones(n=10, seed=42)
    resources = generate_resources(n=30, seed=42)
    agencies = generate_agencies()
    incidents = generate_incidents(zones, n=20, seed=42)
"""

from __future__ import annotations

import random
import uuid

from salus.models.agency import Agency, AgencyType, ICPStatus
from salus.models.incident import Incident, IncidentSeverity, IncidentStatus, IncidentType
from salus.models.resource import (
    Resource,
    ResourceCapabilities,
    ResourceStatus,
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
from salus.models.common import GeoLocation


# ============================================================================
# Zone Names and Descriptions
# ============================================================================

_ZONE_NAMES = [
    ("Sector 1 — Old City Market", "Z-01", "Dense market area, narrow lanes, old buildings"),
    ("Sector 2 — Residential East", "Z-02", "Multi-story apartment complexes, moderate density"),
    ("Sector 3 — Industrial Park", "Z-03", "Factories, warehouses, chemical storage"),
    ("Sector 4 — Hospital District", "Z-04", "Medical facilities, care homes, pharmacies"),
    ("Sector 5 — Riverside Colony", "Z-05", "Flood-prone area along river, low-rise housing"),
    ("Sector 6 — Highway Junction", "Z-06", "Major highway interchange, elevated roads"),
    ("Sector 7 — University Campus", "Z-07", "Large campus, dormitories, open grounds"),
    ("Sector 8 — Government Quarter", "Z-08", "Government buildings, embassies, wide roads"),
    ("Sector 9 — Slum Settlement", "Z-09", "Informal housing, high density, poor infrastructure"),
    ("Sector 10 — Tech Park", "Z-10", "Modern glass buildings, underground parking"),
    ("Sector 11 — Railway Station", "Z-11", "Major station, dense foot traffic, tunnels"),
    ("Sector 12 — Airport Approach", "Z-12", "Airport perimeter, fuel storage, cargo area"),
    ("Sector 13 — Suburban West", "Z-13", "Low-density housing, good road access"),
    ("Sector 14 — Lake District", "Z-14", "Recreational area, bridges, waterfront"),
    ("Sector 15 — Heritage Quarter", "Z-15", "Historic buildings, narrow streets, tourism zone"),
]

# ============================================================================
# Resource Templates
# ============================================================================

_RESOURCE_TEMPLATES: dict[ResourceType, dict] = {
    ResourceType.HELICOPTER_TRANSPORT: {
        "name_prefix": "Helo-Transport",
        "capabilities": {
            "personnel_count": 4,
            "has_medical_personnel": False,
            "passenger_capacity": 12,
            "cargo_capacity_kg": 2500.0,
            "can_access_air": True,
            "max_range_km": 600.0,
            "fuel_hours_remaining": 4.0,
        },
    },
    ResourceType.HELICOPTER_MEDICAL: {
        "name_prefix": "Medevac",
        "capabilities": {
            "personnel_count": 4,
            "has_medical_personnel": True,
            "passenger_capacity": 4,
            "cargo_capacity_kg": 1200.0,
            "can_perform_medical": True,
            "can_access_air": True,
            "max_range_km": 400.0,
            "fuel_hours_remaining": 3.5,
        },
    },
    ResourceType.SAR_TEAM_URBAN: {
        "name_prefix": "SAR-Urban",
        "capabilities": {
            "personnel_count": 12,
            "has_medical_personnel": True,
            "can_perform_sar": True,
            "has_listening_devices": True,
            "has_thermal_imaging": True,
            "can_access_rough_terrain": True,
            "max_range_km": 200.0,
            "fuel_hours_remaining": 8.0,
        },
    },
    ResourceType.SAR_TEAM_WATER: {
        "name_prefix": "SAR-Water",
        "capabilities": {
            "personnel_count": 8,
            "has_medical_personnel": True,
            "can_perform_sar": True,
            "can_perform_water_rescue": True,
            "can_access_water": True,
            "max_range_km": 100.0,
            "fuel_hours_remaining": 6.0,
        },
    },
    ResourceType.AMBULANCE_ALS: {
        "name_prefix": "ALS-Ambulance",
        "capabilities": {
            "personnel_count": 3,
            "has_medical_personnel": True,
            "passenger_capacity": 2,
            "can_perform_medical": True,
            "max_range_km": 300.0,
            "fuel_hours_remaining": 10.0,
        },
    },
    ResourceType.FIRE_ENGINE: {
        "name_prefix": "Engine",
        "capabilities": {
            "personnel_count": 6,
            "can_perform_firefighting": True,
            "can_access_rough_terrain": True,
            "max_range_km": 200.0,
            "fuel_hours_remaining": 8.0,
        },
    },
    ResourceType.EVACUATION_BUS: {
        "name_prefix": "EvacBus",
        "capabilities": {
            "personnel_count": 2,
            "passenger_capacity": 50,
            "max_range_km": 500.0,
            "fuel_hours_remaining": 12.0,
        },
    },
    ResourceType.SUPPLY_TRUCK: {
        "name_prefix": "Supply",
        "capabilities": {
            "personnel_count": 2,
            "cargo_capacity_kg": 10000.0,
            "max_range_km": 500.0,
            "fuel_hours_remaining": 12.0,
        },
    },
    ResourceType.GENERATOR: {
        "name_prefix": "GenSet",
        "capabilities": {
            "personnel_count": 2,
            "cargo_capacity_kg": 0.0,
            "max_range_km": 100.0,
            "fuel_hours_remaining": 24.0,
        },
    },
    ResourceType.K9_UNIT: {
        "name_prefix": "K9",
        "capabilities": {
            "personnel_count": 3,
            "can_perform_sar": True,
            "has_thermal_imaging": False,
            "can_access_rough_terrain": True,
            "max_range_km": 50.0,
            "fuel_hours_remaining": 6.0,
        },
    },
    ResourceType.ENGINEERING_UNIT: {
        "name_prefix": "Eng",
        "capabilities": {
            "personnel_count": 8,
            "can_clear_debris": True,
            "cargo_capacity_kg": 5000.0,
            "can_access_rough_terrain": True,
            "max_range_km": 150.0,
            "fuel_hours_remaining": 10.0,
        },
    },
    ResourceType.HAZMAT_TEAM: {
        "name_prefix": "HAZMAT",
        "capabilities": {
            "personnel_count": 6,
            "can_perform_hazmat": True,
            "max_range_km": 200.0,
            "fuel_hours_remaining": 6.0,
        },
    },
}


# ============================================================================
# Generators
# ============================================================================


def generate_agencies(n: int = 3) -> list[Agency]:
    """Generate disaster response agencies.

    Default: 3 agencies (Fire Department, EMS, Military/NDRF)
    matching the demo ICP cluster.

    Args:
        n: Number of agencies (1–5). Extra agencies are NGOs.

    Returns:
        List of Agency objects.
    """
    templates = [
        {
            "name": "Fire Department",
            "code": "FD-1",
            "agency_type": AgencyType.FIRE_DEPARTMENT,
            "incident_commander": "Chief Rajesh Kumar",
            "commander_contact": "VHF-CH-1",
            "icp_location": GeoLocation(latitude=28.5500, longitude=77.2000),
            "icp_status": ICPStatus.OPERATIONAL,
            "raft_node_id": "node-alpha",
            "grpc_address": "icp-alpha:50051",
            "api_address": "icp-alpha:8000",
            "connectivity_type": "lan",
        },
        {
            "name": "Emergency Medical Services",
            "code": "EMS-1",
            "agency_type": AgencyType.EMS,
            "incident_commander": "Dr. Priya Sharma",
            "commander_contact": "SAT-CH-3",
            "icp_location": GeoLocation(latitude=28.5700, longitude=77.2200),
            "icp_status": ICPStatus.OPERATIONAL,
            "raft_node_id": "node-bravo",
            "grpc_address": "icp-bravo:50051",
            "api_address": "icp-bravo:8000",
            "connectivity_type": "satellite",
        },
        {
            "name": "NDRF 1st Battalion",
            "code": "NDRF-1",
            "agency_type": AgencyType.NDRF,
            "incident_commander": "Cmdr. Vikram Singh",
            "commander_contact": "SAT-CH-7",
            "icp_location": GeoLocation(latitude=28.5300, longitude=77.1900),
            "icp_status": ICPStatus.OPERATIONAL,
            "raft_node_id": "node-charlie",
            "grpc_address": "icp-charlie:50051",
            "api_address": "icp-charlie:8000",
            "connectivity_type": "satellite",
        },
        {
            "name": "Red Cross Relief Unit",
            "code": "RC-1",
            "agency_type": AgencyType.RED_CROSS,
            "incident_commander": "Maria Santos",
            "commander_contact": "VHF-CH-9",
            "icp_location": GeoLocation(latitude=28.5600, longitude=77.2100),
            "icp_status": ICPStatus.DEPLOYING,
            "connectivity_type": "cellular",
        },
        {
            "name": "Municipal Emergency Management",
            "code": "MEM-1",
            "agency_type": AgencyType.GOVERNMENT,
            "incident_commander": "Commissioner Anil Mehta",
            "commander_contact": "LAN-HQ",
            "icp_location": GeoLocation(latitude=28.5800, longitude=77.2300),
            "icp_status": ICPStatus.OPERATIONAL,
            "connectivity_type": "lan",
        },
    ]

    return [Agency(**templates[i]) for i in range(min(n, len(templates)))]


def generate_zones(n: int = 10, seed: int = 42) -> list[DisasterZone]:
    """Generate disaster zones with realistic damage assessments.

    Args:
        n: Number of zones to generate (max 15).
        seed: Random seed for reproducibility.

    Returns:
        List of DisasterZone objects.
    """
    rng = random.Random(seed)
    n = min(n, len(_ZONE_NAMES))
    zones = []

    # Base coordinates (Delhi NCR area)
    base_lat, base_lon = 28.6, 77.2

    for i in range(n):
        name, code, desc = _ZONE_NAMES[i]

        # Randomized damage assessment
        damage_level = rng.choice(list(DamageLevel))
        if damage_level == DamageLevel.UNKNOWN:
            damage_level = DamageLevel.MODERATE

        access_status = rng.choice(list(AccessStatus))
        if access_status == AccessStatus.UNKNOWN:
            access_status = AccessStatus.RESTRICTED

        # Scale casualties by damage level
        damage_multiplier = {
            DamageLevel.CATASTROPHIC: 4,
            DamageLevel.SEVERE: 3,
            DamageLevel.MODERATE: 2,
            DamageLevel.LIGHT: 1,
            DamageLevel.NONE: 0,
        }.get(damage_level, 1)

        trapped = rng.randint(0, 15) * damage_multiplier
        injured = rng.randint(5, 30) * damage_multiplier
        displaced = rng.randint(100, 500) * damage_multiplier
        population = rng.randint(5000, 25000)

        needs = ZoneNeeds(
            needs_sar=trapped > 0,
            needs_medical=injured > 10,
            needs_evacuation=displaced > 500,
            needs_water=rng.random() > 0.4,
            needs_food=rng.random() > 0.5,
            needs_shelter=displaced > 200,
            needs_power=rng.random() > 0.3,
            needs_hazmat=damage_level == DamageLevel.CATASTROPHIC and rng.random() > 0.7,
            needs_firefighting=rng.random() > 0.6,
            needs_engineering=damage_level in (DamageLevel.CATASTROPHIC, DamageLevel.SEVERE),
            estimated_trapped=trapped,
            estimated_injured=injured,
            estimated_displaced=displaced,
            estimated_population=population,
        )

        lat = base_lat + rng.uniform(-0.1, 0.1)
        lon = base_lon + rng.uniform(-0.1, 0.1)

        zone = DisasterZone(
            name=name,
            zone_code=code,
            boundary=ZoneBoundary(
                center=GeoLocation(latitude=lat, longitude=lon),
                radius_km=rng.uniform(0.5, 3.0),
            ),
            address_description=desc,
            damage_level=damage_level,
            access_status=access_status,
            needs=needs,
            time_since_last_contact_minutes=rng.randint(0, 360),
            assessment_confidence=rng.uniform(0.3, 1.0),
        )

        zones.append(zone)

    return zones


def generate_resources(
    n: int = 30,
    agency_ids: list[str] | None = None,
    seed: int = 42,
) -> list[Resource]:
    """Generate emergency resources with capabilities.

    Distributes resources across agencies and resource types.

    Args:
        n: Number of resources to generate.
        agency_ids: Agency IDs to distribute across. Defaults to 3 demo agencies.
        seed: Random seed for reproducibility.

    Returns:
        List of Resource objects.
    """
    rng = random.Random(seed)

    if agency_ids is None:
        agency_ids = ["agency-fire", "agency-ems", "agency-ndrf"]

    # Resource type distribution (weighted)
    type_weights = [
        (ResourceType.SAR_TEAM_URBAN, 4),
        (ResourceType.AMBULANCE_ALS, 4),
        (ResourceType.FIRE_ENGINE, 3),
        (ResourceType.HELICOPTER_TRANSPORT, 2),
        (ResourceType.HELICOPTER_MEDICAL, 2),
        (ResourceType.SAR_TEAM_WATER, 2),
        (ResourceType.EVACUATION_BUS, 3),
        (ResourceType.SUPPLY_TRUCK, 3),
        (ResourceType.GENERATOR, 2),
        (ResourceType.K9_UNIT, 2),
        (ResourceType.ENGINEERING_UNIT, 2),
        (ResourceType.HAZMAT_TEAM, 1),
    ]

    pool: list[ResourceType] = []
    for rtype, weight in type_weights:
        pool.extend([rtype] * weight)

    base_lat, base_lon = 28.6, 77.2
    resources = []
    counters: dict[str, int] = {}

    for i in range(n):
        rtype = rng.choice(pool)
        template = _RESOURCE_TEMPLATES.get(rtype, {})

        # Generate unique name
        prefix = template.get("name_prefix", rtype.value)
        counters[prefix] = counters.get(prefix, 0) + 1
        name = f"{prefix}-{counters[prefix]}"
        callsign = f"{prefix[:4].upper()}-{counters[prefix]}"

        # Assign to an agency
        agency_id = rng.choice(agency_ids)

        # Random base location
        lat = base_lat + rng.uniform(-0.15, 0.15)
        lon = base_lon + rng.uniform(-0.15, 0.15)

        cap_data = template.get("capabilities", {})
        capabilities = ResourceCapabilities(**cap_data)

        resource = Resource(
            name=name,
            callsign=callsign,
            resource_type=rtype,
            owning_agency_id=agency_id,
            capabilities=capabilities,
            home_base=GeoLocation(latitude=lat, longitude=lon),
            status=ResourceStatus.AVAILABLE,
        )

        resources.append(resource)

    return resources


def generate_incidents(
    zones: list[DisasterZone],
    n: int = 5,
    seed: int = 42,
) -> list[Incident]:
    """Generate incident reports linked to zones.

    Args:
        zones: Available disaster zones.
        n: Number of incidents to generate.
        seed: Random seed for reproducibility.

    Returns:
        List of Incident objects.
    """
    rng = random.Random(seed)

    incident_types = [
        (IncidentType.BUILDING_COLLAPSE, "Building collapse reported"),
        (IncidentType.EARTHQUAKE, "Earthquake damage — structural assessment needed"),
        (IncidentType.FLOOD, "Flash flooding — water rescue required"),
        (IncidentType.MASS_CASUALTY, "Mass casualty event — triage required"),
        (IncidentType.LANDSLIDE, "Landslide — road blocked, persons trapped"),
        (IncidentType.INDUSTRIAL_ACCIDENT, "Industrial accident — hazmat risk"),
        (IncidentType.WILDFIRE, "Wildfire approaching populated area"),
    ]

    incidents = []

    for i in range(n):
        inc_type, desc_template = rng.choice(incident_types)
        affected_zones = rng.sample(zones, min(rng.randint(1, 3), len(zones)))

        incident = Incident(
            name=f"Incident {i + 1} — {inc_type.value.replace('_', ' ').title()}",
            incident_type=inc_type,
            severity=rng.choice(list(IncidentSeverity)),
            status=IncidentStatus.ACTIVE,
            description=f"{desc_template} in {affected_zones[0].name}.",
            location_description=affected_zones[0].address_description,
            zone_ids=[z.id for z in affected_zones],
            unified_command=len(affected_zones) > 1,
        )

        incidents.append(incident)

    return incidents
