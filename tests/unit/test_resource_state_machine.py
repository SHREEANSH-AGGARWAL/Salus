"""
Unit tests for the resource dispatch state machine.

Tests every valid and invalid resource state transition explicitly.
This is the core safety invariant of the system — the state machine
MUST reject invalid transitions to prevent double-dispatch.
"""

from __future__ import annotations

import pytest

from salus.models.resource import (
    ConfirmationSource,
    ResourceStatus,
    ResourceStateTransition,
    is_valid_transition,
)


# ============================================================================
# Valid Transition Tests
# ============================================================================


class TestValidTransitions:
    """Test all valid resource state transitions.

    State machine:
        AVAILABLE → DISPATCHED, MAINTENANCE
        DISPATCHED → ON_SCENE, AVAILABLE (cancellation)
        ON_SCENE → RETURNING, NEEDS_RESUPPLY
        RETURNING → AVAILABLE
        NEEDS_RESUPPLY → RESUPPLYING, RETURNING
        RESUPPLYING → AVAILABLE, DISPATCHED
        MAINTENANCE → AVAILABLE
    """

    @pytest.mark.parametrize(
        "from_status, to_status",
        [
            (ResourceStatus.AVAILABLE, ResourceStatus.DISPATCHED),
            (ResourceStatus.AVAILABLE, ResourceStatus.MAINTENANCE),
            (ResourceStatus.DISPATCHED, ResourceStatus.ON_SCENE),
            (ResourceStatus.DISPATCHED, ResourceStatus.AVAILABLE),     # Cancellation
            (ResourceStatus.ON_SCENE, ResourceStatus.RETURNING),
            (ResourceStatus.ON_SCENE, ResourceStatus.NEEDS_RESUPPLY),
            (ResourceStatus.RETURNING, ResourceStatus.AVAILABLE),
            (ResourceStatus.NEEDS_RESUPPLY, ResourceStatus.RESUPPLYING),
            (ResourceStatus.NEEDS_RESUPPLY, ResourceStatus.RETURNING),
            (ResourceStatus.RESUPPLYING, ResourceStatus.AVAILABLE),
            (ResourceStatus.RESUPPLYING, ResourceStatus.DISPATCHED),
            (ResourceStatus.MAINTENANCE, ResourceStatus.AVAILABLE),
        ],
    )
    def test_valid_transitions(self, from_status: ResourceStatus, to_status: ResourceStatus) -> None:
        assert is_valid_transition(from_status, to_status) is True


# ============================================================================
# Invalid Transition Tests
# ============================================================================


class TestInvalidTransitions:
    """Test all invalid resource state transitions.

    These MUST be rejected — accepting them would allow double-dispatch
    and other safety violations.
    """

    @pytest.mark.parametrize(
        "from_status, to_status",
        [
            # Can't skip DISPATCHED
            (ResourceStatus.AVAILABLE, ResourceStatus.ON_SCENE),
            (ResourceStatus.AVAILABLE, ResourceStatus.RETURNING),
            (ResourceStatus.AVAILABLE, ResourceStatus.NEEDS_RESUPPLY),
            (ResourceStatus.AVAILABLE, ResourceStatus.RESUPPLYING),
            # Can't go backward from DISPATCHED (except cancel)
            (ResourceStatus.DISPATCHED, ResourceStatus.MAINTENANCE),
            (ResourceStatus.DISPATCHED, ResourceStatus.NEEDS_RESUPPLY),
            (ResourceStatus.DISPATCHED, ResourceStatus.RESUPPLYING),
            # Can't go directly available from ON_SCENE
            (ResourceStatus.ON_SCENE, ResourceStatus.AVAILABLE),
            (ResourceStatus.ON_SCENE, ResourceStatus.DISPATCHED),
            (ResourceStatus.ON_SCENE, ResourceStatus.MAINTENANCE),
            (ResourceStatus.ON_SCENE, ResourceStatus.RESUPPLYING),
            # RETURNING can only go to AVAILABLE
            (ResourceStatus.RETURNING, ResourceStatus.DISPATCHED),
            (ResourceStatus.RETURNING, ResourceStatus.ON_SCENE),
            (ResourceStatus.RETURNING, ResourceStatus.MAINTENANCE),
            # MAINTENANCE can only go to AVAILABLE
            (ResourceStatus.MAINTENANCE, ResourceStatus.DISPATCHED),
            (ResourceStatus.MAINTENANCE, ResourceStatus.ON_SCENE),
            (ResourceStatus.MAINTENANCE, ResourceStatus.RETURNING),
            # Same-state transitions
            (ResourceStatus.AVAILABLE, ResourceStatus.AVAILABLE),
            (ResourceStatus.DISPATCHED, ResourceStatus.DISPATCHED),
            (ResourceStatus.ON_SCENE, ResourceStatus.ON_SCENE),
        ],
    )
    def test_invalid_transitions(self, from_status: ResourceStatus, to_status: ResourceStatus) -> None:
        assert is_valid_transition(from_status, to_status) is False


