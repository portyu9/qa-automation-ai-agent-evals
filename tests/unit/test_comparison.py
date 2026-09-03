from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.comparison import ComparisonDecision, PairedComparison

P = TrialVerdict.PASS
F = TrialVerdict.FAIL


def test_paired_comparison_detects_clear_candidate_improvement() -> None:
    baseline = [F] * 12 + [P] * 8
    candidate = [P] * 20
    result = PairedComparison.compare(baseline, candidate)
    assert result.candidate_only_pass == 12
    assert result.baseline_only_pass == 0
    assert result.decision is ComparisonDecision.IMPROVED


def test_paired_comparison_does_not_invent_significance() -> None:
    baseline = [P, P, F, F]
    candidate = [P, F, P, F]
    result = PairedComparison.compare(baseline, candidate)
    assert result.absolute_delta == 0.0
    assert result.decision is ComparisonDecision.INCONCLUSIVE


def test_paired_comparison_rejects_unresolved_evidence() -> None:
    with pytest.raises(ValueError, match="resolved PASS/FAIL"):
        PairedComparison.compare([P, TrialVerdict.BLOCKED], [P, F])
