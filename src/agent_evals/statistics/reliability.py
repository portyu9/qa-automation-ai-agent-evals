"""Reliability metrics with uncertainty preserved instead of collapsed into a score."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from agent_evals.evidence.models import TrialVerdict


@dataclass(frozen=True, slots=True)
class ReliabilityReport:
    trials: int
    resolved_trials: int
    passes: int
    failures: int
    blocked: int
    inconclusive: int
    success_rate: float
    wilson_low: float
    wilson_high: float
    pass_at_k: float
    pass_power_k: float
    k: int

    @classmethod
    def from_verdicts(
        cls,
        verdicts: list[TrialVerdict] | tuple[TrialVerdict, ...],
        *,
        k: int = 1,
        confidence_z: float = 1.959963984540054,
    ) -> ReliabilityReport:
        if not verdicts:
            raise ValueError("at least one trial verdict is required")
        if k < 1:
            raise ValueError("k must be >= 1")
        if not isfinite(confidence_z) or confidence_z <= 0:
            raise ValueError("confidence_z must be finite and positive")

        trials = len(verdicts)
        passes = sum(verdict is TrialVerdict.PASS for verdict in verdicts)
        failures = sum(verdict is TrialVerdict.FAIL for verdict in verdicts)
        blocked = sum(verdict is TrialVerdict.BLOCKED for verdict in verdicts)
        inconclusive = sum(verdict is TrialVerdict.INCONCLUSIVE for verdict in verdicts)
        resolved_trials = passes + failures

        if resolved_trials:
            success_rate = passes / resolved_trials
            low, high = _wilson_interval(passes, resolved_trials, confidence_z)
            pass_at_k = 1.0 - (1.0 - success_rate) ** k
            pass_power_k = success_rate**k
        else:
            success_rate = 0.0
            low, high = 0.0, 1.0
            pass_at_k = 0.0
            pass_power_k = 0.0

        return cls(
            trials=trials,
            resolved_trials=resolved_trials,
            passes=passes,
            failures=failures,
            blocked=blocked,
            inconclusive=inconclusive,
            success_rate=success_rate,
            wilson_low=low,
            wilson_high=high,
            pass_at_k=pass_at_k,
            pass_power_k=pass_power_k,
            k=k,
        )


def _wilson_interval(successes: int, trials: int, z: float) -> tuple[float, float]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between zero and trials")
    if not isfinite(z) or z <= 0:
        raise ValueError("confidence_z must be finite and positive")

    p = successes / trials
    z2 = z * z
    denominator = 1.0 + z2 / trials
    centre = (p + z2 / (2.0 * trials)) / denominator
    margin = z * sqrt((p * (1.0 - p) / trials) + z2 / (4.0 * trials * trials)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)
