"""Conservative paired-delta contracts and bounded sample-size/power planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import ceil, isfinite, log, sqrt

from agent_evals.statistics.limits import MAX_STATISTICAL_TRIALS
from agent_evals.statistics.sufficient import PairedSufficientStatistics


class ComparisonGoal(StrEnum):
    SUPERIORITY = "superiority"
    NON_INFERIORITY = "non_inferiority"
    EQUIVALENCE = "equivalence"


@dataclass(frozen=True, slots=True)
class ComparisonContract:
    """Predeclared effect claim over candidate-minus-baseline paired success probability."""

    goal: ComparisonGoal
    margin: float
    alpha: float = 0.05

    def __post_init__(self) -> None:
        if type(self.goal) is not ComparisonGoal:
            raise ValueError("goal must be an exact ComparisonGoal")
        _validate_probability(self.alpha, name="alpha")
        if isinstance(self.margin, bool) or not isinstance(self.margin, float):
            raise ValueError("margin must be an exact finite float")
        if not isfinite(self.margin) or not 0.0 <= self.margin < 1.0:
            raise ValueError("margin must be finite and in [0, 1)")
        if self.goal is ComparisonGoal.EQUIVALENCE and self.margin == 0.0:
            raise ValueError("equivalence requires a positive predeclared margin")


@dataclass(frozen=True, slots=True)
class DeltaInterval:
    lower: float
    upper: float
    alpha: float

    def __post_init__(self) -> None:
        if not -1.0 <= self.lower <= self.upper <= 1.0:
            raise ValueError("delta interval must be ordered inside [-1, 1]")
        _validate_probability(self.alpha, name="alpha")


@dataclass(frozen=True, slots=True)
class PairedDeltaAssessment:
    """Derived inference over one exact paired sufficient-statistics table."""

    statistics: PairedSufficientStatistics
    contract: ComparisonContract

    def __post_init__(self) -> None:
        if type(self.statistics) is not PairedSufficientStatistics:
            raise ValueError("statistics must be exact PairedSufficientStatistics")
        self.statistics.validate()
        if type(self.contract) is not ComparisonContract:
            raise ValueError("contract must be exact ComparisonContract")

    @property
    def empirical_delta(self) -> float:
        return self.statistics.delta_numerator / self.statistics.pairs

    @property
    def interval(self) -> DeltaInterval:
        radius = _paired_hoeffding_radius(self.statistics.pairs, self.contract.alpha)
        return DeltaInterval(
            lower=max(-1.0, self.empirical_delta - radius),
            upper=min(1.0, self.empirical_delta + radius),
            alpha=self.contract.alpha,
        )

    @property
    def established(self) -> bool:
        interval = self.interval
        margin = self.contract.margin
        if self.contract.goal is ComparisonGoal.SUPERIORITY:
            return interval.lower > margin
        if self.contract.goal is ComparisonGoal.NON_INFERIORITY:
            return interval.lower > -margin
        return interval.lower > -margin and interval.upper < margin


@dataclass(frozen=True, slots=True)
class PowerPlan:
    """Conservative fixed-horizon plan under independent bounded paired differences."""

    contract: ComparisonContract
    anticipated_delta: float
    target_power: float
    minimum_pairs: int
    alternative_gap: float
    confidence_radius: float
    sampling_radius: float

    def __post_init__(self) -> None:
        if type(self.contract) is not ComparisonContract:
            raise ValueError("contract must be exact ComparisonContract")
        if isinstance(self.anticipated_delta, bool) or not isinstance(
            self.anticipated_delta, float
        ):
            raise ValueError("anticipated_delta must be an exact finite float")
        if not isfinite(self.anticipated_delta) or not -1.0 <= self.anticipated_delta <= 1.0:
            raise ValueError("anticipated_delta must be finite and in [-1, 1]")
        _validate_probability(self.target_power, name="target_power")
        if (
            type(self.minimum_pairs) is not int
            or not 1 <= self.minimum_pairs <= MAX_STATISTICAL_TRIALS
        ):
            raise ValueError("minimum_pairs is outside the supported statistical work envelope")
        for name in ("alternative_gap", "confidence_radius", "sampling_radius"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
                raise ValueError(f"{name} must be a finite float")
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
        expected_gap = _alternative_gap(self.contract, self.anticipated_delta)
        if self.alternative_gap != expected_gap:
            raise ValueError(
                "alternative_gap does not recompute from contract and anticipated_delta"
            )
        expected_confidence = _paired_hoeffding_radius(
            self.minimum_pairs,
            self.contract.alpha,
        )
        if self.confidence_radius != expected_confidence:
            raise ValueError("confidence_radius does not recompute from minimum_pairs and alpha")
        expected_sampling = _paired_hoeffding_radius(
            self.minimum_pairs,
            1.0 - self.target_power,
        )
        if self.sampling_radius != expected_sampling:
            raise ValueError("sampling_radius does not recompute from minimum_pairs and power")
        if self.confidence_radius + self.sampling_radius > self.alternative_gap:
            raise ValueError("minimum_pairs does not satisfy the declared power guarantee")


def plan_paired_power(
    contract: ComparisonContract,
    *,
    anticipated_delta: float,
    target_power: float = 0.80,
) -> PowerPlan:
    """Return a fixed-horizon pair count with a distribution-free power lower bound.

    If the true paired mean equals the anticipated delta, then under independent paired units the
    probability that the predeclared confidence interval establishes the contract is at least the
    requested target power. The statement is conditional on those assumptions.
    """

    if type(contract) is not ComparisonContract:
        raise ValueError("contract must be an exact ComparisonContract")
    if isinstance(anticipated_delta, bool) or not isinstance(anticipated_delta, float):
        raise ValueError("anticipated_delta must be an exact finite float")
    if not isfinite(anticipated_delta) or not -1.0 <= anticipated_delta <= 1.0:
        raise ValueError("anticipated_delta must be finite and in [-1, 1]")
    _validate_probability(target_power, name="target_power")

    gap = _alternative_gap(contract, anticipated_delta)
    beta = 1.0 - target_power
    alpha_factor = sqrt(2.0 * log(2.0 / contract.alpha))
    beta_factor = sqrt(2.0 * log(2.0 / beta))
    required = ceil(((alpha_factor + beta_factor) / gap) ** 2)
    if required > MAX_STATISTICAL_TRIALS:
        raise ValueError(
            "requested power plan exceeds the maximum supported statistical trial count "
            f"{MAX_STATISTICAL_TRIALS}"
        )
    required = max(1, required)
    return PowerPlan(
        contract=contract,
        anticipated_delta=anticipated_delta,
        target_power=target_power,
        minimum_pairs=required,
        alternative_gap=gap,
        confidence_radius=_paired_hoeffding_radius(required, contract.alpha),
        sampling_radius=_paired_hoeffding_radius(required, beta),
    )


def _alternative_gap(contract: ComparisonContract, anticipated_delta: float) -> float:
    margin = contract.margin
    if contract.goal is ComparisonGoal.SUPERIORITY:
        gap = anticipated_delta - margin
    elif contract.goal is ComparisonGoal.NON_INFERIORITY:
        gap = anticipated_delta + margin
    else:
        gap = margin - abs(anticipated_delta)
    if gap <= 0.0:
        raise ValueError("anticipated_delta does not lie inside the contract alternative region")
    return gap


def _paired_hoeffding_radius(pairs: int, alpha: float) -> float:
    if type(pairs) is not int or not 1 <= pairs <= MAX_STATISTICAL_TRIALS:
        raise ValueError("pairs is outside the supported statistical work envelope")
    _validate_probability(alpha, name="alpha")
    return sqrt(2.0 * log(2.0 / alpha) / pairs)


def _validate_probability(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
        raise ValueError(f"{name} must be a finite float in (0, 1)")
    if not 0.0 < value < 1.0:
        raise ValueError(f"{name} must be in (0, 1)")
