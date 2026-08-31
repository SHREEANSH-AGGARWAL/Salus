"""
Zone priority scoring — deterministic, rule-based.

Computes a zone's priority (P1-P5) from its damage assessment.
This is a pure function: no LLM, no randomness, no external I/O.

Factors (weighted):
  1. Estimated casualties / trapped persons  (40%)
  2. Structural collapse percentage          (25%)
  3. Access difficulty                       (15%)
  4. Time since last contact                 (20%)

The Damage Assessment Agent (Phase 3) will use this as a baseline
and enhance it with LLM reasoning, but this function is always
the ground truth for deterministic scoring.
"""

from __future__ import annotations

from salus.models.zone import AccessStatus, DamageLevel, DisasterZone, ZoneNeeds, ZonePriority


def score_zone_priority(zone: DisasterZone) -> ZonePriority:
    """Compute a zone's priority from its current damage assessment.

    This is deterministic: same inputs always produce same output.
    Used by both the rule-based fallback and as a baseline for
    the AI agent.

    Args:
        zone: The disaster zone to score.

    Returns:
        ZonePriority (P1–P5).
    """
    raw_score = compute_raw_score(zone.needs, zone.damage_level, zone.access_status,
                                  zone.time_since_last_contact_minutes)
    return raw_score_to_priority(raw_score)


def compute_raw_score(
    needs: ZoneNeeds,
    damage_level: DamageLevel,
    access_status: AccessStatus,
    time_since_last_contact_minutes: int,
) -> float:
    """Compute a raw priority score (0.0 - 1.0) from assessment factors.

    Higher score = higher priority (more urgent).

    Args:
        needs: Zone's current resource needs.
        damage_level: Structural damage level.
        access_status: How accessible the zone is.
        time_since_last_contact_minutes: Minutes since last contact.

    Returns:
        Raw score between 0.0 and 1.0.
    """
    # Factor 1: Casualty severity (40% weight)
    casualty_score = _score_casualties(needs)

    # Factor 2: Structural damage (25% weight)
    damage_score = _score_damage(damage_level)

    # Factor 3: Access difficulty (15% weight)
    access_score = _score_access(access_status)

    # Factor 4: Time since last contact (20% weight)
    time_score = _score_time_gap(time_since_last_contact_minutes)

    # Weighted combination
    raw = (
        0.40 * casualty_score
        + 0.25 * damage_score
        + 0.15 * access_score
        + 0.20 * time_score
    )

    return min(1.0, max(0.0, raw))


def raw_score_to_priority(raw_score: float) -> ZonePriority:
    """Convert a raw score to a ZonePriority level.

    Thresholds:
        >= 0.8  → P1 (CRITICAL)
        >= 0.6  → P2 (HIGH)
        >= 0.4  → P3 (MODERATE)
        >= 0.2  → P4 (LOW)
        <  0.2  → P5 (MINIMAL)

    Args:
        raw_score: Score between 0.0 and 1.0.

    Returns:
        ZonePriority level.
    """
    if raw_score >= 0.8:
        return ZonePriority.CRITICAL
    if raw_score >= 0.6:
        return ZonePriority.HIGH
    if raw_score >= 0.4:
        return ZonePriority.MODERATE
    if raw_score >= 0.2:
        return ZonePriority.LOW
    return ZonePriority.MINIMAL


def _score_casualties(needs: ZoneNeeds) -> float:
    """Score based on casualty estimates.

    Considers trapped persons (highest weight), injured, and displaced.
    """
    trapped = needs.estimated_trapped
    injured = needs.estimated_injured

    if trapped >= 50 or injured >= 200:
        return 1.0
    if trapped >= 20 or injured >= 100:
        return 0.8
    if trapped >= 10 or injured >= 50:
        return 0.6
    if trapped >= 5 or injured >= 20:
        return 0.4
    if trapped >= 1 or injured >= 5:
        return 0.2
    return 0.0


def _score_damage(damage_level: DamageLevel) -> float:
    """Score based on structural damage level."""
    scores = {
        DamageLevel.CATASTROPHIC: 1.0,
        DamageLevel.SEVERE: 0.8,
        DamageLevel.MODERATE: 0.5,
        DamageLevel.LIGHT: 0.2,
        DamageLevel.NONE: 0.0,
        DamageLevel.UNKNOWN: 0.5,  # Unknown treated as moderate (precautionary)
    }
    return scores.get(damage_level, 0.5)


def _score_access(access_status: AccessStatus) -> float:
    """Score based on access difficulty.

    Higher difficulty = higher urgency (harder to reach = more vulnerable).
    """
    scores = {
        AccessStatus.CUT_OFF: 1.0,
        AccessStatus.AIR_ONLY: 0.8,
        AccessStatus.WATER_ONLY: 0.7,
        AccessStatus.RESTRICTED: 0.4,
        AccessStatus.OPEN: 0.1,
        AccessStatus.UNKNOWN: 0.5,
    }
    return scores.get(access_status, 0.5)


def _score_time_gap(minutes_since_contact: int) -> float:
    """Score based on time since last contact.

    Longer gaps = higher urgency. "No contact ≠ no need" — it often
    means the zone is in the worst condition.
    """
    if minutes_since_contact >= 360:  # 6+ hours
        return 1.0
    if minutes_since_contact >= 180:  # 3+ hours
        return 0.8
    if minutes_since_contact >= 60:   # 1+ hour
        return 0.6
    if minutes_since_contact >= 30:
        return 0.4
    if minutes_since_contact >= 10:
        return 0.2
    return 0.0
