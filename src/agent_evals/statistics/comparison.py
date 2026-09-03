"""Paired baseline/candidate comparison without pretending uncertainty is a verdict."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import comb

from agent_evals.evidence.models import TrialVerdict


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
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be between zero and one")

        unresolved = {
            TrialVerdict.BLOCKED,
            TrialVerdict.INCONCLUSIVE,
        }
        if any(verdict in unresolved for verdict in (*baseline, *candidate)):
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
    """Two-sided exact McNemar/binomial test over discordant paired outcomes."""
    if baseline_only < 0 or candidate_only < 0:
        raise ValueError("discordant counts cannot be negative")
    discordant = baseline_only + candidate_only
    if discordant == 0:
        return 1.0
    tail = min(baseline_only, candidate_only)
    probability = sum(comb(discordant, index) for index in range(tail + 1)) / (2**discordant)
    return min(1.0, 2.0 * probability)
