"""
5-Agent Dispatch Pipeline Orchestrator.

Chains Damage Assessment → Resource Matching → Protocol Lookup → Routing →
Decision Synthesis into a single async call, returning a fully populated
DispatchOrder ready for the Incident Commander confirmation gate.

Usage (in FastAPI route):
    pipeline = DispatchPipeline(llm_config, rag_config, knowledge_index, state_machine)
    dispatch_order = await pipeline.run(incident_id, zone_id, incident_description)
    # dispatch_order.status == AWAITING_CONFIRMATION → hand to CommanderGate
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from salus.agents.damage import assess_damage
from salus.agents.decision import synthesise_decision
from salus.agents.llm import create_llm
from salus.agents.matcher import match_resource
from salus.agents.protocol import lookup_protocol
from salus.agents.router import plan_route
from salus.models.dispatch import DispatchOrder, DispatchStatus

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from salus.config import LLMConfig, RAGConfig
    from salus.dispatch.state_machine import DispatchStateMachine
    from salus.rag.index import KnowledgeIndex

logger = structlog.get_logger()


class DispatchPipeline:
    """5-agent AI pipeline for disaster response dispatch recommendation.

    Agents run in sequence (each depends on prior output). Each agent is
    wrapped in a circuit-breaker — the pipeline always completes even if
    every agent times out (using deterministic fallbacks).

    The pipeline does NOT commit to the Raft log. It produces a DispatchOrder
    with status=AWAITING_CONFIRMATION that the Incident Commander must confirm
    via the CommanderGate before it is committed.
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        rag_config: RAGConfig,
        knowledge_index: KnowledgeIndex,
        state_machine: DispatchStateMachine,
        icp_id: str = "",
    ) -> None:
        self.llm_config = llm_config
        self.rag_config = rag_config
        self.knowledge_index = knowledge_index
        self.state_machine = state_machine
        self.icp_id = icp_id
        self._llm: BaseChatModel | None = None

    def _get_llm(self) -> BaseChatModel:
        """Lazily create and cache the LLM instance."""
        if self._llm is None:
            self._llm = create_llm(self.llm_config)
        return self._llm

    async def run(
        self,
        incident_id: str,
        zone_id: str,
        incident_description: str,
    ) -> DispatchOrder:
        """Execute the full 5-agent pipeline for an incident.

        Args:
            incident_id: The incident triggering this dispatch.
            zone_id: The target zone ID.
            incident_description: Human-readable description of the incident.

        Returns:
            A DispatchOrder with all agent outputs populated and status set to
            AWAITING_CONFIRMATION (or FALLBACK if all agents used fallback).
        """
        t_pipeline_start = time.monotonic()
        order = DispatchOrder(
            incident_id=incident_id,
            zone_id=zone_id,
            requesting_icp_id=self.icp_id,
            status=DispatchStatus.ASSESSING,
        )
        any_fallback = False

        log = logger.bind(
            dispatch_id=order.id,
            incident_id=incident_id,
            zone_id=zone_id,
        )
        log.info("pipeline_started")

        try:
            # ── Agent 1: Damage Assessment ──────────────────────────────────
            zone = self.state_machine.get_zone(zone_id)
            if zone is None:
                raise ValueError(f"Zone not found: {zone_id}")

            order.status = DispatchStatus.ASSESSING
            damage_result, fb1 = await assess_damage(
                llm=self._get_llm(),
                zone=zone,
                incident_description=incident_description,
                timeout_seconds=self.llm_config.timeout_seconds,
            )
            any_fallback = any_fallback or fb1
            order.damage_assessment = damage_result
            log.info("damage_assessment_done", priority=damage_result.priority.value, fallback=fb1)

            # ── Agent 2: Resource Matching ───────────────────────────────────
            order.status = DispatchStatus.MATCHING
            available = self.state_machine.get_available_resources()
            match_result, fb2 = await match_resource(
                llm=self._get_llm(),
                zone=zone,
                resources=available,
                timeout_seconds=self.llm_config.timeout_seconds,
            )
            any_fallback = any_fallback or fb2
            order.resource_match = match_result
            log.info(
                "resource_match_done",
                resource_id=match_result.recommended_resource_id,
                score=match_result.match_score,
                fallback=fb2,
            )

            if not match_result.recommended_resource_id:
                order.status = DispatchStatus.FAILED
                order.error = "No suitable resource available for dispatch."
                return order

            # ── Agent 3: Protocol Lookup ──────────────────────────────────
            order.status = DispatchStatus.ASSESSING  # Reuse state — no PROTOCOL_LOOKUP status
            protocol_text, fb3 = await lookup_protocol(
                llm=self._get_llm(),
                knowledge_index=self.knowledge_index,
                incident_description=incident_description,
                zone=zone,
                timeout_seconds=self.llm_config.timeout_seconds + 3.0,  # Extra for RAG latency
            )
            any_fallback = any_fallback or fb3
            order.protocol_recommendation = protocol_text
            log.info("protocol_lookup_done", fallback=fb3, length=len(protocol_text))

            # ── Agent 4: Route Planning ───────────────────────────────────
            order.status = DispatchStatus.ROUTING
            resource = self.state_machine.get_resource(match_result.recommended_resource_id)
            if resource is None:
                raise ValueError(
                    f"Resource not found after matching: {match_result.recommended_resource_id}"
                )

            route_result, fb4 = await plan_route(
                llm=self._get_llm(),
                resource=resource,
                zone=zone,
                timeout_seconds=self.llm_config.timeout_seconds,
            )
            any_fallback = any_fallback or fb4
            order.route = route_result
            log.info(
                "routing_done",
                travel_time_min=route_result.estimated_travel_time_minutes,
                requires_air=route_result.requires_air,
                fallback=fb4,
            )

            # ── Agent 5: Decision Synthesis ───────────────────────────────
            order.status = DispatchStatus.RECOMMENDING
            (decision_summary, confidence), fb5 = await synthesise_decision(
                llm=self._get_llm(),
                damage=damage_result,
                match=match_result,
                route=route_result,
                protocol=protocol_text,
                any_fallback=any_fallback,
                timeout_seconds=self.llm_config.timeout_seconds,
            )
            any_fallback = any_fallback or fb5
            order.decision_summary = decision_summary
            order.decision_confidence = confidence
            log.info("decision_done", confidence=confidence, fallback=fb5)

            # ── Finalize ─────────────────────────────────────────────────
            order.assigned_resource_id = match_result.recommended_resource_id
            order.assigned_resource_name = match_result.recommended_resource_name
            order.status = (
                DispatchStatus.FALLBACK if any_fallback else DispatchStatus.AWAITING_CONFIRMATION
            )
            order.used_fallback = any_fallback
            order.total_latency_ms = round((time.monotonic() - t_pipeline_start) * 1000, 1)

            log.info(
                "pipeline_complete",
                status=order.status,
                total_latency_ms=order.total_latency_ms,
                any_fallback=any_fallback,
                confidence=confidence,
            )

        except Exception:
            log.exception("pipeline_error")
            order.status = DispatchStatus.FAILED
            order.error = "Pipeline execution failed. See logs for details."
            order.used_fallback = True
            order.total_latency_ms = round((time.monotonic() - t_pipeline_start) * 1000, 1)

        return order

    @classmethod
    async def create_and_ingest(
        cls,
        llm_config: LLMConfig,
        rag_config: RAGConfig,
        state_machine: DispatchStateMachine,
        icp_id: str = "",
        data_dir: Path | None = None,
    ) -> DispatchPipeline:
        """Factory: create the pipeline and ingest all knowledge documents.

        Call this at application startup. Ingestion is idempotent — unchanged
        documents are skipped via content-hash deduplication.

        Args:
            llm_config: LLM configuration.
            rag_config: RAG configuration.
            state_machine: The dispatch state machine (provides resource/zone access).
            icp_id: This ICP node's identifier.
            data_dir: Root data directory. Defaults to ./data.

        Returns:
            A fully initialized and knowledge-loaded DispatchPipeline.
        """
        from salus.rag.index import KnowledgeIndex

        index = KnowledgeIndex(rag_config)
        root = data_dir or Path("data")

        # Ingest static protocol documents
        protocol_dir = root / "protocols"
        drugs_dir = root / "drugs"
        index.ingest_directory(protocol_dir)
        index.ingest_directory(drugs_dir)

        # Ingest auto-generated Pydantic schema docs (Option B RAG scope)
        index.ingest_schema_docs()

        stats = index.stats()
        logger.info(
            "knowledge_index_ready",
            total_chunks=stats.total_chunks,
            sources=len(stats.sources),
        )

        return cls(
            llm_config=llm_config,
            rag_config=rag_config,
            knowledge_index=index,
            state_machine=state_machine,
            icp_id=icp_id,
        )
