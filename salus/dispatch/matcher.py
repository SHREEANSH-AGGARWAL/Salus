"""
Resource-to-zone matching logic.

Rule-based matcher for Phase 1 — matches available resources to zone
needs based on capability overlap, proximity, and operational constraints.

The AI agents (Phase 3) will wrap this with LLM-powered reasoning,
but this rule-based matcher serves as:
  1. The baseline implementation
  2. The circuit-breaker fallback when LLM is down
  3. The deterministic core that the AI layer enhances
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import structlog

from salus.models.resource import Resource, ResourceStatus, ResourceType
from salus.models.zone import AccessStatus, DisasterZone

logger = structlog.get_logger()


@dataclass
class MatchResult:
    """Result of matching a resource to a zone."""

    resource_id: str
    resource_name: str
    resource_type: ResourceType
    score: float  # 0.0 - 1.0
    reasoning: str
    distance_km: float
    capability_matches: list[str]
    capability_gaps: list[str]


def match_resources_to_zone(
    zone: DisasterZone,
    resources: list[Resource],
    max_results: int = 5,
    include_uncertain: bool = False,
) -> list[MatchResult]:
    """Find and rank the best resources for a given zone.

    This is the rule-based matcher — no LLM involved. It serves as
    both the primary matcher for Phase 1 and the circuit-breaker
    fallback when the LLM is unavailable.

    Args:
        zone: The disaster zone needing resources.
        resources: All resources to consider.
        max_results: Maximum number of results to return.
        include_uncertain: If True, include UNCERTAIN resources
                          (partition-degraded mode, conservative matching).

    Returns:
        Ranked list of MatchResults, best first.
    """
    candidates: list[MatchResult] = []

    for resource in resources:
        # Filter: only available resources (or uncertain if flagged)
        if resource.status != ResourceStatus.AVAILABLE:
            if not (include_uncertain and resource.status == ResourceStatus.NEEDS_RESUPPLY):
                continue

        # Filter: check if resource can access this zone
        if not _can_access_zone(resource, zone):
            continue

        # Score the match
        score, matches, gaps, reasoning = _score_match(resource, zone)

        if score > 0.0:
            distance = _calculate_distance(resource, zone)
            candidates.append(MatchResult(
                resource_id=resource.id,
                resource_name=resource.name,
                resource_type=resource.resource_type,
                score=score,
                reasoning=reasoning,
                distance_km=distance,
                capability_matches=matches,
                capability_gaps=gaps,
            ))

    # Sort by score (descending), then distance (ascending) as tiebreaker
    candidates.sort(key=lambda m: (-m.score, m.distance_km))

    return candidates[:max_results]


def _can_access_zone(resource: Resource, zone: DisasterZone) -> bool:
    """Check if a resource can physically reach this zone.

    Args:
        resource: The candidate resource.
        zone: The target zone.

    Returns:
        True if the resource can reach the zone.
    """
    if zone.access_status == AccessStatus.CUT_OFF:
        return False

    if zone.access_status == AccessStatus.AIR_ONLY:
        return resource.capabilities.can_access_air

    if zone.access_status == AccessStatus.WATER_ONLY:
        return resource.capabilities.can_access_water

    return True


def _score_match(
    resource: Resource, zone: DisasterZone
) -> tuple[float, list[str], list[str], str]:
    """Score how well a resource matches a zone's needs.

    Returns:
        (score, capability_matches, capability_gaps, reasoning)
    """
    matches: list[str] = []
    gaps: list[str] = []
    needs = zone.needs
    cap = resource.capabilities

    # Check each need against capabilities
    need_checks = [
        (needs.needs_sar, cap.can_perform_sar, "search_and_rescue"),
        (needs.needs_medical, cap.can_perform_medical or cap.has_medical_personnel, "medical"),
        (needs.needs_evacuation, cap.passenger_capacity > 0, "evacuation"),
        (needs.needs_hazmat, cap.can_perform_hazmat, "hazmat"),
        (needs.needs_firefighting, cap.can_perform_firefighting, "firefighting"),
        (needs.needs_engineering, cap.can_clear_debris, "engineering"),
    ]

    total_needs = 0
    matched_needs = 0

    for needed, has_capability, name in need_checks:
        if needed:
            total_needs += 1
            if has_capability:
                matched_needs += 1
                matches.append(name)
            else:
                gaps.append(name)

    if total_needs == 0:
        # Zone has no specific needs flagged — base score on resource type
        score = 0.3
        reasoning = "No specific needs flagged; resource available as general support."
    else:
        score = matched_needs / total_needs
        reasoning = (
            f"Matches {matched_needs}/{total_needs} zone needs: "
            f"{', '.join(matches) if matches else 'none'}."
        )

    # Bonus: resource has listening devices and zone has trapped persons
    if needs.estimated_trapped > 0 and cap.has_listening_devices:
        score = min(1.0, score + 0.15)
        matches.append("life_detection")
        reasoning += " +bonus: life-detection equipment for trapped persons."

    # Bonus: resource has thermal imaging
    if needs.estimated_trapped > 0 and cap.has_thermal_imaging:
        score = min(1.0, score + 0.1)
        matches.append("thermal_imaging")

    # Penalty: resource is fatigued
    if resource.is_fatigued:
        score *= 0.5
        reasoning += " -penalty: crew fatigue exceeds shift limit."

    # Penalty: low fuel
    if cap.fuel_hours_remaining < 2.0 and cap.fuel_hours_remaining > 0:
        score *= 0.7
        reasoning += " -penalty: low fuel remaining."

    return score, matches, gaps, reasoning


def _calculate_distance(resource: Resource, zone: DisasterZone) -> float:
    """Calculate approximate distance between resource and zone.

    Uses Haversine formula for lat/lon distance.

    Returns:
        Distance in kilometers.
    """
    r_loc = resource.home_base if resource.current_location is None else resource.current_location
    z_loc = zone.boundary.center

    # Haversine
    R = 6371.0  # Earth's radius in km
    lat1, lon1 = math.radians(r_loc.latitude), math.radians(r_loc.longitude)
    lat2, lon2 = math.radians(z_loc.latitude), math.radians(z_loc.longitude)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