# ============================================================================
# IC Confirmation Gate Tests
# ============================================================================


class TestConfirmationGate:
    """Test the Incident Commander confirmation gate enforcement.

    DISPATCHED transitions MUST have a confirmation_source.
    This is the safety property that prevents autonomous dispatch.
    """

    def test_dispatch_requires_commander_confirmation(self) -> None:
        """RESOURCE_DISPATCHED without confirmation_source must be rejected."""
        transition = ResourceStateTransition(
            resource_id="res-001",
            from_status=ResourceStatus.AVAILABLE,
            to_status=ResourceStatus.DISPATCHED,
            actor_id="system",
            confirmation_source=None,  # Missing!
        )
        with pytest.raises(ValueError, match="confirmation_source"):
            transition.validate_transition()

    def test_dispatch_with_commander_confirmation(self) -> None:
        """RESOURCE_DISPATCHED with COMMANDER confirmation should pass."""
        transition = ResourceStateTransition(
            resource_id="res-001",
            from_status=ResourceStatus.AVAILABLE,
            to_status=ResourceStatus.DISPATCHED,
            zone_id="zone-007",
            incident_id="inc-001",
            actor_id="cmd-vikram",
            confirmation_source=ConfirmationSource.COMMANDER,
            reason="Building collapse — SAR team needed",
        )
        assert transition.validate_transition() is True

    def test_dispatch_with_override_confirmation(self) -> None:
        """RESOURCE_DISPATCHED with OVERRIDE confirmation should pass."""
        transition = ResourceStateTransition(
            resource_id="res-001",
            from_status=ResourceStatus.AVAILABLE,
            to_status=ResourceStatus.DISPATCHED,
            zone_id="zone-007",
            actor_id="cmd-vikram",
            confirmation_source=ConfirmationSource.OVERRIDE,
            commander_override=True,
            override_reason="Different resource better suited",
        )
        assert transition.validate_transition() is True

    def test_non_dispatch_does_not_require_confirmation(self) -> None:
        """Non-DISPATCH transitions should not require confirmation_source."""
        transition = ResourceStateTransition(
            resource_id="res-001",
            from_status=ResourceStatus.DISPATCHED,
            to_status=ResourceStatus.ON_SCENE,
            actor_id="system",
        )
        assert transition.validate_transition() is True

    def test_invalid_transition_raises_error(self) -> None:
        """Attempting an invalid transition must raise ValueError."""
        transition = ResourceStateTransition(
            resource_id="res-001",
            from_status=ResourceStatus.AVAILABLE,
            to_status=ResourceStatus.ON_SCENE,  # Can't skip DISPATCHED
            actor_id="system",
        )
        with pytest.raises(ValueError, match="Invalid resource state transition"):
            transition.validate_transition()


# ============================================================================
# ResourceStateTransition Model Tests
# ============================================================================


class TestResourceStateTransition:
    """Test the ResourceStateTransition model."""

    def test_transition_id_auto_generated(self) -> None:
        t1 = ResourceStateTransition(
            resource_id="r1", from_status=ResourceStatus.AVAILABLE,
            to_status=ResourceStatus.MAINTENANCE, actor_id="sys",
        )
        t2 = ResourceStateTransition(
            resource_id="r1", from_status=ResourceStatus.AVAILABLE,
            to_status=ResourceStatus.MAINTENANCE, actor_id="sys",
        )
        assert t1.id != t2.id

    def test_transition_serialization(self) -> None:
        transition = ResourceStateTransition(
            resource_id="res-001",
            from_status=ResourceStatus.AVAILABLE,
            to_status=ResourceStatus.DISPATCHED,
            zone_id="zone-007",
            actor_id="cmd-vikram",
            confirmation_source=ConfirmationSource.COMMANDER,
            ai_confidence=0.91,
        )
        json_str = transition.model_dump_json()
        restored = ResourceStateTransition.model_validate_json(json_str)
        assert restored.resource_id == "res-001"
        assert restored.confirmation_source == ConfirmationSource.COMMANDER
        assert restored.ai_confidence == 0.91

    def test_ai_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            ResourceStateTransition(
                resource_id="r1",
                from_status=ResourceStatus.AVAILABLE,
                to_status=ResourceStatus.DISPATCHED,
                actor_id="sys",
                confirmation_source=ConfirmationSource.COMMANDER,
                ai_confidence=1.5,  # Out of bounds
            )
