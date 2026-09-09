"""
Circuit-breaker wrapper for agent pipeline steps.

Every LLM call in the pipeline is wrapped with this to ensure:
1. Hard timeout (circuit trips if LLM doesn't respond in time).
2. Immediate fallback to deterministic rule-based logic.
3. No silent failures — the caller always knows if fallback was used.

This implements the 3-layer architecture from matcher.py's docstring:
  1. Baseline (deterministic) implementation
  2. Circuit-breaker fallback
  3. AI layer (enhancement, not replacement)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import structlog

T = TypeVar("T")

logger = structlog.get_logger()


async def with_fallback(  # noqa: UP047
    agent_fn: Callable[..., Awaitable[T]],
    fallback_fn: Callable[..., T],
    timeout_seconds: float,
    agent_name: str,
    *args: object,
    **kwargs: object,
) -> tuple[T, bool]:
    """Run an async agent function with timeout and deterministic fallback.

    This is the core safety mechanism of the AI pipeline. It ensures that
    any failure (timeout, exception, hallucination-induced parse error) falls
    back to the rule-based system gracefully, without propagating an error
    up to the Incident Commander interface.

    Args:
        agent_fn: The async AI agent function to call.
        fallback_fn: The synchronous deterministic fallback function.
        timeout_seconds: Maximum seconds to wait for the agent.
        agent_name: Name for logging/audit purposes.
        *args: Positional arguments to pass to both agent_fn and fallback_fn.
        **kwargs: Keyword arguments to pass to both agent_fn and fallback_fn.

    Returns:
        Tuple of (result, used_fallback) where:
            - result is the output of agent_fn (or fallback_fn if it tripped)
            - used_fallback is True if the circuit breaker triggered
    """
    try:
        result = await asyncio.wait_for(
            agent_fn(*args, **kwargs),
            timeout=timeout_seconds,
        )
        logger.debug("agent_success", agent=agent_name)
        return result, False

    except TimeoutError:
        logger.warning(
            "agent_timeout",
            agent=agent_name,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        logger.exception("agent_error", agent=agent_name)

    # Circuit breaker tripped — use deterministic fallback
    logger.info("circuit_breaker_fallback", agent=agent_name)
    fallback_result = fallback_fn(*args, **kwargs)
    return fallback_result, True
