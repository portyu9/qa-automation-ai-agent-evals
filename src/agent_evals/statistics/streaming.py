"""Streaming exact sufficient-statistics aggregation for very large campaigns.

These aggregators preserve the repository's integer sufficient-statistics contracts while avoiding
materialization of verdict vectors.  They do not infer independence, sampling quality, or release
authority; callers still need the existing sampling/provenance and release-policy layers.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.limits import MAX_STATISTICAL_TRIALS
from agent_evals.statistics.sufficient import (
    BinarySufficientStatistics,
    PairedSufficientStatistics,
)


@dataclass(slots=True)
class StreamingBinaryAggregator:
    """Incrementally derive the exact BinarySufficientStatistics contract."""

    trials: int = 0
    passes: int = 0
    failures: int = 0
    blocked: int = 0
    inconclusive: int = 0

    def update(self, verdict: TrialVerdict) -> None:
        if type(verdict) is not TrialVerdict:
            raise ValueError("streaming verdict must be an exact TrialVerdict")
        if self.trials >= MAX_STATISTICAL_TRIALS:
            raise ValueError(
                f"streaming aggregate exceeds maximum statistical trial count "
                f"{MAX_STATISTICAL_TRIALS}"
            )
        self.trials += 1
        if verdict is TrialVerdict.PASS:
            self.passes += 1
        elif verdict is TrialVerdict.FAIL:
            self.failures += 1
        elif verdict is TrialVerdict.BLOCKED:
            self.blocked += 1
        else:
            self.inconclusive += 1

    def merge(self, other: StreamingBinaryAggregator) -> None:
        if type(other) is not StreamingBinaryAggregator:
            raise TypeError("streaming binary merge requires an exact aggregator")
        combined = self.trials + other.trials
        if combined > MAX_STATISTICAL_TRIALS:
            raise ValueError(
                f"merged aggregate exceeds maximum statistical trial count "
                f"{MAX_STATISTICAL_TRIALS}"
            )
        self.trials = combined
        self.passes += other.passes
        self.failures += other.failures
        self.blocked += other.blocked
        self.inconclusive += other.inconclusive

    def snapshot(self) -> BinarySufficientStatistics:
        return BinarySufficientStatistics(
            trials=self.trials,
            passes=self.passes,
            failures=self.failures,
            blocked=self.blocked,
            inconclusive=self.inconclusive,
        )


@dataclass(slots=True)
class StreamingPairedAggregator:
    """Incrementally derive exact paired PASS/FAIL counts without outcome coercion."""

    pairs: int = 0
    both_pass: int = 0
    baseline_only_pass: int = 0
    candidate_only_pass: int = 0
    both_fail: int = 0

    def update(self, baseline: TrialVerdict, candidate: TrialVerdict) -> None:
        if type(baseline) is not TrialVerdict or type(candidate) is not TrialVerdict:
            raise ValueError("streaming paired verdicts must be exact TrialVerdict members")
        if baseline in (TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE) or candidate in (
            TrialVerdict.BLOCKED,
            TrialVerdict.INCONCLUSIVE,
        ):
            raise ValueError(
                "streaming paired aggregation requires resolved PASS/FAIL outcomes; "
                "BLOCKED and INCONCLUSIVE remain separate"
            )
        if self.pairs >= MAX_STATISTICAL_TRIALS:
            raise ValueError(
                f"streaming paired aggregate exceeds maximum statistical trial count "
                f"{MAX_STATISTICAL_TRIALS}"
            )

        self.pairs += 1
        baseline_pass = baseline is TrialVerdict.PASS
        candidate_pass = candidate is TrialVerdict.PASS
        if baseline_pass and candidate_pass:
            self.both_pass += 1
        elif baseline_pass:
            self.baseline_only_pass += 1
        elif candidate_pass:
            self.candidate_only_pass += 1
        else:
            self.both_fail += 1

    def merge(self, other: StreamingPairedAggregator) -> None:
        if type(other) is not StreamingPairedAggregator:
            raise TypeError("streaming paired merge requires an exact aggregator")
        combined = self.pairs + other.pairs
        if combined > MAX_STATISTICAL_TRIALS:
            raise ValueError(
                f"merged paired aggregate exceeds maximum statistical trial count "
                f"{MAX_STATISTICAL_TRIALS}"
            )
        self.pairs = combined
        self.both_pass += other.both_pass
        self.baseline_only_pass += other.baseline_only_pass
        self.candidate_only_pass += other.candidate_only_pass
        self.both_fail += other.both_fail

    def snapshot(self) -> PairedSufficientStatistics:
        return PairedSufficientStatistics(
            pairs=self.pairs,
            both_pass=self.both_pass,
            baseline_only_pass=self.baseline_only_pass,
            candidate_only_pass=self.candidate_only_pass,
            both_fail=self.both_fail,
        )
