from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.statistics.reliability import ReliabilityReport


def test_reliability_preserves_uncertainty_and_two_k_semantics() -> None:
    report = ReliabilityReport.from_verdicts(
        [TrialVerdict.PASS, TrialVerdict.PASS, TrialVerdict.FAIL, TrialVerdict.PASS], k=3
    )
    assert report.resolved_trials == 4
    assert report.success_rate == pytest.approx(0.75)
    assert report.pass_at_k == pytest.approx(1 - 0.25**3)
    assert report.pass_power_k == pytest.approx(0.75**3)
    assert report.wilson_low < report.success_rate < report.wilson_high


def test_reliability_rejects_non_finite_confidence_contracts() -> None:
    for confidence_z in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0):
        with pytest.raises(ValueError, match="confidence_z must be finite and positive"):
            ReliabilityReport.from_verdicts(
                [TrialVerdict.PASS, TrialVerdict.FAIL], confidence_z=confidence_z
            )


def test_blocked_trials_are_not_relabelled_as_behavioral_failures() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS, TrialVerdict.BLOCKED])
    assert report.resolved_trials == 1
    assert report.success_rate == 1.0
    assert report.blocked == 1


def test_all_unresolved_trials_retain_full_statistical_uncertainty() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE])
    assert report.resolved_trials == 0
    assert report.success_rate == 0.0
    assert (report.wilson_low, report.wilson_high) == (0.0, 1.0)


def test_critical_violation_cannot_be_compensated_by_perfect_success_rate() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS] * 100)
    gate = ReleaseGate(
        ReleasePolicy(min_resolved_trials=20, min_success_rate=0.95, min_wilson_low=0.80)
    )
    assert gate.decide(report, critical_violations=1).decision is GateDecision.REJECT


def test_release_gate_rejects_invalid_critical_violation_counts() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS] * 20)
    gate = ReleaseGate(ReleasePolicy(min_wilson_low=0.0))
    for invalid in (-1, True, 1.5):
        with pytest.raises(ValueError, match="critical_violations must be a non-negative integer"):
            gate.decide(report, critical_violations=invalid)  # type: ignore[arg-type]


def test_small_resolved_sample_is_inconclusive_not_green() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS] * 3)
    gate = ReleaseGate(
        ReleasePolicy(min_resolved_trials=20, min_success_rate=0.95, min_wilson_low=0.50)
    )
    assert gate.decide(report, critical_violations=0).decision is GateDecision.INCONCLUSIVE


def test_blocked_attempts_do_not_satisfy_minimum_resolved_sample() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS] + [TrialVerdict.BLOCKED] * 19)
    gate = ReleaseGate(
        ReleasePolicy(
            min_resolved_trials=20,
            min_success_rate=0.95,
            min_wilson_low=0.0,
            max_blocked_trials=20,
        )
    )
    assert gate.decide(report, critical_violations=0).decision is GateDecision.INCONCLUSIVE


def test_fully_blocked_session_is_inconclusive_not_behavioral_reject() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.BLOCKED] * 20)
    gate = ReleaseGate(ReleasePolicy(min_resolved_trials=20, max_blocked_trials=0))
    result = gate.decide(report, critical_violations=0)
    assert result.decision is GateDecision.INCONCLUSIVE
    assert any("blocked trials" in reason for reason in result.reasons)
