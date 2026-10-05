from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.inference import (
    ComparisonContract,
    ComparisonGoal,
    PairedDeltaAssessment,
    plan_paired_power,
)
from agent_evals.statistics.sufficient import (
    BinarySufficientStatistics,
    PairedSufficientStatistics,
)


def test_binary_sufficient_statistics_are_integer_only_and_canonical() -> None:
    stats = BinarySufficientStatistics.from_verdicts(
        (
            TrialVerdict.PASS,
            TrialVerdict.FAIL,
            TrialVerdict.BLOCKED,
            TrialVerdict.INCONCLUSIVE,
        )
    )

    assert stats.canonical_json() == (
        '{"blocked":1,"failures":1,"inconclusive":1,"passes":1,'
        '"schema_version":"agent-evals/binary-sufficient-statistics/v1","trials":4}'
    )
    assert len(stats.statistics_root) == 64
    assert stats.resolved == 2


def test_paired_sufficient_statistics_reject_unresolved_outcomes() -> None:
    with pytest.raises(ValueError, match="BLOCKED and INCONCLUSIVE"):
        PairedSufficientStatistics.from_verdicts(
            (TrialVerdict.PASS, TrialVerdict.FAIL),
            (TrialVerdict.PASS, TrialVerdict.BLOCKED),
        )


def test_paired_sufficient_statistics_derive_delta_without_storing_float_authority() -> None:
    stats = PairedSufficientStatistics(
        pairs=100,
        both_pass=50,
        baseline_only_pass=10,
        candidate_only_pass=30,
        both_fail=10,
    )

    assert stats.delta_numerator == 20
    assert '"delta"' not in stats.canonical_json()
    assert len(stats.statistics_root) == 64


def test_superiority_contract_uses_predeclared_margin_and_interval() -> None:
    stats = PairedSufficientStatistics(
        pairs=1_000,
        both_pass=700,
        baseline_only_pass=20,
        candidate_only_pass=200,
        both_fail=80,
    )
    assessment = PairedDeltaAssessment(
        statistics=stats,
        contract=ComparisonContract(
            goal=ComparisonGoal.SUPERIORITY,
            margin=0.05,
            alpha=0.05,
        ),
    )

    assert assessment.empirical_delta == pytest.approx(0.18)
    assert assessment.interval.lower > 0.05
    assert assessment.established is True


def test_non_inferiority_and_equivalence_are_distinct_contracts() -> None:
    stats = PairedSufficientStatistics(
        pairs=5_000,
        both_pass=4_500,
        baseline_only_pass=100,
        candidate_only_pass=100,
        both_fail=300,
    )
    non_inferiority = PairedDeltaAssessment(
        statistics=stats,
        contract=ComparisonContract(
            goal=ComparisonGoal.NON_INFERIORITY,
            margin=0.10,
            alpha=0.05,
        ),
    )
    equivalence = PairedDeltaAssessment(
        statistics=stats,
        contract=ComparisonContract(
            goal=ComparisonGoal.EQUIVALENCE,
            margin=0.10,
            alpha=0.05,
        ),
    )

    assert non_inferiority.established is True
    assert equivalence.established is True


def test_small_sample_does_not_establish_raw_positive_delta() -> None:
    stats = PairedSufficientStatistics(
        pairs=10,
        both_pass=4,
        baseline_only_pass=1,
        candidate_only_pass=3,
        both_fail=2,
    )
    assessment = PairedDeltaAssessment(
        statistics=stats,
        contract=ComparisonContract(
            goal=ComparisonGoal.SUPERIORITY,
            margin=0.0,
            alpha=0.05,
        ),
    )

    assert assessment.empirical_delta > 0.0
    assert assessment.established is False


def test_power_plan_is_conservative_and_predeclared() -> None:
    contract = ComparisonContract(
        goal=ComparisonGoal.NON_INFERIORITY,
        margin=0.10,
        alpha=0.05,
    )
    plan = plan_paired_power(
        contract,
        anticipated_delta=0.05,
        target_power=0.80,
    )

    assert plan.minimum_pairs > 0
    assert plan.confidence_radius + plan.sampling_radius <= plan.alternative_gap
    assert plan.alternative_gap == pytest.approx(0.15)


def test_power_plan_rejects_alternative_outside_contract_region() -> None:
    contract = ComparisonContract(
        goal=ComparisonGoal.SUPERIORITY,
        margin=0.10,
        alpha=0.05,
    )

    with pytest.raises(ValueError, match="alternative region"):
        plan_paired_power(contract, anticipated_delta=0.05)


def test_equivalence_requires_positive_margin() -> None:
    with pytest.raises(ValueError, match="positive"):
        ComparisonContract(
            goal=ComparisonGoal.EQUIVALENCE,
            margin=0.0,
            alpha=0.05,
        )
