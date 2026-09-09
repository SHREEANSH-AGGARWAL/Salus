"""
Auto-generate domain schema documentation for RAG ingestion.

Reads the Pydantic models (ResourceCapabilities, DisasterZone, ZonePriority, etc.)
and produces human-readable markdown that the RAG index can embed. This ensures
agents have grounded, accurate knowledge of what each field and enum value means,
reducing hallucination risk.

The output is regenerated at startup so it always matches the current code.
"""

from __future__ import annotations

from salus.models.resource import (
    ResourceCapabilities,
    ResourceStatus,
    ResourceType,
)
from salus.models.zone import (
    AccessStatus,
)


def generate_resource_types_doc() -> str:
    """Generate markdown documentation for all resource types."""
    lines = [
        "# Salus Resource Types Reference",
        "",
        "This document describes the 17 resource types available in the disaster",
        "response system. Each resource type has specific capabilities and is used",
        "for different kinds of emergency response tasks.",
        "",
        "## Resource Type Definitions",
        "",
    ]
    descriptions = {
        ResourceType.SAR_TEAM_URBAN: "Urban Search and Rescue team specialised for collapsed building operations. Carries hydraulic spreaders, acoustic sensors, dogs.",
        ResourceType.SAR_TEAM_WATER: "Water/flood rescue team. Equipped with boats, throw bags, and swiftwater gear. Can operate in Class I-III water.",
        ResourceType.SAR_TEAM_MOUNTAIN: "Mountain/wilderness rescue team. Equipped for rope rescue, cliff rescue, and remote terrain operations.",
        ResourceType.HELICOPTER_TRANSPORT: "Medical transport helicopter. Used for hoist rescue, rooftop evacuation, and rapid patient transport.",
        ResourceType.HELICOPTER_MEDICAL: "Dedicated air ambulance/HEMS helicopter with in-flight medical capability. For time-critical patient transport.",
        ResourceType.HELICOPTER_HEAVY_LIFT: "Heavy-lift helicopter for cargo, supply drops, and large-scale evacuation. Not configured for medical hoist rescue.",
        ResourceType.AMBULANCE: "Ground BLS ambulance. Can transport 1-2 stretcher patients. Carries oxygen, AED, basic first aid.",
        ResourceType.AMBULANCE_ALS: "Advanced life support (ALS) ground ambulance. Paramedic-staffed with IV meds, RSI capability, defibrillator.",
        ResourceType.FIRE_ENGINE: "Standard fire suppression engine. Carries hoses, water/foam. Can also assist with vehicle extrication and light rescue.",
        ResourceType.HAZMAT_TEAM: "Hazardous materials team. Can perform decontamination, chemical identification, and Level A/B entry into hot zones.",
        ResourceType.EVACUATION_BUS: "Ground-based evacuation transport for displaced population. Capacity 40-50 persons. Not equipped for medical evacuation.",
        ResourceType.SUPPLY_TRUCK: "Logistics supply truck. Carries food, water, blankets, and emergency shelter materials. Not for personnel transport.",
        ResourceType.WATER_TANKER: "Water tanker for fire suppression or potable water supply to displaced populations.",
        ResourceType.GENERATOR: "Mobile generator unit for emergency power supply to shelters, field hospitals, or command posts.",
        ResourceType.FIELD_HOSPITAL: "Deployable field hospital unit. Sets up a surgical capability, ICU beds, and patient management in the field.",
        ResourceType.K9_UNIT: "Search dog (K9) and handler team for locating live victims in collapse debris or wilderness terrain.",
        ResourceType.DRONE_TEAM: "Unmanned aerial vehicle (UAV) unit for aerial reconnaissance, search imaging, and damage assessment. Range: 5-15 km.",
        ResourceType.ENGINEERING_UNIT: "Civil engineering unit for debris clearance, temporary bridge construction, road repair. Carries heavy machinery.",
    }

    for rt in ResourceType:
        desc = descriptions.get(rt, f"{rt.value.replace('_', ' ').title()} resource type.")
        lines.append(f"### {rt.value} ({rt.name})")
        lines.append(f"{desc}")
        lines.append("")

    return "\n".join(lines)


