"""Evaluator-owned computational ceilings for statistical assurance kernels."""

from __future__ import annotations

from typing import Any

MAX_STATISTICAL_TRIALS = 100_000
MAX_RELIABILITY_K = 1_000_000


def validate_materialized_statistical_vector(
    value: list[Any] | tuple[Any, ...],
    *,
    label: str,
) -> int:
    """Require one bounded built-in list/tuple before statistical iteration begins."""
    if type(value) not in (list, tuple):
        raise ValueError(f"{label} must be an exact list or tuple")
    count = len(value)
    if count > MAX_STATISTICAL_TRIALS:
        raise ValueError(
            f"{label} exceeds maximum statistical trial count {MAX_STATISTICAL_TRIALS}"
        )
    return count


def validate_reliability_k(value: int) -> int:
    """Bound algebraic retry depth before float exponentiation."""
    if type(value) is not int or value < 1:
        raise ValueError("k must be an integer >= 1")
    if value > MAX_RELIABILITY_K:
        raise ValueError(f"k exceeds maximum reliability retry depth {MAX_RELIABILITY_K}")
    return value
