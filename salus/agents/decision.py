"""
Decision Synthesis Agent.

Final agent in the pipeline. Receives the outputs of all 4 prior agents and
synthesises a coherent, human-readable dispatch recommendation with a confidence
score for the Incident Commander gate.

Input:  DamageAssessmentResult + ResourceMatchResult + RouteResult + protocol_str
Output: (decision_summary: str, confidence: float)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog

from salus.models.dispatch import DamageAssessmentResult, ResourceMatchResult, RouteResult

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are the Incident Commander decision support system for a disaster response \
operation. You receive assessments from 4 specialist agents and must synthesise \
them into a clear, concise dispatch recommendation for the human Incident Commander \
to confirm or override.

Your recommendation must:
1. State clearly which resource to dispatch and to which zone.
2. Give a confidence score (0.0–1.0) reflecting overall certainty.
3. Briefly explain the key reasons (3–4 bullet points max).
4. Flag any significant concerns (capability gaps, long ETA, fallback used).

The Incident Commander is experienced — be direct, not verbose.
Do NOT use filler phrases. Max 200 words.
"""

_USER_PROMPT_TEMPLATE = """\
DISPATCH DECISION REQUEST

Zone: {zone_id}
Recommended Resource: {resource_name} (ID: {resource_id})

Damage Assessment:
- Priority: P{priority} | Confidence: {damage_confidence:.0%}
- Key factors: {key_factors}
- Reasoning: {damage_reasoning}

Resource Match:
- Match score: {match_score:.0%}
- Reasoning: {match_reasoning}
- Capability gaps: {capability_gaps}

Routing:
- Travel time: {travel_time:.0f} minutes | Distance: {distance_km:.1f} km
- Requires air: {requires_air}
- Route: {route_description}

Protocol Recommendation:
{protocol}

Pipeline quality flags:
- Used AI fallback (any agent): {any_fallback}

Provide your dispatch recommendation:
"""

_FALLBACK_TEMPLATE = """\
DISPATCH RECOMMENDATION (Rule-Based):
Dispatch {resource_name} to Zone {zone_id}.

Priority: P{priority} | Travel time: {travel_time:.0f} min | Match score: {match_score:.0%}

Reasons:
• Highest capability match for zone needs.
• {route_description}
• Protocol: Standard ICS response for reported incident type.

Note: AI synthesis unavailable — this recommendation is rule-based. \
Confidence is reduced ({confidence:.0%}). IC review strongly recommended."""


async def _llm_decide(
    llm: BaseChatModel,
    damage: DamageAssessmentResult,
    match: ResourceMatchResult,
    route: RouteResult,
    protocol: str,
    any_fallback: bool,
    **kwargs: Any,
) -> tuple[str, float]:
    """Call LLM to synthesise a final decision."""
    from langchain_core.messages import HumanMessage, SystemMessage

    user_msg = _USER_PROMPT_TEMPLATE.format(
        zone_id=damage.zone_id,
        resource_name=match.recommended_resource_name,
        resource_id=match.recommended_resource_id,
        priority=damage.priority.value,
        damage_confidence=damage.confidence,
        key_factors=", ".join(damage.key_factors[:3]),
        damage_reasoning=damage.reasoning[:300],
        match_score=match.match_score,
        match_reasoning=match.reasoning[:200],
        capability_gaps=", ".join(match.capability_gaps) if match.capability_gaps else "None",
        travel_time=route.estimated_travel_time_minutes,
        distance_km=route.distance_km,
        requires_air=route.requires_air,
        route_description=route.route_description[:200],
        protocol=protocol[:500],
        any_fallback=any_fallback,
    )

    t0 = time.monotonic()
    response = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
    )
    latency_ms = (time.monotonic() - t0) * 1000
    logger.debug("decision_agent_done", latency_ms=round(latency_ms, 1))

    content = str(response.content).strip()

    # Calculate confidence: average of sub-agent confidences, reduced if any fallback
    confidence = (damage.confidence + match.match_score) / 2.0
    if any_fallback:
        confidence *= 0.85  # Discount for fallback usage

    return content, round(min(confidence, 0.99), 3)


def _rule_based_decide(
    damage: DamageAssessmentResult,
    match: ResourceMatchResult,
    route: RouteResult,
    protocol: str,
    any_fallback: bool,
    **kwargs: Any,
) -> tuple[str, float]:
    """Deterministic fallback decision synthesis."""
    confidence = (damage.confidence * 0.5 + match.match_score * 0.5)
    if any_fallback:
        confidence *= 0.75  # Heavier discount — all agents used fallback

    summary = _FALLBACK_TEMPLATE.format(
        resource_name=match.recommended_resource_name,
        zone_id=damage.zone_id,
        priority=damage.priority.value,
        travel_time=route.estimated_travel_time_minutes,
        match_score=match.match_score,
        route_description=route.route_description,
        confidence=confidence,
    )

    return summary, round(min(confidence, 0.99), 3)


async def synthesise_decision(
    llm: BaseChatModel,
    damage: DamageAssessmentResult,
    match: ResourceMatchResult,
    route: RouteResult,
    protocol: str,
    any_fallback: bool,
    timeout_seconds: float = 5.0,
) -> tuple[tuple[str, float], bool]:
    """Synthesise a final dispatch recommendation from all agent outputs.

    Args:
        llm: LangChain chat model.
        damage: Output from the Damage Assessment Agent.
        match: Output from the Resource Matching Agent.
        route: Output from the Routing Agent.
        protocol: Output from the Protocol Lookup Agent.
        any_fallback: True if any upstream agent used its fallback.
        timeout_seconds: LLM timeout.

    Returns:
        Tuple of ((decision_summary, confidence), used_fallback).
    """
    from salus.agents.circuit_breaker import with_fallback

    return await with_fallback(
        agent_fn=_llm_decide,
        fallback_fn=_rule_based_decide,
        timeout_seconds=timeout_seconds,
        agent_name="decision_synthesis",
        llm=llm,
        damage=damage,
        match=match,
        route=route,
        protocol=protocol,
        any_fallback=any_fallback,
    )
