"""Bounded campaign change-point scan with family-wise correction over candidate splits."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.limits import validate_materialized_statistical_vector


@dataclass(frozen=True, slots=True)
class ChangePointCandidate:
    split_index: int
    reference_trials: int
    current_trials: int
    reference_success_rate: float
    current_success_rate: float
    delta: float
    raw_p_upper_bound: float
    adjusted_p_upper_bound: float

    def __post_init__(self) -> None:
        for name in ("split_index", "reference_trials", "current_trials"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive exact integer")
        for name in (
            "reference_success_rate",
            "current_success_rate",
            "raw_p_upper_bound",
            "adjusted_p_upper_bound",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
                raise ValueError(f"{name} must be a finite float")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must lie in [0, 1]")
        if isinstance(self.delta, bool) or not isinstance(self.delta, float):
            raise ValueError("delta must be an exact finite float")
        if not isfinite(self.delta) or not -1.0 <= self.delta <= 1.0:
            raise ValueError("delta must lie in [-1, 1]")


@dataclass(frozen=True, slots=True)
class ChangePointResult:
    detected: bool
    scanned_splits: int
    candidate: ChangePointCandidate | None

    def __post_init__(self) -> None:
        if type(self.detected) is not bool:
            raise ValueError("detected must be an exact bool")
        if type(self.scanned_splits) is not int or self.scanned_splits <= 0:
            raise ValueError("scanned_splits must be a positive exact integer")
        if self.detected != (self.candidate is not None):
            raise ValueError("detected must agree with candidate presence")


def detect_binary_change_point(
    verdicts: list[TrialVerdict] | tuple[TrialVerdict, ...],
    *,
    minimum_segment_trials: int = 20,
    alpha: float = 0.05,
    minimum_absolute_delta: float = 0.0,
) -> ChangePointResult:
    """Scan predeclared campaign order for one rate shift using Bonferroni control.

    All observations must be resolved PASS/FAIL. BLOCKED or INCONCLUSIVE attempts require a
    separate availability/missingness analysis and are never coerced into the binary rate.
    """

    count = validate_materialized_statistical_vector(
        verdicts,
        label="change-point verdict vector",
    )
    if type(minimum_segment_trials) is not int or minimum_segment_trials < 1:
        raise ValueError("minimum_segment_trials must be a positive exact integer")
    if count < 2 * minimum_segment_trials:
        raise ValueError("change-point scan requires two complete minimum-sized segments")
    _validate_alpha(alpha)
    if isinstance(minimum_absolute_delta, bool) or not isinstance(minimum_absolute_delta, float):
        raise ValueError("minimum_absolute_delta must be an exact finite float")
    if not isfinite(minimum_absolute_delta) or not 0.0 <= minimum_absolute_delta <= 1.0:
        raise ValueError("minimum_absolute_delta must lie in [0, 1]")

    prefix_passes = [0]
    for verdict in verdicts:
        if type(verdict) is not TrialVerdict:
            raise ValueError("change-point verdicts must be exact TrialVerdict members")
        if verdict in (TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE):
            raise ValueError(
                "change-point detection requires resolved PASS/FAIL outcomes; "
                "BLOCKED and INCONCLUSIVE remain separate"
            )
        prefix_passes.append(prefix_passes[-1] + int(verdict is TrialVerdict.PASS))

    first = minimum_segment_trials
    last = count - minimum_segment_trials
    scanned = last - first + 1
    total_passes = prefix_passes[-1]
    candidates: list[ChangePointCandidate] = []
    for split in range(first, last + 1):
        left_n = split
        right_n = count - split
        left_rate = prefix_passes[split] / left_n
        right_rate = (total_passes - prefix_passes[split]) / right_n
        delta = right_rate - left_rate
        denominator = (1.0 / left_n) + (1.0 / right_n)
        raw = min(1.0, 2.0 * exp(-2.0 * delta * delta / denominator))
        adjusted = min(1.0, raw * scanned)
        if abs(delta) >= minimum_absolute_delta and adjusted <= alpha:
            candidates.append(
                ChangePointCandidate(
                    split_index=split,
                    reference_trials=left_n,
                    current_trials=right_n,
                    reference_success_rate=left_rate,
                    current_success_rate=right_rate,
                    delta=delta,
                    raw_p_upper_bound=raw,
                    adjusted_p_upper_bound=adjusted,
                )
            )

    if not candidates:
        return ChangePointResult(detected=False, scanned_splits=scanned, candidate=None)
    best = min(
        candidates,
        key=lambda item: (
            item.adjusted_p_upper_bound,
            -abs(item.delta),
            item.split_index,
        ),
    )
    return ChangePointResult(detected=True, scanned_splits=scanned, candidate=best)


def _validate_alpha(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
        raise ValueError("alpha must be a finite float in (0, 1)")
    if not 0.0 < value < 1.0:
        raise ValueError("alpha must be in (0, 1)")
