"""
Resource Matching Agent.

Selects the best available resource for a disaster zone using an LLM,
with deterministic fallback to the rule-based matcher.

Input:  DisasterZone + list of available Resources
Output: ResourceMatchResult (recommended resource, match score, reasoning, alternatives)
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import structlog

from salus.dispatch.matcher import match_resources_to_zone
from salus.models.dispatch import ResourceMatchResult
from salus.models.resource import Resource
from salus.models.zone import DisasterZone

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are a disaster response resource allocation specialist. Your task is to select the \
BEST single resource to dispatch to a disaster zone from a list of available resources.

Consider:
1. Capability match: Does the resource's capabilities match the zone's needs?
2. Access compatibility: Can the resource reach the zone given its access status?
3. Proximity: Is the resource close to the zone? (lower travel time is better)
4. Current load: Prefer rested resources (lower hours_deployed).

You MUST respond with a JSON object only. No other text.
"""

_USER_PROMPT_TEMPLATE = """\
Disaster Zone:
- Name: {zone_name} ({zone_code})
- Priority: P{priority}
- Access: {access_status}
- Needs: {needs_list}
- Estimated trapped: {estimated_trapped}, injured: {estimated_injured}

Available Resources:
{resources_json}

Select the BEST resource to dispatch. Respond with JSON:
{{
  "recommended_resource_id": "<id>",
  "recommended_resource_name": "<name>",
  "match_score": <float 0.0-1.0>,
  "reasoning": "<explanation of why this resource is the best choice>",
  "alternative_resource_ids": ["<id2>", "<id3>"],
  "capability_gaps": ["<gap1>", "<gap2>"]
}}
"""


def _format_needs(zone: DisasterZone) -> str:
    needs = zone.needs
    active = []
    if needs.needs_sar:
        active.append("SAR")
    if needs.needs_medical:
        active.append("Medical")
    if needs.needs_evacuation:
        active.append("Evacuation")
    if needs.needs_hazmat:
        active.append("HAZMAT")
    if needs.needs_firefighting:
        active.append("Firefighting")
    if needs.needs_engineering:
        active.append("Engineering/Debris clearing")
    if needs.needs_water:
        active.append("Water supply")
    if needs.needs_food:
        active.append("Food supply")
    if needs.needs_shelter:
        active.append("Shelter")
    if needs.needs_communication:
        active.append("Communications")
    return ", ".join(active) if active else "General support"


def _format_resources(resources: list[Resource]) -> str:
    items = []
    for r in resources[:10]:  # Cap at 10 to avoid token explosion
        caps = r.capabilities
        flags = []
        if caps.can_perform_sar:
            flags.append("SAR")
        if caps.can_perform_medical:
            flags.append("Medical")
        if caps.can_access_air:
            flags.append("Air-capable")
        if caps.can_access_water:
            flags.append("Water-capable")
        if caps.can_perform_hazmat:
            flags.append("HAZMAT")
        if caps.can_clear_debris:
            flags.append("Debris clearing")
        if caps.can_perform_firefighting:
            flags.append("Firefighting")
        items.append(
            {
                "id": r.id,
                "name": r.name,
                "type": r.resource_type.value,
                "capabilities": flags,
                "max_range_km": caps.max_range_km,
                "hours_deployed": r.hours_deployed,
            }
        )
    return json.dumps(items, indent=2)


async def _llm_match(
    llm: BaseChatModel,
    zone: DisasterZone,
    resources: list[Resource],
) -> ResourceMatchResult:
    """Call the LLM to select the best resource."""
    from langchain_core.messages import HumanMessage, SystemMessage

    user_msg = _USER_PROMPT_TEMPLATE.format(
        zone_name=zone.name,
        zone_code=zone.zone_code,
        priority=zone.priority.value,
        access_status=zone.access_status.value,
        needs_list=_format_needs(zone),
        estimated_trapped=zone.needs.estimated_trapped,
        estimated_injured=zone.needs.estimated_injured,
        resources_json=_format_resources(resources),
    )

    t0 = time.monotonic()
    response = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
    )
    latency_ms = (time.monotonic() - t0) * 1000

    content = str(response.content)
    # Strip markdown code blocks if LLM wraps output
    if "```" in content:
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]

    data = json.loads(content.strip())

    return ResourceMatchResult(
        recommended_resource_id=str(data["recommended_resource_id"]),
        recommended_resource_name=str(data.get("recommended_resource_name", "")),
        match_score=float(data.get("match_score", 0.7)),
        reasoning=str(data.get("reasoning", "")),
        alternative_resource_ids=list(data.get("alternative_resource_ids", [])),
        capability_gaps=list(data.get("capability_gaps", [])),
        latency_ms=round(latency_ms, 1),
    )


def _rule_based_match(
    zone: DisasterZone,
    resources: list[Resource],
    **kwargs: Any,
) -> ResourceMatchResult:
    """Deterministic fallback: use rule-based matcher."""
    t0 = time.monotonic()
    matches = match_resources_to_zone(zone, resources)
    latency_ms = (time.monotonic() - t0) * 1000

    if not matches:
        # No match found — return a placeholder with zero score
        return ResourceMatchResult(
            recommended_resource_id="",
            recommended_resource_name="No suitable resource available",
            match_score=0.0,
            reasoning="No available resources match zone requirements.",
            alternative_resource_ids=[],
            capability_gaps=[_format_needs(zone)],
            latency_ms=round(latency_ms, 1),
        )

    best = matches[0]
    alternatives = [m.resource_id for m in matches[1:4]]

    return ResourceMatchResult(
        recommended_resource_id=best.resource_id,
        recommended_resource_name=best.resource_name,
        match_score=round(best.score, 3),
        reasoning=(
            f"Rule-based match (AI unavailable). Score {best.score:.2f} based on "
            f"capability overlap and proximity."
        ),
        alternative_resource_ids=alternatives,
        capability_gaps=best.capability_gaps,
        latency_ms=round(latency_ms, 1),
    )


async def match_resource(
    llm: BaseChatModel,
    zone: DisasterZone,
    resources: list[Resource],
    timeout_seconds: float = 5.0,
) -> tuple[ResourceMatchResult, bool]:
    """Select the best resource for a zone using LLM with rule-based fallback.

    Args:
        llm: LangChain chat model.
        zone: The disaster zone to dispatch to.
        resources: List of available resources to choose from.
        timeout_seconds: LLM timeout before fallback triggers.

    Returns:
        Tuple of (ResourceMatchResult, used_fallback).
    """
    from salus.agents.circuit_breaker import with_fallback

    if not resources:
        logger.warning("no_available_resources", zone_id=zone.id)
        return ResourceMatchResult(
            recommended_resource_id="",
            recommended_resource_name="No resources available",
            match_score=0.0,
            reasoning="No available resources in the system.",
            alternative_resource_ids=[],
            capability_gaps=[],
        ), False

    return await with_fallback(
        agent_fn=_llm_match,
        fallback_fn=_rule_based_match,
        timeout_seconds=timeout_seconds,
        agent_name="resource_matching",
        llm=llm,
        zone=zone,
        resources=resources,
    )
