from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.statistics.reliability import ReliabilityReport


def test_reliability_preserves_uncertainty_and_two_k_semantics() -> None:
    report = ReliabilityReport.from_verdicts(
        [TrialVerdict.PASS, TrialVerdict.PASS, TrialVerdict.FAIL, TrialVerdict.PASS],
        k=3,
    )
    assert report.success_rate == pytest.approx(0.75)
    assert report.pass_at_k == pytest.approx(1 - 0.25**3)
    assert report.pass_power_k == pytest.approx(0.75**3)
    assert report.wilson_low < report.success_rate < report.wilson_high


def test_critical_violation_cannot_be_compensated_by_perfect_success_rate() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS] * 100)
    gate = ReleaseGate(
        ReleasePolicy(min_trials=20, min_success_rate=0.95, min_wilson_low=0.80)
    )
    assert gate.decide(report, critical_violations=1).decision is GateDecision.REJECT


def test_small_sample_is_inconclusive_not_green() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS] * 3)
    gate = ReleaseGate(ReleasePolicy(min_trials=20, min_success_rate=0.95, min_wilson_low=0.50))
    assert gate.decide(report, critical_violations=0).decision is GateDecision.INCONCLUSIVE
