"""Time-uniform Bernoulli confidence sequences with explicit unresolved-attempt handling."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log, pi, sqrt

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.limits import validate_materialized_statistical_vector


@dataclass(frozen=True, slots=True)
class ConfidenceSequencePoint:
    attempt_index: int
    resolved_index: int
    passes: int
    failures: int
    blocked: int
    inconclusive: int
    lower: float
    upper: float
    allocated_alpha: float

    def __post_init__(self) -> None:
        for name in (
            "attempt_index",
            "resolved_index",
            "passes",
            "failures",
            "blocked",
            "inconclusive",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative exact integer")
        for name in ("lower", "upper", "allocated_alpha"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
                raise ValueError(f"{name} must be a finite float")
        if not 0.0 <= self.lower <= self.upper <= 1.0:
            raise ValueError("confidence-sequence interval must lie in [0, 1]")
        if not 0.0 <= self.allocated_alpha < 1.0:
            raise ValueError("allocated_alpha must lie in [0, 1)")


def bernoulli_confidence_sequence(
    verdicts: list[TrialVerdict] | tuple[TrialVerdict, ...],
    *,
    alpha: float = 0.05,
) -> tuple[ConfidenceSequencePoint, ...]:
    """Return an anytime-valid sequence for the mean of resolved PASS/FAIL observations.

    The construction spends alpha_t = alpha * 6 / (pi^2 * t^2) at resolved index t and uses a
    two-sided Hoeffding interval. The union bound makes simultaneous coverage at all resolved times
    at least 1-alpha under independent bounded resolved observations.

    BLOCKED and INCONCLUSIVE attempts advance the attempt index and counters but do not update the
    resolved Bernoulli sequence. This does not make informative missingness ignorable.
    """

    validate_materialized_statistical_vector(
        verdicts,
        label="confidence-sequence verdict vector",
    )
    _validate_alpha(alpha)

    passes = failures = blocked = inconclusive = 0
    points: list[ConfidenceSequencePoint] = []
    for attempt_index, verdict in enumerate(verdicts, start=1):
        if type(verdict) is not TrialVerdict:
            raise ValueError("confidence-sequence verdicts must be exact TrialVerdict members")
        allocated_alpha = 0.0
        if verdict is TrialVerdict.PASS:
            passes += 1
        elif verdict is TrialVerdict.FAIL:
            failures += 1
        elif verdict is TrialVerdict.BLOCKED:
            blocked += 1
        else:
            inconclusive += 1

        resolved = passes + failures
        if resolved == 0:
            lower, upper = 0.0, 1.0
        else:
            allocated_alpha = alpha * 6.0 / (pi * pi * resolved * resolved)
            radius = sqrt(log(2.0 / allocated_alpha) / (2.0 * resolved))
            mean = passes / resolved
            lower = max(0.0, mean - radius)
            upper = min(1.0, mean + radius)

        points.append(
            ConfidenceSequencePoint(
                attempt_index=attempt_index,
                resolved_index=resolved,
                passes=passes,
                failures=failures,
                blocked=blocked,
                inconclusive=inconclusive,
                lower=lower,
                upper=upper,
                allocated_alpha=allocated_alpha,
            )
        )
    return tuple(points)


def _validate_alpha(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
        raise ValueError("alpha must be a finite float in (0, 1)")
    if not 0.0 < value < 1.0:
        raise ValueError("alpha must be in (0, 1)")
