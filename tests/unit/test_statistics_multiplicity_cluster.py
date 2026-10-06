from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.cluster import ClusterAwareEstimate, ClusterCounts
from agent_evals.statistics.multiplicity import (
    HypothesisPValue,
    MultiplicityMethod,
    adjust_p_values,
)


def test_holm_fwer_known_vector_and_order_restoration() -> None:
    adjusted = adjust_p_values(
        [
            HypothesisPValue("late", 0.04),
            HypothesisPValue("strong", 0.01),
            HypothesisPValue("weak", 0.03),
        ],
        method=MultiplicityMethod.HOLM_FWER,
        alpha=0.05,
    )

    by_id = {item.hypothesis_id: item for item in adjusted}
    assert by_id["strong"].adjusted_p_value == pytest.approx(0.03)
    assert by_id["weak"].adjusted_p_value == pytest.approx(0.06)
    assert by_id["late"].adjusted_p_value == pytest.approx(0.06)
    assert by_id["strong"].rejected is True
    assert by_id["weak"].rejected is False


def test_benjamini_hochberg_known_vector() -> None:
    adjusted = adjust_p_values(
        [
            HypothesisPValue("h1", 0.01),
            HypothesisPValue("h2", 0.02),
            HypothesisPValue("h3", 0.20),
            HypothesisPValue("h4", 0.80),
        ],
        method=MultiplicityMethod.BENJAMINI_HOCHBERG_FDR,
        alpha=0.05,
    )

    assert [item.adjusted_p_value for item in adjusted] == pytest.approx(
        [0.04, 0.04, 0.26666666666666666, 0.8]
    )
    assert [item.rejected for item in adjusted] == [True, True, False, False]


def test_multiplicity_rejects_duplicate_hypothesis_identity() -> None:
    with pytest.raises(ValueError, match="unique"):
        adjust_p_values(
            [
                HypothesisPValue("same", 0.01),
                HypothesisPValue("same", 0.02),
            ],
            method=MultiplicityMethod.HOLM_FWER,
        )


def test_cluster_estimate_does_not_pseudo_replicate_large_cluster() -> None:
    dominant = ClusterCounts.from_verdicts(
        "shared-prompt-a",
        tuple(TrialVerdict.PASS for _ in range(1_000)),
    )
    small = ClusterCounts.from_verdicts(
        "shared-prompt-b",
        (TrialVerdict.FAIL,),
    )
    estimate = ClusterAwareEstimate((dominant, small), alpha=0.05)

    assert estimate.equal_cluster_mean == pytest.approx(0.5)
    assert estimate.total_resolved == 1_001
    assert estimate.cluster_count == 2


def test_cluster_estimate_retains_unresolved_counts_without_coercion() -> None:
    cluster = ClusterCounts.from_verdicts(
        "task-family",
        (
            TrialVerdict.PASS,
            TrialVerdict.FAIL,
            TrialVerdict.BLOCKED,
            TrialVerdict.INCONCLUSIVE,
        ),
    )
    estimate = ClusterAwareEstimate((cluster,), alpha=0.05)

    assert estimate.equal_cluster_mean == pytest.approx(0.5)
    assert estimate.blocked == 1
    assert estimate.inconclusive == 1
    assert estimate.total_resolved == 2


def test_cluster_without_resolved_outcome_is_not_silently_dropped() -> None:
    with pytest.raises(ValueError, match="at least one resolved"):
        ClusterCounts.from_verdicts(
            "unresolved-only",
            (TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE),
        )
