from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.streaming import (
    StreamingBinaryAggregator,
    StreamingPairedAggregator,
)
from agent_evals.statistics.sufficient import (
    BinarySufficientStatistics,
    PairedSufficientStatistics,
)


def test_streaming_binary_matches_materialized_sufficient_statistics() -> None:
    verdicts = [
        TrialVerdict.PASS,
        TrialVerdict.FAIL,
        TrialVerdict.BLOCKED,
        TrialVerdict.INCONCLUSIVE,
        TrialVerdict.PASS,
    ]
    aggregator = StreamingBinaryAggregator()
    for verdict in verdicts:
        aggregator.update(verdict)

    expected = BinarySufficientStatistics.from_verdicts(verdicts)
    assert aggregator.snapshot() == expected
    assert aggregator.snapshot().statistics_root == expected.statistics_root


def test_streaming_binary_partition_merge_is_exact_and_order_independent() -> None:
    left = StreamingBinaryAggregator()
    right = StreamingBinaryAggregator()
    for verdict in (TrialVerdict.PASS, TrialVerdict.FAIL, TrialVerdict.PASS):
        left.update(verdict)
    for verdict in (TrialVerdict.BLOCKED, TrialVerdict.PASS, TrialVerdict.INCONCLUSIVE):
        right.update(verdict)

    left.merge(right)

    assert left.snapshot() == BinarySufficientStatistics(
        trials=6,
        passes=3,
        failures=1,
        blocked=1,
        inconclusive=1,
    )


@pytest.mark.parametrize("trial_count", [10_000, 100_000])
def test_streaming_binary_scales_to_large_campaigns_without_verdict_vector(
    trial_count: int,
) -> None:
    aggregator = StreamingBinaryAggregator()
    for index in range(trial_count):
        aggregator.update(TrialVerdict.PASS if index % 5 else TrialVerdict.FAIL)

    snapshot = aggregator.snapshot()
    expected_failures = (trial_count + 4) // 5
    assert snapshot.trials == trial_count
    assert snapshot.failures == expected_failures
    assert snapshot.passes == trial_count - expected_failures
    assert snapshot.blocked == 0
    assert snapshot.inconclusive == 0
    assert len(snapshot.statistics_root) == 64


def test_streaming_paired_matches_materialized_exact_table() -> None:
    baseline = [
        TrialVerdict.PASS,
        TrialVerdict.PASS,
        TrialVerdict.FAIL,
        TrialVerdict.FAIL,
    ]
    candidate = [
        TrialVerdict.PASS,
        TrialVerdict.FAIL,
        TrialVerdict.PASS,
        TrialVerdict.FAIL,
    ]
    aggregator = StreamingPairedAggregator()
    for baseline_verdict, candidate_verdict in zip(baseline, candidate, strict=True):
        aggregator.update(baseline_verdict, candidate_verdict)

    expected = PairedSufficientStatistics.from_verdicts(baseline, candidate)
    assert aggregator.snapshot() == expected
    assert aggregator.snapshot().statistics_root == expected.statistics_root


@pytest.mark.parametrize("unresolved", [TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE])
def test_streaming_paired_never_flattens_unresolved_outcomes(
    unresolved: TrialVerdict,
) -> None:
    aggregator = StreamingPairedAggregator()

    with pytest.raises(ValueError, match="remain separate"):
        aggregator.update(unresolved, TrialVerdict.FAIL)