def generate_capabilities_doc() -> str:
    """Generate markdown documentation for ResourceCapabilities fields."""
    lines = [
        "# Resource Capabilities Reference",
        "",
        "Each resource in Salus has a `ResourceCapabilities` object with boolean flags and",
        "numeric fields describing what the resource can do. Use these fields when matching",
        "a resource to a zone's needs.",
        "",
        "## Capability Flags",
        "",
    ]

    for name, field in ResourceCapabilities.model_fields.items():
        desc = field.description or name.replace("_", " ").title()
        lines.append(f"- **`{name}`**: {desc}")

    lines += [
        "",
        "## Resource-to-Zone Needs Mapping",
        "",
        "| Zone Need | Required Capability |",
        "|---|---|",
        "| `needs_sar` | `can_perform_sar = True` |",
        "| `needs_medical` | `can_perform_medical = True` or `has_medical_personnel = True` |",
        "| `needs_evacuation` | `passenger_capacity > 0` |",
        "| `needs_water` | resource_type = SUPPLY_TRUCK |",
        "| `needs_food` | resource_type = SUPPLY_TRUCK |",
        "| `needs_shelter` | resource_type = SHELTER_UNIT |",
        "| `needs_hazmat` | `can_perform_hazmat = True` |",
        "| `needs_firefighting` | `can_perform_firefighting = True` |",
        "| `needs_engineering` | `can_clear_debris = True` |",
        "| `needs_communication` | resource_type = COMMUNICATION_UNIT |",
        "| `needs_power` | resource_type = SUPPLY_TRUCK or ENGINEERING_UNIT |",
        "",
        "## Access Constraints",
        "",
        "When a zone has restricted access, the resource must have the corresponding capability:",
        "",
        "| Zone Access Status | Required Capability |",
        "|---|---|",
        "| AIR_ONLY | `can_access_air = True` |",
        "| WATER_ONLY | `can_access_water = True` |",
        "| CUT_OFF | `can_access_air = True` (highest priority) |",
        "| RESTRICTED | `can_access_rough_terrain = True` OR `can_access_air = True` |",
        "| OPEN | Any resource |",
    ]

    return "\n".join(lines)


def generate_zone_priority_doc() -> str:
    """Generate markdown documentation for ZonePriority levels."""
    lines = [
        "# Zone Priority Reference — P1 through P5",
        "",
        "Disaster zones are classified P1–P5 based on damage severity. P1 is the most",
        "critical and requires immediate resource allocation. P5 requires no intervention.",
        "",
        "## Priority Level Definitions",
        "",
        "| Priority | Code | Meaning | Dispatch Urgency |",
        "|---|---|---|---|",
        "| **P1 — CRITICAL** | 1 | Immediate life threat: active entrapment, mass casualties, structural collapse with trapped persons. | Dispatch within 5 minutes. |",
        "| **P2 — HIGH** | 2 | Significant casualties, structural collapse, urgent medical needs. No imminent collapse expected but life risk is high. | Dispatch within 15 minutes. |",
        "| **P3 — MODERATE** | 3 | Infrastructure damage, displaced population, no immediate life threat. Urgent welfare needs. | Dispatch within 60 minutes. |",
        "| **P4 — LOW** | 4 | Minor damage, some injured but ambulatory. Population is mostly self-sufficient. | Dispatch within 4 hours. |",
        "| **P5 — MINIMAL** | 5 | Cosmetic damage, no injuries, no displacement. Information and monitoring only. | No immediate dispatch. |",
        "",
        "## Priority Scoring Factors",
        "",
        "The following factors drive zone priority:",
        "- **Estimated trapped persons**: ≥50 → adds max to casualty score",
        "- **Estimated injured persons**: ≥200 → significant weight",
        "- **Damage level**: CATASTROPHIC (>70% collapse) drives priority up",
        "- **Access status**: CUT_OFF or AIR_ONLY increases urgency",
        "- **Time since last contact**: >60 minutes without comms increases priority (no contact ≠ no need)",
        "- **Resources already on scene**: More resources → lower priority relative to unserved zones",
    ]

    return "\n".join(lines)


