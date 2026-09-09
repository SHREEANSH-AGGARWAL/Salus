"""
Routing Agent.

Calculates the optimal route and ETA for a resource to reach a disaster zone,
using the existing RoutePlanner as the baseline and LLM to enrich with contextual
obstacle reasoning.

Input:  Resource + DisasterZone
Output: RouteResult (travel time, distance, route description, obstacles)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from salus.models.dispatch import RouteResult
from salus.models.resource import Resource
from salus.models.zone import DisasterZone
from salus.routing.pathfinder import RoutePlanner

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = structlog.get_logger()

_planner = RoutePlanner()

_SYSTEM_PROMPT = """\
You are a field logistics coordinator for disaster response. Given a base route \
calculation, enrich it with contextual reasoning about obstacles, alternative \
approaches, and operational notes for the Incident Commander.

Keep your additions concise and actionable. The base calculation is correct — \
you are adding human-readable context, not recalculating.
"""

_USER_PROMPT_TEMPLATE = """\
Resource: {resource_name} ({resource_type})
Destination Zone: {zone_name} | Access: {access_status} | Damage: {damage_level}

Base Route (calculated):
- Distance: {distance_km:.1f} km
- Estimated travel time: {travel_time:.0f} minutes
- Requires air: {requires_air}
- Route: {route_description}
- Obstacles: {obstacles}

Enrich the route description with:
1. Any operational warnings based on the zone's access/damage status.
2. Whether the route choice is appropriate for this resource type.
3. Any coordination needed (e.g., air traffic control if helicopter).

Respond with a single improved route_description paragraph (max 70 words).
"""


async def _llm_route(
    llm: BaseChatModel,
    resource: Resource,
    zone: DisasterZone,
) -> RouteResult:
    """Get base route then enrich with LLM contextual reasoning."""
    from langchain_core.messages import HumanMessage, SystemMessage

    # Always get the deterministic base result first
    t0 = time.monotonic()
    base = _planner.plan_route(resource, zone)
    base_latency_ms = (time.monotonic() - t0) * 1000

    user_msg = _USER_PROMPT_TEMPLATE.format(
        resource_name=resource.name,
        resource_type=resource.resource_type.value,
        zone_name=zone.name,
        access_status=zone.access_status.value,
        damage_level=zone.damage_level.value,
        distance_km=base.distance_km,
        travel_time=base.estimated_travel_time_minutes,
        requires_air=base.requires_air,
        route_description=base.route_description,
        obstacles=", ".join(base.obstacles) if base.obstacles else "None identified",
    )

    t1 = time.monotonic()
    response = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
    )
    llm_latency_ms = (time.monotonic() - t1) * 1000

    # Use LLM-enriched route description, keep all base numerical data
    enriched_description = str(response.content).strip()

    return RouteResult(
        resource_id=resource.id,
        zone_id=zone.id,
        route_description=enriched_description,
        estimated_travel_time_minutes=base.estimated_travel_time_minutes,
        distance_km=base.distance_km,
        obstacles=base.obstacles,
        requires_air=base.requires_air,
        latency_ms=round(base_latency_ms + llm_latency_ms, 1),
    )


def _rule_based_route(
    resource: Resource,
    zone: DisasterZone,
    **kwargs: Any,
) -> RouteResult:
    """Deterministic fallback: use RoutePlanner directly."""
    return _planner.plan_route(resource, zone)


async def plan_route(
    llm: BaseChatModel,
    resource: Resource,
    zone: DisasterZone,
    timeout_seconds: float = 5.0,
) -> tuple[RouteResult, bool]:
    """Plan the route from resource to zone using LLM-enriched routing.

    The base route calculation (RoutePlanner) always runs. The LLM adds
    contextual enrichment on top. If LLM times out, returns the base result.

    Args:
        llm: LangChain chat model.
        resource: The resource being dispatched.
        zone: The destination disaster zone.
        timeout_seconds: LLM timeout before fallback.

    Returns:
        Tuple of (RouteResult, used_fallback).
    """
    from salus.agents.circuit_breaker import with_fallback

    return await with_fallback(
        agent_fn=_llm_route,
        fallback_fn=_rule_based_route,
        timeout_seconds=timeout_seconds,
        agent_name="routing",
        llm=llm,
        resource=resource,
        zone=zone,
    )
