"""
Incident Commander confirmation gate.

The IC gate is the hard safety boundary between AI recommendation and
resource dispatch. No resource dispatch commits to the Raft log without
explicit Incident Commander confirmation. This is non-negotiable.

Flow:
    1. Agent pipeline produces dispatch recommendation
    2. Recommendation queued for IC review
    3. IC confirms / rejects / overrides
    4. Only confirmed/overridden dispatches become Raft log entries
    5. Timeout → automatic rejection (fail-safe)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

from salus.models.resource import ConfirmationSource

logger = structlog.get_logger()


class GateAction(StrEnum):
    """Actions the Incident Commander can take at the gate."""

    CONFIRM = "confirm"        # Accept AI recommendation as-is
    REJECT = "reject"          # Reject — do not dispatch
    OVERRIDE = "override"      # Accept but change resource/zone assignment
    TIMEOUT = "timeout"        # No response within timeout → auto-reject


class PendingConfirmation(BaseModel):
    """A dispatch recommendation awaiting IC confirmation.

    This is a transient object — it exists only while the dispatch
    is waiting for IC review. Once the IC acts, the result is written
    to the Raft log and this object is removed.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(seconds=120)
    )

    # What's being recommended
    dispatch_order_id: str = Field(..., description="Dispatch order ID")
    resource_id: str = Field(..., description="Recommended resource")
    resource_name: str = Field("", description="Resource display name")
    zone_id: str = Field(..., description="Target zone")
    zone_name: str = Field("", description="Zone display name")
    incident_id: str = Field(..., description="Related incident")

    # AI recommendation context
    ai_confidence: float = Field(0.0, ge=0.0, le=1.0)
    ai_reasoning: str = Field("")
    alternative_resources: list[str] = Field(default_factory=list)

    # Resolution (populated when IC acts)
    resolved: bool = Field(False)
    resolved_at: datetime | None = Field(None)
    action: GateAction | None = Field(None)
    commander_id: str | None = Field(None)
    commander_agency_id: str | None = Field(None)
    commander_notes: str | None = Field(None)
    override_resource_id: str | None = Field(
        None, description="Different resource if IC overrides"
    )

    @property
    def is_expired(self) -> bool:
        """True if this confirmation has timed out."""
        return datetime.utcnow() > self.expires_at and not self.resolved


