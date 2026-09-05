"""Reliability metrics with uncertainty preserved instead of collapsed into a score."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from agent_evals.evidence.models import TrialVerdict

DEFAULT_CONFIDENCE_Z = 1.959963984540054


@dataclass(frozen=True, slots=True)
class ReliabilityReport:
    """Self-validating reliability statistics derived from one exact verdict vector."""

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
    confidence_z: float = DEFAULT_CONFIDENCE_Z

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Revalidate counts, configuration, and every derived statistic in place."""
        for name in (
            "trials",
            "resolved_trials",
            "passes",
            "failures",
            "blocked",
            "inconclusive",
            "k",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")

        if self.trials < 0:
            raise ValueError("trials cannot be negative")
        for name in ("resolved_trials", "passes", "failures", "blocked", "inconclusive"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.k < 1:
            raise ValueError("k must be >= 1")
        _validate_confidence_z(self.confidence_z)

        for name in (
            "success_rate",
            "wilson_low",
            "wilson_high",
            "pass_at_k",
            "pass_power_k",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
                raise ValueError(f"{name} must be a finite float")

        if self.resolved_trials != self.passes + self.failures:
            raise ValueError("resolved_trials must equal passes + failures")
        if self.trials != self.resolved_trials + self.blocked + self.inconclusive:
            raise ValueError("trials must equal passes + failures + blocked + inconclusive")

        expected = _derive_metrics(
            passes=self.passes,
            resolved_trials=self.resolved_trials,
            k=self.k,
            confidence_z=self.confidence_z,
        )
        for name, expected_value in expected.items():
            if getattr(self, name) != expected_value:
                raise ValueError(f"{name} does not recompute from reliability counts")

    @classmethod
    def from_verdicts(
        cls,
        verdicts: list[TrialVerdict] | tuple[TrialVerdict, ...],
        *,
        k: int = 1,
        confidence_z: float = DEFAULT_CONFIDENCE_Z,
    ) -> ReliabilityReport:
        if not verdicts:
            raise ValueError("at least one trial verdict is required")
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("k must be an integer >= 1")
        _validate_confidence_z(confidence_z)
        if any(type(verdict) is not TrialVerdict for verdict in verdicts):
            raise ValueError("trial verdicts must be exact TrialVerdict members")

        trials = len(verdicts)
        passes = sum(verdict is TrialVerdict.PASS for verdict in verdicts)
        failures = sum(verdict is TrialVerdict.FAIL for verdict in verdicts)
        blocked = sum(verdict is TrialVerdict.BLOCKED for verdict in verdicts)
        inconclusive = sum(verdict is TrialVerdict.INCONCLUSIVE for verdict in verdicts)
        resolved_trials = passes + failures
        metrics = _derive_metrics(
            passes=passes,
            resolved_trials=resolved_trials,
            k=k,
            confidence_z=confidence_z,
        )

        return cls(
            trials=trials,
            resolved_trials=resolved_trials,
            passes=passes,
            failures=failures,
            blocked=blocked,
            inconclusive=inconclusive,
            k=k,
            confidence_z=confidence_z,
            **metrics,
        )


def _derive_metrics(
    *,
    passes: int,
    resolved_trials: int,
    k: int,
    confidence_z: float,
) -> dict[str, float]:
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
    return {
        "success_rate": success_rate,
        "wilson_low": low,
        "wilson_high": high,
        "pass_at_k": pass_at_k,
        "pass_power_k": pass_power_k,
    }


def _validate_confidence_z(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value) or value <= 0:
        raise ValueError("confidence_z must be finite and positive")


def _wilson_interval(successes: int, trials: int, z: float) -> tuple[float, float]:
    if isinstance(successes, bool) or not isinstance(successes, int):
        raise ValueError("successes must be an integer")
    if isinstance(trials, bool) or not isinstance(trials, int):
        raise ValueError("trials must be an integer")
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between zero and trials")
    _validate_confidence_z(z)

    p = successes / trials
    z2 = z * z
    denominator = 1.0 + z2 / trials
    centre = (p + z2 / (2.0 * trials)) / denominator
    margin = z * sqrt((p * (1.0 - p) / trials) + z2 / (4.0 * trials * trials)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)
