"""Paired baseline/candidate comparison without pretending uncertainty is a verdict."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import comb, fsum, isfinite

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.limits import (
    MAX_STATISTICAL_TRIALS,
    validate_materialized_statistical_vector,
)


class ComparisonDecision(StrEnum):
    IMPROVED = "improved"
    REGRESSED = "regressed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class PairedComparison:
    pairs: int
    both_pass: int
    baseline_only_pass: int
    candidate_only_pass: int
    both_fail: int
    baseline_success_rate: float
    candidate_success_rate: float
    absolute_delta: float
    exact_p_value: float
    decision: ComparisonDecision

    @classmethod
    def compare(
        cls,
        baseline: list[TrialVerdict] | tuple[TrialVerdict, ...],
        candidate: list[TrialVerdict] | tuple[TrialVerdict, ...],
        *,
        alpha: float = 0.05,
    ) -> PairedComparison:
        baseline_pairs = validate_materialized_statistical_vector(
            baseline,
            label="baseline verdict vector",
        )
        candidate_pairs = validate_materialized_statistical_vector(
            candidate,
            label="candidate verdict vector",
        )
        if baseline_pairs != candidate_pairs:
            raise ValueError("paired comparison requires equal-length trial vectors")
        if baseline_pairs == 0:
            raise ValueError("paired comparison requires at least one pair")
        if isinstance(alpha, bool) or not isinstance(alpha, float) or not isfinite(alpha):
            raise ValueError("alpha must be a finite float between zero and one")
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be between zero and one")

        both_pass = baseline_only = candidate_only = both_fail = 0
        for baseline_verdict, candidate_verdict in zip(baseline, candidate, strict=True):
            if (
                type(baseline_verdict) is not TrialVerdict
                or type(candidate_verdict) is not TrialVerdict
            ):
                raise ValueError("paired comparison verdicts must be exact TrialVerdict members")
            if baseline_verdict in (TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE) or (
                candidate_verdict in (TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE)
            ):
                raise ValueError(
                    "paired behavioral comparison requires resolved PASS/FAIL outcomes; "
                    "BLOCKED or INCONCLUSIVE evidence must be resolved separately"
                )

            baseline_pass = baseline_verdict is TrialVerdict.PASS
            candidate_pass = candidate_verdict is TrialVerdict.PASS
            if baseline_pass and candidate_pass:
                both_pass += 1
            elif baseline_pass:
                baseline_only += 1
            elif candidate_pass:
                candidate_only += 1
            else:
                both_fail += 1

        pairs = baseline_pairs
        baseline_rate = (both_pass + baseline_only) / pairs
        candidate_rate = (both_pass + candidate_only) / pairs
        p_value = _exact_mcnemar_p_value(baseline_only, candidate_only)

        if p_value <= alpha and candidate_only > baseline_only:
            decision = ComparisonDecision.IMPROVED
        elif p_value <= alpha and baseline_only > candidate_only:
            decision = ComparisonDecision.REGRESSED
        else:
            decision = ComparisonDecision.INCONCLUSIVE

        return cls(
            pairs=pairs,
            both_pass=both_pass,
            baseline_only_pass=baseline_only,
            candidate_only_pass=candidate_only,
            both_fail=both_fail,
            baseline_success_rate=baseline_rate,
            candidate_success_rate=candidate_rate,
            absolute_delta=candidate_rate - baseline_rate,
            exact_p_value=p_value,
            decision=decision,
        )


def _exact_mcnemar_p_value(baseline_only: int, candidate_only: int) -> float:
    """Two-sided exact McNemar/binomial test over bounded discordant paired outcomes."""
    if type(baseline_only) is not int or type(candidate_only) is not int:
        raise ValueError("discordant counts must be integers")
    if baseline_only < 0 or candidate_only < 0:
        raise ValueError("discordant counts cannot be negative")
    discordant = baseline_only + candidate_only
    if discordant > MAX_STATISTICAL_TRIALS:
        raise ValueError(
            f"discordant counts exceed maximum statistical trial count {MAX_STATISTICAL_TRIALS}"
        )
    if discordant == 0:
        return 1.0

    tail = min(baseline_only, candidate_only)
    probability = fsum(_lower_binomial_tail_terms(discordant, tail))
    return min(1.0, 2.0 * probability)


def _lower_binomial_tail_terms(trials: int, tail: int):  # type: ignore[no-untyped-def]
    """Yield Binomial(n, 0.5) mass from ``tail`` down to zero with one ``comb`` call."""
    term = comb(trials, tail) / (1 << trials)
    yield term
    for index in range(tail, 0, -1):
        term *= index / (trials - index + 1)
        yield term