class CommanderGate:
    """Incident Commander confirmation gate.

    Manages pending dispatch confirmations. The IC must act on each
    recommendation before it can be committed to the Raft log.

    Thread-safe: In production, this would need locking. For the
    prototype, single-threaded asyncio is sufficient.
    """

    def __init__(self, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds
        self.pending: dict[str, PendingConfirmation] = {}
        self._history: list[PendingConfirmation] = []

    def request_confirmation(
        self,
        dispatch_order_id: str,
        resource_id: str,
        resource_name: str,
        zone_id: str,
        zone_name: str,
        incident_id: str,
        ai_confidence: float = 0.0,
        ai_reasoning: str = "",
        alternative_resources: list[str] | None = None,
    ) -> PendingConfirmation:
        """Queue a dispatch recommendation for IC review.

        Args:
            dispatch_order_id: The dispatch order to confirm.
            resource_id: Recommended resource ID.
            resource_name: Resource display name.
            zone_id: Target zone ID.
            zone_name: Zone display name.
            incident_id: Related incident ID.
            ai_confidence: AI pipeline confidence score.
            ai_reasoning: AI pipeline reasoning.
            alternative_resources: Fallback resource IDs.

        Returns:
            The pending confirmation object.
        """
        confirmation = PendingConfirmation(
            dispatch_order_id=dispatch_order_id,
            resource_id=resource_id,
            resource_name=resource_name,
            zone_id=zone_id,
            zone_name=zone_name,
            incident_id=incident_id,
            ai_confidence=ai_confidence,
            ai_reasoning=ai_reasoning,
            alternative_resources=alternative_resources or [],
            expires_at=datetime.utcnow() + timedelta(seconds=self.timeout_seconds),
        )
        self.pending[confirmation.id] = confirmation

        logger.info(
            "confirmation_requested",
            confirmation_id=confirmation.id,
            resource=resource_name,
            zone=zone_name,
            confidence=ai_confidence,
            expires_in_seconds=self.timeout_seconds,
        )

        return confirmation

    def confirm(
        self,
        confirmation_id: str,
        commander_id: str,
        commander_agency_id: str = "",
        notes: str = "",
    ) -> PendingConfirmation:
        """IC confirms the dispatch recommendation.

        Args:
            confirmation_id: The pending confirmation to confirm.
            commander_id: ID of the confirming IC.
            commander_agency_id: Agency of the IC.
            notes: IC's notes.

        Returns:
            The resolved confirmation.

        Raises:
            KeyError: If confirmation not found.
            ValueError: If already resolved or expired.
        """
        confirmation = self._get_and_validate(confirmation_id)

        confirmation.resolved = True
        confirmation.resolved_at = datetime.utcnow()
        confirmation.action = GateAction.CONFIRM
        confirmation.commander_id = commander_id
        confirmation.commander_agency_id = commander_agency_id
        confirmation.commander_notes = notes

        self._archive(confirmation_id)

        logger.info(
            "dispatch_confirmed",
            confirmation_id=confirmation_id,
            commander=commander_id,
            resource=confirmation.resource_id,
            zone=confirmation.zone_id,
        )

        return confirmation

    def reject(
        self,
        confirmation_id: str,
        commander_id: str,
        commander_agency_id: str = "",
        reason: str = "",
    ) -> PendingConfirmation:
        """IC rejects the dispatch recommendation.

        Args:
            confirmation_id: The pending confirmation to reject.
            commander_id: ID of the rejecting IC.
            commander_agency_id: Agency of the IC.
            reason: Reason for rejection.

        Returns:
            The resolved confirmation.

        Raises:
            KeyError: If confirmation not found.
            ValueError: If already resolved or expired.
        """
        confirmation = self._get_and_validate(confirmation_id)

        confirmation.resolved = True
        confirmation.resolved_at = datetime.utcnow()
        confirmation.action = GateAction.REJECT
        confirmation.commander_id = commander_id
        confirmation.commander_agency_id = commander_agency_id
        confirmation.commander_notes = reason

        self._archive(confirmation_id)

        logger.info(
            "dispatch_rejected",
            confirmation_id=confirmation_id,
            commander=commander_id,
            reason=reason,
        )

        return confirmation

    def override(
        self,
        confirmation_id: str,
        commander_id: str,
        override_resource_id: str,
        commander_agency_id: str = "",
        notes: str = "",
    ) -> PendingConfirmation:
        """IC overrides with a different resource assignment.

        Args:
            confirmation_id: The pending confirmation to override.
            commander_id: ID of the overriding IC.
            override_resource_id: The resource the IC wants instead.
            commander_agency_id: Agency of the IC.
            notes: IC's reason for override.

        Returns:
            The resolved confirmation.

        Raises:
            KeyError: If confirmation not found.
            ValueError: If already resolved or expired.
        """
        confirmation = self._get_and_validate(confirmation_id)

        confirmation.resolved = True
        confirmation.resolved_at = datetime.utcnow()
        confirmation.action = GateAction.OVERRIDE
        confirmation.commander_id = commander_id
        confirmation.commander_agency_id = commander_agency_id
        confirmation.commander_notes = notes
        confirmation.override_resource_id = override_resource_id

        self._archive(confirmation_id)

        logger.info(
            "dispatch_overridden",
            confirmation_id=confirmation_id,
            commander=commander_id,
            original_resource=confirmation.resource_id,
            override_resource=override_resource_id,
        )

        return confirmation

    def expire_stale(self) -> list[PendingConfirmation]:
        """Expire all pending confirmations past their timeout.

        Called periodically to enforce the timeout. Timed-out
        confirmations are treated as rejections (fail-safe).

        Returns:
            List of expired confirmations.
        """
        expired = []
        for cid, confirmation in list(self.pending.items()):
            if confirmation.is_expired:
                confirmation.resolved = True
                confirmation.resolved_at = datetime.utcnow()
                confirmation.action = GateAction.TIMEOUT
                self._archive(cid)
                expired.append(confirmation)

                logger.warning(
                    "confirmation_expired",
                    confirmation_id=cid,
                    resource=confirmation.resource_id,
                    zone=confirmation.zone_id,
                )

        return expired

    def get_pending(self) -> list[PendingConfirmation]:
        """Return all pending (unresolved) confirmations."""
        return list(self.pending.values())

    def get_confirmation_result(self, confirmation_id: str) -> ConfirmationSource | None:
        """Map gate action to ConfirmationSource for Raft log entry.

        Returns:
            ConfirmationSource if confirmed/overridden, None if rejected/timeout.
        """
        # Check history
        for c in self._history:
            if c.id == confirmation_id:
                if c.action == GateAction.CONFIRM:
                    return ConfirmationSource.COMMANDER
                if c.action == GateAction.OVERRIDE:
                    return ConfirmationSource.OVERRIDE
                return None
        return None

    def _get_and_validate(self, confirmation_id: str) -> PendingConfirmation:
        """Get a pending confirmation and validate it can be acted upon."""
        confirmation = self.pending.get(confirmation_id)
        if confirmation is None:
            raise KeyError(f"Confirmation not found: {confirmation_id}")

        if confirmation.resolved:
            raise ValueError(f"Confirmation {confirmation_id} already resolved")

        if confirmation.is_expired:
            raise ValueError(
                f"Confirmation {confirmation_id} has expired "
                f"(timeout: {self.timeout_seconds}s)"
            )

        return confirmation

    def _archive(self, confirmation_id: str) -> None:
        """Move a resolved confirmation to history."""
        confirmation = self.pending.pop(confirmation_id, None)
        if confirmation:
            self._history.append(confirmation)
