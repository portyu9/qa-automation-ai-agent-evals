"""Deterministic multiplicity control for bounded collections of predeclared hypotheses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

MAX_HYPOTHESES = 10_000
_MAX_HYPOTHESIS_ID = 160


class MultiplicityMethod(StrEnum):
    HOLM_FWER = "holm_fwer"
    BENJAMINI_HOCHBERG_FDR = "benjamini_hochberg_fdr"


@dataclass(frozen=True, slots=True)
class HypothesisPValue:
    hypothesis_id: str
    p_value: float

    def __post_init__(self) -> None:
        _validate_id(self.hypothesis_id)
        _validate_unit_float(self.p_value, name="p_value", allow_zero=True)


@dataclass(frozen=True, slots=True)
class AdjustedHypothesis:
    hypothesis_id: str
    p_value: float
    adjusted_p_value: float
    rejected: bool

    def __post_init__(self) -> None:
        _validate_id(self.hypothesis_id)
        _validate_unit_float(self.p_value, name="p_value", allow_zero=True)
        _validate_unit_float(self.adjusted_p_value, name="adjusted_p_value", allow_zero=True)
        if type(self.rejected) is not bool:
            raise ValueError("rejected must be an exact bool")


def adjust_p_values(
    hypotheses: list[HypothesisPValue] | tuple[HypothesisPValue, ...],
    *,
    method: MultiplicityMethod,
    alpha: float = 0.05,
) -> tuple[AdjustedHypothesis, ...]:
    """Adjust p-values and restore caller order after deterministic tie-breaking."""

    if type(hypotheses) not in (list, tuple):
        raise ValueError("hypotheses must be an exact list or tuple")
    count = len(hypotheses)
    if count == 0:
        raise ValueError("at least one hypothesis is required")
    if count > MAX_HYPOTHESES:
        raise ValueError(f"hypothesis count exceeds maximum {MAX_HYPOTHESES}")
    if type(method) is not MultiplicityMethod:
        raise ValueError("method must be an exact MultiplicityMethod")
    _validate_unit_float(alpha, name="alpha", allow_zero=False)

    seen: set[str] = set()
    indexed: list[tuple[int, HypothesisPValue]] = []
    for index, hypothesis in enumerate(hypotheses):
        if type(hypothesis) is not HypothesisPValue:
            raise ValueError("hypotheses must contain exact HypothesisPValue values")
        if hypothesis.hypothesis_id in seen:
            raise ValueError("hypothesis identifiers must be unique")
        seen.add(hypothesis.hypothesis_id)
        indexed.append((index, hypothesis))

    ordered = sorted(
        indexed,
        key=lambda item: (item[1].p_value, item[1].hypothesis_id),
    )
    if method is MultiplicityMethod.HOLM_FWER:
        adjusted = _holm_adjusted([item[1].p_value for item in ordered])
    else:
        adjusted = _bh_adjusted([item[1].p_value for item in ordered])

    restored: list[AdjustedHypothesis | None] = [None] * count
    for (original_index, hypothesis), adjusted_p in zip(ordered, adjusted, strict=True):
        restored[original_index] = AdjustedHypothesis(
            hypothesis_id=hypothesis.hypothesis_id,
            p_value=hypothesis.p_value,
            adjusted_p_value=adjusted_p,
            rejected=adjusted_p <= alpha,
        )
    if any(item is None for item in restored):
        raise AssertionError("internal multiplicity ordering did not cover every hypothesis")
    return tuple(item for item in restored if item is not None)


def _holm_adjusted(p_values: list[float]) -> list[float]:
    total = len(p_values)
    result: list[float] = []
    running = 0.0
    for index, p_value in enumerate(p_values):
        candidate = min(1.0, (total - index) * p_value)
        running = max(running, candidate)
        result.append(running)
    return result


def _bh_adjusted(p_values: list[float]) -> list[float]:
    total = len(p_values)
    result = [1.0] * total
    running = 1.0
    for index in range(total - 1, -1, -1):
        rank = index + 1
        candidate = min(1.0, total * p_values[index] / rank)
        running = min(running, candidate)
        result[index] = running
    return result


def _validate_id(value: object) -> None:
    if type(value) is not str:
        raise ValueError("hypothesis_id must be an exact string")
    if (
        not value
        or len(value) > _MAX_HYPOTHESIS_ID
        or value.strip() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(
            f"hypothesis_id must contain 1..{_MAX_HYPOTHESIS_ID} trimmed characters "
            "without controls"
        )


def _validate_unit_float(value: object, *, name: str, allow_zero: bool) -> None:
    if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
        raise ValueError(f"{name} must be a finite float")
    if allow_zero:
        valid = 0.0 <= value <= 1.0
    else:
        valid = 0.0 < value < 1.0
    if not valid:
        raise ValueError(f"{name} is outside the permitted probability interval")
