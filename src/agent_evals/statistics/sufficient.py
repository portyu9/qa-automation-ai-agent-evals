"""Cross-language-stable integer sufficient statistics for binary assurance outcomes.

Presentation floats are always derived from these counts; they are never authoritative stored inputs.
Roots bind canonical integer material for integrity only and do not authenticate its producer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.limits import (
    MAX_STATISTICAL_TRIALS,
    validate_materialized_statistical_vector,
)

_BINARY_DOMAIN = b"agent-evals/binary-sufficient-statistics/v1\x00"
_PAIRED_DOMAIN = b"agent-evals/paired-sufficient-statistics/v1\x00"


@dataclass(frozen=True, slots=True)
class BinarySufficientStatistics:
    """Exact count material for one binary reliability campaign."""

    trials: int
    passes: int
    failures: int
    blocked: int
    inconclusive: int

    def __post_init__(self) -> None:
        self.validate()

    @property
    def resolved(self) -> int:
        return self.passes + self.failures

    @property
    def schema_version(self) -> str:
        return "agent-evals/binary-sufficient-statistics/v1"

    @property
    def statistics_root(self) -> str:
        return hashlib.sha256(_BINARY_DOMAIN + self.canonical_json().encode("utf-8")).hexdigest()

    def canonical_json(self) -> str:
        return _canonical_json(
            {
                "blocked": self.blocked,
                "failures": self.failures,
                "inconclusive": self.inconclusive,
                "passes": self.passes,
                "schema_version": self.schema_version,
                "trials": self.trials,
            }
        )

    def validate(self) -> None:
        for name in ("trials", "passes", "failures", "blocked", "inconclusive"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative exact integer")
        if self.trials > MAX_STATISTICAL_TRIALS:
            raise ValueError(
                f"trials exceeds maximum statistical trial count {MAX_STATISTICAL_TRIALS}"
            )
        if self.trials != self.passes + self.failures + self.blocked + self.inconclusive:
            raise ValueError("trials must equal passes + failures + blocked + inconclusive")

    @classmethod
    def from_verdicts(
        cls,
        verdicts: list[TrialVerdict] | tuple[TrialVerdict, ...],
    ) -> BinarySufficientStatistics:
        count = validate_materialized_statistical_vector(
            verdicts,
            label="binary sufficient-statistics verdict vector",
        )
        passes = failures = blocked = inconclusive = 0
        for verdict in verdicts:
            if type(verdict) is not TrialVerdict:
                raise ValueError("verdicts must be exact TrialVerdict members")
            if verdict is TrialVerdict.PASS:
                passes += 1
            elif verdict is TrialVerdict.FAIL:
                failures += 1
            elif verdict is TrialVerdict.BLOCKED:
                blocked += 1
            else:
                inconclusive += 1
        return cls(
            trials=count,
            passes=passes,
            failures=failures,
            blocked=blocked,
            inconclusive=inconclusive,
        )


@dataclass(frozen=True, slots=True)
class PairedSufficientStatistics:
    """Exact paired PASS/FAIL table for candidate-versus-baseline inference."""

    pairs: int
    both_pass: int
    baseline_only_pass: int
    candidate_only_pass: int
    both_fail: int

    def __post_init__(self) -> None:
        self.validate()

    @property
    def schema_version(self) -> str:
        return "agent-evals/paired-sufficient-statistics/v1"

    @property
    def delta_numerator(self) -> int:
        return self.candidate_only_pass - self.baseline_only_pass

    @property
    def statistics_root(self) -> str:
        return hashlib.sha256(_PAIRED_DOMAIN + self.canonical_json().encode("utf-8")).hexdigest()

    def canonical_json(self) -> str:
        return _canonical_json(
            {
                "baseline_only_pass": self.baseline_only_pass,
                "both_fail": self.both_fail,
                "both_pass": self.both_pass,
                "candidate_only_pass": self.candidate_only_pass,
                "pairs": self.pairs,
                "schema_version": self.schema_version,
            }
        )

    def validate(self) -> None:
        for name in (
            "pairs",
            "both_pass",
            "baseline_only_pass",
            "candidate_only_pass",
            "both_fail",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative exact integer")
        if self.pairs == 0:
            raise ValueError("paired sufficient statistics require at least one pair")
        if self.pairs > MAX_STATISTICAL_TRIALS:
            raise ValueError(
                f"pairs exceeds maximum statistical trial count {MAX_STATISTICAL_TRIALS}"
            )
        if self.pairs != (
            self.both_pass
            + self.baseline_only_pass
            + self.candidate_only_pass
            + self.both_fail
        ):
            raise ValueError("paired sufficient-statistics counts must sum to pairs")

    @classmethod
    def from_verdicts(
        cls,
        baseline: list[TrialVerdict] | tuple[TrialVerdict, ...],
        candidate: list[TrialVerdict] | tuple[TrialVerdict, ...],
    ) -> PairedSufficientStatistics:
        baseline_count = validate_materialized_statistical_vector(
            baseline,
            label="paired baseline verdict vector",
        )
        candidate_count = validate_materialized_statistical_vector(
            candidate,
            label="paired candidate verdict vector",
        )
        if baseline_count != candidate_count:
            raise ValueError("paired sufficient statistics require equal-length verdict vectors")
        if baseline_count == 0:
            raise ValueError("paired sufficient statistics require at least one pair")

        both_pass = baseline_only = candidate_only = both_fail = 0
        for baseline_verdict, candidate_verdict in zip(baseline, candidate, strict=True):
            if (
                type(baseline_verdict) is not TrialVerdict
                or type(candidate_verdict) is not TrialVerdict
            ):
                raise ValueError("paired verdicts must be exact TrialVerdict members")
            if baseline_verdict in (TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE) or (
                candidate_verdict in (TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE)
            ):
                raise ValueError(
                    "paired sufficient statistics require resolved PASS/FAIL outcomes; "
                    "BLOCKED and INCONCLUSIVE must remain separate"
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

        return cls(
            pairs=baseline_count,
            both_pass=both_pass,
            baseline_only_pass=baseline_only,
            candidate_only_pass=candidate_only,
            both_fail=both_fail,
        )


def _canonical_json(material: dict[str, object]) -> str:
    return json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        ensure_ascii=True,
    )
