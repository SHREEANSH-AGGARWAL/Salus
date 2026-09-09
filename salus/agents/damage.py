"""
Damage Assessment Agent.

Assesses the damage level and priority of a disaster zone using an LLM,
with deterministic fallback to the rule-based priority scorer.

Input:  DisasterZone (current state) + incident description string
Output: DamageAssessmentResult (priority P1-P5, confidence, reasoning, key factors)
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import structlog

from salus.dispatch.priority import score_zone_priority
from salus.models.dispatch import DamageAssessmentResult
from salus.models.zone import DisasterZone

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are a disaster damage assessment specialist with expertise in the INSARAG damage \
assessment methodology and ICS-300 priority scoring. Your task is to assess the \
priority level (P1-P5) of a disaster zone based on the data provided.

Priority levels:
- P1 (CRITICAL, value=1): Immediate life threat: active entrapment, mass casualties, \
  structural collapse with trapped persons. Dispatch within 5 minutes.
- P2 (HIGH, value=2): Significant casualties, serious structural damage, urgent medical \
  needs but not immediately life-threatening collapse.
- P3 (MODERATE, value=3): Infrastructure damage, displaced population, no immediate \
  life threat.
- P4 (LOW, value=4): Minor damage, mostly self-sufficient population.
- P5 (MINIMAL, value=5): Cosmetic damage only. No intervention needed.

You MUST respond with a JSON object only. No other text.
"""

_USER_PROMPT_TEMPLATE = """\
Zone: {zone_name} ({zone_code})
Incident description: {incident_description}
Damage level: {damage_level}
Access status: {access_status}
Estimated trapped: {estimated_trapped}
Estimated injured: {estimated_injured}
Estimated displaced: {estimated_displaced}
Time since last contact (minutes): {time_since_contact}
Resources already on scene: {resources_on_scene}

Respond with JSON:
{{
  "priority": <integer 1-5>,
  "confidence": <float 0.0-1.0>,
  "reasoning": "<one paragraph explaining the priority decision>",
  "key_factors": ["<factor1>", "<factor2>", "<factor3>"]
}}
"""


async def _llm_assess(
    llm: BaseChatModel,
    zone: DisasterZone,
    incident_description: str,
) -> DamageAssessmentResult:
    """Call the LLM to assess zone damage and priority."""
    from langchain_core.messages import HumanMessage, SystemMessage

    user_msg = _USER_PROMPT_TEMPLATE.format(
        zone_name=zone.name,
        zone_code=zone.zone_code,
        incident_description=incident_description,
        damage_level=zone.damage_level.value,
        access_status=zone.access_status.value,
        estimated_trapped=zone.needs.estimated_trapped,
        estimated_injured=zone.needs.estimated_injured,
        estimated_displaced=zone.needs.estimated_displaced,
        time_since_contact=zone.time_since_last_contact_minutes,
        resources_on_scene=zone.resources_on_scene,
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

    from salus.models.zone import ZonePriority

    return DamageAssessmentResult(
        zone_id=zone.id,
        priority=ZonePriority(int(data["priority"])),
        confidence=float(data.get("confidence", 0.7)),
        reasoning=str(data.get("reasoning", "")),
        key_factors=list(data.get("key_factors", [])),
        estimated_trapped=zone.needs.estimated_trapped,
        estimated_injured=zone.needs.estimated_injured,
        latency_ms=round(latency_ms, 1),
    )


def _rule_based_assess(
    zone: DisasterZone,
    incident_description: str,
    **kwargs: Any,
) -> DamageAssessmentResult:
    """Deterministic fallback: use rule-based priority scorer."""
    t0 = time.monotonic()
    priority, factors = score_zone_priority(zone)
    latency_ms = (time.monotonic() - t0) * 1000

    return DamageAssessmentResult(
        zone_id=zone.id,
        priority=priority,
        confidence=0.65,  # Rule-based is less confident than LLM synthesis
        reasoning=(
            f"Rule-based assessment (AI unavailable). Priority {priority.value} "
            f"based on: {', '.join(factors[:3])}."
        ),
        key_factors=factors,
        estimated_trapped=zone.needs.estimated_trapped,
        estimated_injured=zone.needs.estimated_injured,
        latency_ms=round(latency_ms, 1),
    )


async def assess_damage(
    llm: BaseChatModel,
    zone: DisasterZone,
    incident_description: str,
    timeout_seconds: float = 5.0,
) -> tuple[DamageAssessmentResult, bool]:
    """Assess zone damage and priority using LLM with rule-based fallback.

    Args:
        llm: LangChain chat model instance.
        zone: The disaster zone to assess.
        incident_description: Human-readable incident report.
        timeout_seconds: LLM timeout before fallback triggers.

    Returns:
        Tuple of (DamageAssessmentResult, used_fallback).
    """
    from salus.agents.circuit_breaker import with_fallback

    return await with_fallback(
        agent_fn=_llm_assess,
        fallback_fn=_rule_based_assess,
        timeout_seconds=timeout_seconds,
        agent_name="damage_assessment",
        llm=llm,
        zone=zone,
        incident_description=incident_description,
    )