def generate_access_status_doc() -> str:
    """Generate markdown documentation for AccessStatus enum."""
    lines = [
        "# Zone Access Status Reference",
        "",
        "The `access_status` field of a DisasterZone describes how accessible the zone",
        "is for emergency response teams. This directly affects which resource types can",
        "reach the zone.",
        "",
    ]

    descriptions = {
        AccessStatus.OPEN: "All roads clear. Full ground access available. Any resource type can reach the zone.",
        AccessStatus.RESTRICTED: "Some routes are blocked by debris or damage. Alternative routes exist. Ground vehicles can reach the zone but may face delays. Off-road capable resources preferred.",
        AccessStatus.AIR_ONLY: "All ground routes are blocked. Helicopter access is the only option. Only resources with `can_access_air = True` can respond.",
        AccessStatus.WATER_ONLY: "Zone is flooded and surrounded by water. Boat access only. Only resources with `can_access_water = True` can respond.",
        AccessStatus.CUT_OFF: "No known access route exists. Ground routes destroyed. Air access uncertain. Requires engineering to establish access. Highest-priority resources should be dispatched.",
        AccessStatus.UNKNOWN: "Access has not yet been assessed. Assume worst-case (CUT_OFF) for planning purposes until reconnaissance confirms.",
    }

    for status in AccessStatus:
        desc = descriptions.get(status, status.value)
        lines.append(f"## {status.value.upper()}")
        lines.append(f"{desc}")
        lines.append("")

    return "\n".join(lines)


def generate_resource_status_doc() -> str:
    """Generate markdown documentation for ResourceStatus state machine."""
    lines = [
        "# Resource Status (State Machine) Reference",
        "",
        "Each resource has a `status` field that tracks its current deployment state.",
        "Status transitions are validated and committed to the Raft log. Only AVAILABLE",
        "resources can be dispatched.",
        "",
        "## Status Definitions",
        "",
    ]

    descriptions = {
        ResourceStatus.AVAILABLE: "Resource is at base/staging, ready for dispatch. This is the only status from which a resource can be dispatched.",
        ResourceStatus.DISPATCHED: "Resource has been ordered to a zone and is en route. Not yet on scene.",
        ResourceStatus.ON_SCENE: "Resource has arrived at the assigned zone and is actively working.",
        ResourceStatus.RETURNING: "Resource has completed its mission and is returning to base.",
        ResourceStatus.NEEDS_RESUPPLY: "Resource is on scene but requires fuel, medical supplies, or other resupply before continuing.",
        ResourceStatus.RESUPPLYING: "Resource is temporarily at a resupply point. Will return to AVAILABLE when complete.",
        ResourceStatus.MAINTENANCE: "Resource is offline for equipment failure or scheduled maintenance. Not deployable.",
    }

    for status in ResourceStatus:
        desc = descriptions.get(status, status.value)
        lines.append(f"- **`{status.value}`**: {desc}")

    lines += [
        "",
        "## Valid Transitions",
        "",
        "| From | To | Meaning |",
        "|---|---|---|",
        "| AVAILABLE | DISPATCHED | Resource ordered to zone (requires IC confirmation) |",
        "| AVAILABLE | MAINTENANCE | Resource taken offline |",
        "| DISPATCHED | ON_SCENE | Resource arrives at zone |",
        "| DISPATCHED | AVAILABLE | Dispatch cancelled |",
        "| ON_SCENE | RETURNING | Mission complete |",
        "| ON_SCENE | NEEDS_RESUPPLY | Resource needs supply |",
        "| NEEDS_RESUPPLY | RESUPPLYING | At resupply point |",
        "| NEEDS_RESUPPLY | RETURNING | Returns without resupply |",
        "| RESUPPLYING | AVAILABLE | Resupply complete |",
        "| RESUPPLYING | DISPATCHED | Re-dispatched from resupply |",
        "| RETURNING | AVAILABLE | Resource back at base |",
        "| MAINTENANCE | AVAILABLE | Maintenance complete |",
    ]

    return "\n".join(lines)


def generate_all_schema_docs() -> dict[str, str]:
    """Generate all schema documentation documents.

    Returns:
        dict mapping a logical name (used as ChromaDB source) to markdown content.
    """
    return {
        "schema:resource_types": generate_resource_types_doc(),
        "schema:capabilities": generate_capabilities_doc(),
        "schema:zone_priority": generate_zone_priority_doc(),
        "schema:access_status": generate_access_status_doc(),
        "schema:resource_status": generate_resource_status_doc(),
    }
