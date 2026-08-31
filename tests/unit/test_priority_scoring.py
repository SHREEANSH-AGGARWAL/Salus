"""
Unit tests for zone priority scoring.

Tests the deterministic, rule-based priority scoring function
with known inputs and expected outputs.
"""

from __future__ import annotations

import pytest

from salus.dispatch.priority import (
    compute_raw_score,
    raw_score_to_priority,
    score_zone_priority,
)
from salus.models.zone import (
    AccessStatus,
    DamageLevel,
    DisasterZone,
    GeoLocation,
    ZoneBoundary,
    ZoneNeeds,
    ZonePriority,
)


# ============================================================================
# Raw Score to Priority Mapping Tests
# ============================================================================


class TestRawScoreToPriority:
    """Test the score-to-priority threshold mapping."""

    @pytest.mark.parametrize(
        "score, expected",
        [
            (1.0, ZonePriority.CRITICAL),
            (0.9, ZonePriority.CRITICAL),
            (0.8, ZonePriority.CRITICAL),
            (0.79, ZonePriority.HIGH),
            (0.7, ZonePriority.HIGH),
            (0.6, ZonePriority.HIGH),
            (0.59, ZonePriority.MODERATE),
            (0.4, ZonePriority.MODERATE),
            (0.39, ZonePriority.LOW),
            (0.2, ZonePriority.LOW),
            (0.19, ZonePriority.MINIMAL),
            (0.0, ZonePriority.MINIMAL),
        ],
    )
    def test_score_thresholds(self, score: float, expected: ZonePriority) -> None:
        assert raw_score_to_priority(score) == expected


# ============================================================================
# Full Priority Scoring Tests
# ============================================================================


class TestScoreZonePriority:
    """Test end-to-end zone priority scoring."""

    def test_critical_zone(self) -> None:
        """High casualties + catastrophic damage → P1."""
        zone = _make_zone(
            trapped=50, injured=200,
            damage=DamageLevel.CATASTROPHIC,
            access=AccessStatus.AIR_ONLY,
            time_since_contact=200,
        )
        assert score_zone_priority(zone) == ZonePriority.CRITICAL

    def test_high_priority_zone(self) -> None:
        """Significant casualties + severe damage → P2 or P3 (boundary case)."""
        zone = _make_zone(
            trapped=15, injured=60,
            damage=DamageLevel.SEVERE,
            access=AccessStatus.RESTRICTED,
            time_since_contact=45,
        )
        priority = score_zone_priority(zone)
        assert priority in (ZonePriority.CRITICAL, ZonePriority.HIGH, ZonePriority.MODERATE)

    def test_low_priority_zone(self) -> None:
        """No casualties + light damage → P4 or P5."""
        zone = _make_zone(
            trapped=0, injured=0,
            damage=DamageLevel.LIGHT,
            access=AccessStatus.OPEN,
            time_since_contact=5,
        )
        priority = score_zone_priority(zone)
        assert priority in (ZonePriority.LOW, ZonePriority.MINIMAL)

    def test_minimal_damage_zone(self) -> None:
        """No damage, no casualties → P5."""
        zone = _make_zone(
            trapped=0, injured=0,
            damage=DamageLevel.NONE,
            access=AccessStatus.OPEN,
            time_since_contact=0,
        )
        assert score_zone_priority(zone) == ZonePriority.MINIMAL

    def test_unknown_damage_moderate_treatment(self) -> None:
        """Unknown damage treated as moderate (precautionary)."""
        zone = _make_zone(
            trapped=5, injured=10,
            damage=DamageLevel.UNKNOWN,
            access=AccessStatus.UNKNOWN,
            time_since_contact=30,
        )
        priority = score_zone_priority(zone)
        # Unknown damage + some casualties → should be at least MODERATE
        assert priority.value <= ZonePriority.MODERATE.value

    def test_long_contact_gap_increases_priority(self) -> None:
        """6+ hours without contact → significantly higher priority."""
        zone_recent = _make_zone(
            trapped=5, injured=10, damage=DamageLevel.MODERATE,
            access=AccessStatus.RESTRICTED, time_since_contact=5,
        )
        zone_stale = _make_zone(
            trapped=5, injured=10, damage=DamageLevel.MODERATE,
            access=AccessStatus.RESTRICTED, time_since_contact=400,
        )
        score_recent = compute_raw_score(
            zone_recent.needs, zone_recent.damage_level,
            zone_recent.access_status, zone_recent.time_since_last_contact_minutes,
        )
        score_stale = compute_raw_score(
            zone_stale.needs, zone_stale.damage_level,
            zone_stale.access_status, zone_stale.time_since_last_contact_minutes,
        )
        assert score_stale > score_recent


# ============================================================================
# Determinism Tests
# ============================================================================


class TestDeterminism:
    """Verify scoring is deterministic — same input always gives same output."""

    def test_repeated_scoring_identical(self) -> None:
        zone = _make_zone(
            trapped=30, injured=100,
            damage=DamageLevel.CATASTROPHIC,
            access=AccessStatus.RESTRICTED,
            time_since_contact=120,
        )
        results = [score_zone_priority(zone) for _ in range(100)]
        assert all(r == results[0] for r in results)

    def test_raw_score_deterministic(self) -> None:
        needs = ZoneNeeds(estimated_trapped=20, estimated_injured=50)
        scores = [
            compute_raw_score(needs, DamageLevel.SEVERE, AccessStatus.RESTRICTED, 60)
            for _ in range(100)
        ]
        assert all(s == scores[0] for s in scores)


# ============================================================================
# Individual Factor Tests
# ============================================================================


class TestCasualtyScoring:
    """Test casualty factor scoring."""

    @pytest.mark.parametrize(
        "trapped, injured, min_expected_score",
        [
            (50, 200, 0.7),   # Mass casualties → near max
            (20, 100, 0.5),   # Significant
            (5, 20, 0.2),     # Moderate
            (0, 0, 0.0),      # None
        ],
    )
    def test_casualty_scaling(
        self, trapped: int, injured: int, min_expected_score: float
    ) -> None:
        needs = ZoneNeeds(estimated_trapped=trapped, estimated_injured=injured)
        score = compute_raw_score(needs, DamageLevel.NONE, AccessStatus.OPEN, 0)
        assert score >= min_expected_score * 0.4  # 40% weight


# ============================================================================
# Helper
# ============================================================================


def _make_zone(
    trapped: int = 0,
    injured: int = 0,
    damage: DamageLevel = DamageLevel.NONE,
    access: AccessStatus = AccessStatus.OPEN,
    time_since_contact: int = 0,
) -> DisasterZone:
    """Create a minimal zone for testing."""
    return DisasterZone(
        name="Test Zone",
        zone_code="T-01",
        boundary=ZoneBoundary(
            center=GeoLocation(latitude=28.6, longitude=77.2),
            radius_km=1.0,
        ),
        damage_level=damage,
        access_status=access,
        needs=ZoneNeeds(
            estimated_trapped=trapped,
            estimated_injured=injured,
            needs_sar=trapped > 0,
            needs_medical=injured > 10,
        ),
        time_since_last_contact_minutes=time_since_contact,
    )
