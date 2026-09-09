"""
Protocol Lookup Agent.

Retrieves relevant ICS/INSARAG/WHO emergency protocols via RAG and synthesises
a concise procedure recommendation for the Incident Commander.

Input:  incident_description + DisasterZone (for context)
Output: str — human-readable protocol recommendation with cited procedures
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from salus.models.zone import DisasterZone

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from salus.rag.index import KnowledgeIndex

logger = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are an experienced Incident Commander advisor with deep knowledge of ICS \
(Incident Command System), INSARAG USAR guidelines, START/SALT triage protocols, \
HAZMAT ERG procedures, and FEMA disaster response standards.

Based on the retrieved protocol excerpts provided, give a concise, actionable \
procedure recommendation for the Incident Commander. Focus on:
1. The most critical immediate actions (first 30 minutes).
2. Resource requirements (what types of teams are needed).
3. Safety considerations (what hazards to watch for).
4. Medical priorities (triage and treatment).

Be specific. Reference protocol names when applicable (e.g., "Per INSARAG ASR 4 criteria",
"Apply START triage"). Keep it under 300 words.
"""

_USER_PROMPT_TEMPLATE = """\
Incident: {incident_description}
Zone: {zone_name} | Priority: P{priority} | Access: {access_status}
Damage: {damage_level} | Trapped: {trapped} | Injured: {injured}

Retrieved Protocol Excerpts:
---
{retrieved_chunks}
---

Provide a concise procedure recommendation for the Incident Commander:
"""

_STATIC_FALLBACKS: dict[str, str] = {
    "collapse": (
        "STRUCTURAL COLLAPSE PROTOCOL (Fallback): "
        "1. Establish 360° perimeter at 1.5× building height. "
        "2. Apply INSARAG site marking to all searched sectors. "
        "3. Classify collapse type (lean-to, pancake, void) to prioritise search. "
        "4. Conduct vocal sweep before deploying search dogs. "
        "5. Monitor for aftershock — 3-whistle evacuation signal. "
        "6. All victims trapped >4hrs: establish IV access before extraction (crush syndrome). "
        "Required: SAR Urban team with acoustic devices + medical team at CCP."
    ),
    "flood": (
        "FLOOD RESCUE PROTOCOL (Fallback): "
        "1. Classify water speed. Class I-II: boat operations. Class III+: defensive/helicopter only. "
        "2. Never approach low-head dams from downstream. "
        "3. All victims submerged: transport to hospital for 24hr observation (secondary drowning risk). "
        "4. Hypothermia management: remove wet clothing, warm IV fluids. "
        "Required: Rescue boat team + helicopter if Class III+ or rooftop rescue needed."
    ),
    "hazmat": (
        "HAZMAT PROTOCOL (Fallback): "
        "1. Upwind, uphill, upstream staging. "
        "2. Initial isolation: 300 m radius minimum. Protective Action Distance: 800 m downwind. "
        "3. Call CHEMTREC: 1-800-424-9300 for chemical identification support. "
        "4. Establish Hot/Warm/Cold zones. Level A entry team + decon corridor. "
        "5. Mass decon: disrobe + 3-minute water flush removes 90% of surface contamination. "
        "Required: HAZMAT team Level A + medical team with antidotes."
    ),
    "earthquake": (
        "EARTHQUAKE PROTOCOL (Fallback): "
        "1. 72-hour window: prioritise entrapment rescue above all else. "
        "2. Aftershock plan: 3-whistle evacuation signal; re-assess after M4.0+ shake. "
        "3. Check for secondary hazards: gas leaks, downed power lines, dam failure risk. "
        "4. Coastal zone: if M7.0+ offshore, evacuate to 30m+ elevation (tsunami risk). "
        "5. Crush syndrome in all victims trapped >4hrs: IV before extraction. "
        "Required: USAR urban team + medical ALS team + engineering unit."
    ),
    "default": (
        "GENERAL EMERGENCY PROTOCOL (Fallback): "
        "1. Establish Incident Command and Safety Officer. "
        "2. Set up CCP upwind, uphill, upstream of the incident. "
        "3. Apply START triage: walking = GREEN, assess breathing/perfusion/mental status. "
        "4. Communicate resource needs to EOC. "
        "5. Maintain communications log (ICS-214). "
        "Required: Medical team + safety officer at minimum."
    ),
}


def _classify_incident(description: str, zone: DisasterZone) -> str:
    """Classify the incident type for static fallback selection."""
    text = description.lower() + " " + zone.name.lower()
    if any(w in text for w in ["collapse", "building", "structure", "crush", "entrap"]):
        return "collapse"
    if any(w in text for w in ["flood", "water", "submerge", "inundat", "swiftwater"]):
        return "flood"
    if any(w in text for w in ["hazmat", "chemical", "gas", "toxic", "spill", "hazardous"]):
        return "hazmat"
    if any(w in text for w in ["earthquake", "quake", "seismic", "tremor", "aftershock"]):
        return "earthquake"
    return "default"


async def _llm_protocol(
    llm: BaseChatModel,
    knowledge_index: KnowledgeIndex,
    incident_description: str,
    zone: DisasterZone,
) -> str:
    """Query RAG and synthesise a protocol recommendation."""
    from langchain_core.messages import HumanMessage, SystemMessage

    # Build query from incident + zone context
    query = f"{incident_description} {zone.damage_level.value} {zone.access_status.value}"
    chunks = knowledge_index.query(query, top_k=5)

    if not chunks:
        raise RuntimeError("No chunks retrieved from knowledge index")

    retrieved_text = "\n\n---\n\n".join(
        f"[Source: {c.source} | Score: {c.score:.2f}]\n{c.text}" for c in chunks
    )

    user_msg = _USER_PROMPT_TEMPLATE.format(
        incident_description=incident_description,
        zone_name=zone.name,
        priority=zone.priority.value,
        access_status=zone.access_status.value,
        damage_level=zone.damage_level.value,
        trapped=zone.needs.estimated_trapped,
        injured=zone.needs.estimated_injured,
        retrieved_chunks=retrieved_text,
    )

    t0 = time.monotonic()
    response = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_msg)]
    )
    latency_ms = (time.monotonic() - t0) * 1000

    logger.debug("protocol_agent_done", latency_ms=round(latency_ms, 1), chunks_used=len(chunks))
    return str(response.content).strip()


def _static_fallback(
    knowledge_index: KnowledgeIndex,
    incident_description: str,
    zone: DisasterZone,
) -> str:
    """Deterministic fallback: return a static protocol based on incident type."""
    incident_type = _classify_incident(incident_description, zone)
    return _STATIC_FALLBACKS[incident_type]


async def lookup_protocol(
    llm: BaseChatModel,
    knowledge_index: KnowledgeIndex,
    incident_description: str,
    zone: DisasterZone,
    timeout_seconds: float = 8.0,
) -> tuple[str, bool]:
    """Retrieve and synthesise an ICS protocol recommendation.

    Args:
        llm: LangChain chat model.
        knowledge_index: The RAG knowledge index.
        incident_description: Human-readable incident description.
        zone: The disaster zone for context.
        timeout_seconds: LLM timeout (slightly longer — RAG adds latency).

    Returns:
        Tuple of (protocol_recommendation: str, used_fallback: bool).
    """
    from salus.agents.circuit_breaker import with_fallback

    return await with_fallback(
        agent_fn=_llm_protocol,
        fallback_fn=_static_fallback,
        timeout_seconds=timeout_seconds,
        agent_name="protocol_lookup",
        llm=llm,
        knowledge_index=knowledge_index,
        incident_description=incident_description,
        zone=zone,
    )
