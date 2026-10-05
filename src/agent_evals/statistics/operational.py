"""Explicit operational distributions for latency, cost, tool-use and retry tails."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import ceil, isfinite

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.limits import MAX_STATISTICAL_TRIALS


class OperationalInclusion(StrEnum):
    ALL_ATTEMPTS = "all_attempts"
    RESOLVED_ONLY = "resolved_only"


@dataclass(frozen=True, slots=True)
class OperationalObservation:
    verdict: TrialVerdict
    latency_ms: float
    cost_usd: float
    tool_calls: int
    retries: int

    def __post_init__(self) -> None:
        if type(self.verdict) is not TrialVerdict:
            raise ValueError("verdict must be an exact TrialVerdict")
        for name in ("latency_ms", "cost_usd"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
                raise ValueError(f"{name} must be a finite float")
            if value < 0.0:
                raise ValueError(f"{name} cannot be negative")
        for name in ("tool_calls", "retries"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative exact integer")


@dataclass(frozen=True, slots=True)
class OperationalSummary:
    """Tail summaries over an explicit attempt-inclusion population."""

    observations: tuple[OperationalObservation, ...]
    inclusion: OperationalInclusion

    def __post_init__(self) -> None:
        if type(self.observations) is not tuple:
            raise ValueError("observations must be an exact tuple")
        if not 1 <= len(self.observations) <= MAX_STATISTICAL_TRIALS:
            raise ValueError(
                f"observation count must be in 1..{MAX_STATISTICAL_TRIALS}"
            )
        if type(self.inclusion) is not OperationalInclusion:
            raise ValueError("inclusion must be an exact OperationalInclusion")
        for observation in self.observations:
            if type(observation) is not OperationalObservation:
                raise ValueError("observations must contain exact OperationalObservation values")
        if not self.included:
            raise ValueError("operational summary has no observations under its inclusion policy")

    @property
    def total_attempts(self) -> int:
        return len(self.observations)

    @property
    def included(self) -> tuple[OperationalObservation, ...]:
        if self.inclusion is OperationalInclusion.ALL_ATTEMPTS:
            return self.observations
        return tuple(
            observation
            for observation in self.observations
            if observation.verdict in (TrialVerdict.PASS, TrialVerdict.FAIL)
        )

    @property
    def included_attempts(self) -> int:
        return len(self.included)

    @property
    def excluded_blocked(self) -> int:
        if self.inclusion is OperationalInclusion.ALL_ATTEMPTS:
            return 0
        return sum(
            observation.verdict is TrialVerdict.BLOCKED for observation in self.observations
        )

    @property
    def excluded_inconclusive(self) -> int:
        if self.inclusion is OperationalInclusion.ALL_ATTEMPTS:
            return 0
        return sum(
            observation.verdict is TrialVerdict.INCONCLUSIVE
            for observation in self.observations
        )

    @property
    def latency_p50_ms(self) -> float:
        return _float_quantile([item.latency_ms for item in self.included], 0.50)

    @property
    def latency_p95_ms(self) -> float:
        return _float_quantile([item.latency_ms for item in self.included], 0.95)

    @property
    def latency_p99_ms(self) -> float:
        return _float_quantile([item.latency_ms for item in self.included], 0.99)

    @property
    def cost_p50_usd(self) -> float:
        return _float_quantile([item.cost_usd for item in self.included], 0.50)

    @property
    def cost_p95_usd(self) -> float:
        return _float_quantile([item.cost_usd for item in self.included], 0.95)

    @property
    def cost_p99_usd(self) -> float:
        return _float_quantile([item.cost_usd for item in self.included], 0.99)

    @property
    def tool_calls_p95(self) -> int:
        return _int_quantile([item.tool_calls for item in self.included], 0.95)

    @property
    def tool_calls_p99(self) -> int:
        return _int_quantile([item.tool_calls for item in self.included], 0.99)

    @property
    def retries_p95(self) -> int:
        return _int_quantile([item.retries for item in self.included], 0.95)

    @property
    def retries_p99(self) -> int:
        return _int_quantile([item.retries for item in self.included], 0.99)


def _float_quantile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    rank = max(1, ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def _int_quantile(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    rank = max(1, ceil(quantile * len(ordered)))
    return ordered[rank - 1]
