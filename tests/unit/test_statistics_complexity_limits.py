from __future__ import annotations

from math import comb, isfinite

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.comparison import PairedComparison, _exact_mcnemar_p_value
from agent_evals.statistics.limits import MAX_RELIABILITY_K, MAX_STATISTICAL_TRIALS
from agent_evals.statistics.reliability import ReliabilityReport


def _reference_exact_mcnemar(baseline_only: int, candidate_only: int) -> float:
    discordant = baseline_only + candidate_only
    if discordant == 0:
        return 1.0
    tail = min(baseline_only, candidate_only)
    favorable_mass = sum(comb(discordant, index) for index in range(tail + 1))
    return min(1.0, 2.0 * (favorable_mass / (1 << discordant)))


@pytest.mark.parametrize(
    ("baseline_only", "candidate_only"),
    [(0, 1), (1, 1), (2, 5), (7, 3), (12, 12), (2, 25), (30, 10)],
)
def test_stable_mcnemar_matches_exact_integer_reference(
    baseline_only: int,
    candidate_only: int,
) -> None:
    observed = _exact_mcnemar_p_value(baseline_only, candidate_only)
    expected = _reference_exact_mcnemar(baseline_only, candidate_only)

    assert observed == pytest.approx(expected, rel=1e-14, abs=0.0)


def test_mcnemar_balanced_tail_is_finite_at_statistical_ceiling() -> None:
    half = MAX_STATISTICAL_TRIALS // 2

    p_value = _exact_mcnemar_p_value(half, half)

    assert isfinite(p_value)
    assert p_value == 1.0


def test_mcnemar_rejects_discordance_over_statistical_ceiling() -> None:
    with pytest.raises(ValueError, match="maximum statistical trial count"):
        _exact_mcnemar_p_value(MAX_STATISTICAL_TRIALS + 1, 0)


def test_paired_comparison_accepts_exact_trial_ceiling() -> None:
    verdicts = [TrialVerdict.PASS] * MAX_STATISTICAL_TRIALS

    comparison = PairedComparison.compare(verdicts, verdicts)

    assert comparison.pairs == MAX_STATISTICAL_TRIALS
    assert comparison.both_pass == MAX_STATISTICAL_TRIALS
    assert comparison.exact_p_value == 1.0


def test_paired_comparison_rejects_over_limit_before_verdict_scan() -> None:
    verdicts = [object()] * (MAX_STATISTICAL_TRIALS + 1)

    with pytest.raises(ValueError, match="maximum statistical trial count"):
        PairedComparison.compare(  # type: ignore[arg-type]
            verdicts,
            verdicts,
        )


def test_reliability_accepts_exact_trial_and_retry_ceilings() -> None:
    verdicts = [TrialVerdict.PASS] * MAX_STATISTICAL_TRIALS

    report = ReliabilityReport.from_verdicts(verdicts, k=MAX_RELIABILITY_K)

    assert report.trials == MAX_STATISTICAL_TRIALS
    assert report.k == MAX_RELIABILITY_K
    assert report.pass_at_k == 1.0
    assert report.pass_power_k == 1.0


def test_reliability_rejects_over_limit_before_verdict_scan() -> None:
    verdicts = [object()] * (MAX_STATISTICAL_TRIALS + 1)

    with pytest.raises(ValueError, match="maximum statistical trial count"):
        ReliabilityReport.from_verdicts(verdicts)  # type: ignore[arg-type]


def test_reliability_rejects_extreme_k_before_float_exponentiation() -> None:
    extreme_k = 1 << 10_000

    with pytest.raises(ValueError, match="maximum reliability retry depth"):
        ReliabilityReport.from_verdicts(
            [TrialVerdict.PASS, TrialVerdict.FAIL],
            k=extreme_k,
        )


class _HostileList(list[TrialVerdict]):
    def __len__(self) -> int:
        raise AssertionError("hostile list length must not execute")


def test_statistical_entry_points_reject_container_subclasses_before_len() -> None:
    hostile = _HostileList([TrialVerdict.PASS])

    with pytest.raises(ValueError, match="exact list or tuple"):
        ReliabilityReport.from_verdicts(hostile)
    with pytest.raises(ValueError, match="exact list or tuple"):
        PairedComparison.compare(hostile, [TrialVerdict.PASS])
