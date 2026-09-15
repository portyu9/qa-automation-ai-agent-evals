"""Paired baseline/candidate comparison without pretending uncertainty is a verdict."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import exp, isfinite, lgamma, log

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.limits import MAX_STATISTICAL_TRIALS

_LOG_TWO = log(2.0)


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
        if len(baseline) != len(candidate):
            raise ValueError("paired comparison requires equal-length trial vectors")
        if not baseline:
            raise ValueError("paired comparison requires at least one pair")
        if len(baseline) > MAX_STATISTICAL_TRIALS:
            raise ValueError(
                f"paired comparison supports at most {MAX_STATISTICAL_TRIALS} trial pairs"
            )
        if isinstance(alpha, bool) or not isinstance(alpha, float) or not isfinite(alpha):
            raise ValueError("alpha must be a finite float between zero and one")
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be between zero and one")

        if any(type(verdict) is not TrialVerdict for verdict in baseline) or any(
            type(verdict) is not TrialVerdict for verdict in candidate
        ):
            raise ValueError("paired comparison verdicts must be exact TrialVerdict members")

        unresolved = {
            TrialVerdict.BLOCKED,
            TrialVerdict.INCONCLUSIVE,
        }
        if any(verdict in unresolved for verdict in baseline) or any(
            verdict in unresolved for verdict in candidate
        ):
            raise ValueError(
                "paired behavioral comparison requires resolved PASS/FAIL outcomes; "
                "BLOCKED or INCONCLUSIVE evidence must be resolved separately"
            )

        both_pass = baseline_only = candidate_only = both_fail = 0
        for baseline_verdict, candidate_verdict in zip(baseline, candidate, strict=True):
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

        pairs = len(baseline)
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
    """Two-sided exact McNemar/binomial test over discordant paired outcomes.

    The binomial tail is evaluated with bounded-size floating-point recurrence rather than
    constructing ``comb(n, k)`` and ``2**n`` integers. The statistical definition is unchanged;
    only the arithmetic representation is bounded.
    """
    if isinstance(baseline_only, bool) or not isinstance(baseline_only, int):
        raise ValueError("discordant counts must be integers")
    if isinstance(candidate_only, bool) or not isinstance(candidate_only, int):
        raise ValueError("discordant counts must be integers")
    if baseline_only < 0 or candidate_only < 0:
        raise ValueError("discordant counts cannot be negative")
    discordant = baseline_only + candidate_only
    if discordant > MAX_STATISTICAL_TRIALS:
        raise ValueError(
            f"discordant count cannot exceed {MAX_STATISTICAL_TRIALS} supported trial pairs"
        )
    if discordant == 0:
        return 1.0
    tail = min(baseline_only, candidate_only)
    probability = _binomial_half_lower_tail(discordant, tail)
    return min(1.0, 2.0 * probability)


def _binomial_half_lower_tail(trials: int, tail: int) -> float:
    """Return ``P[X <= tail]`` for ``X ~ Binomial(trials, 0.5)`` without big integers."""
    log_mass = (
        lgamma(trials + 1)
        - lgamma(tail + 1)
        - lgamma(trials - tail + 1)
        - trials * _LOG_TWO
    )
    mass = exp(log_mass)
    probability = mass
    for index in range(tail, 0, -1):
        mass *= index / (trials - index + 1)
        probability += mass
    return min(1.0, probability)
