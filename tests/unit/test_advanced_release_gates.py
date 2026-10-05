from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.gates.advanced import (
    OperationalReleaseGate,
    OperationalTailPolicy,
    RiskFamilyResult,
    SliceEvidence,
    SliceGateResult,
    SliceReleaseGate,
)
from agent_evals.gates.release import GateDecision, ReleasePolicy
from agent_evals.statistics.operational import (
    OperationalInclusion,
    OperationalObservation,
    OperationalSummary,
)
from agent_evals.statistics.reliability import ReliabilityReport


def _report(*verdicts: TrialVerdict) -> ReliabilityReport:
    return ReliabilityReport.from_verdicts(list(verdicts))


def test_operational_summary_uses_deterministic_nearest_rank_tails() -> None:
    observations = tuple(
        OperationalObservation(
            verdict=TrialVerdict.PASS,
            latency_ms=float(index),
            cost_usd=float(index) / 1000.0,
            tool_calls=index,
            retries=index // 10,
        )
        for index in range(1, 21)
    )
    summary = OperationalSummary(
        observations=observations,
        inclusion=OperationalInclusion.ALL_ATTEMPTS,
    )

    assert summary.latency_p50_ms == 10.0
    assert summary.latency_p95_ms == 19.0
    assert summary.latency_p99_ms == 20.0
    assert summary.tool_calls_p99 == 20
    assert summary.retries_p99 == 2


def test_operational_gate_rejects_resolved_tail_violation() -> None:
    observations = tuple(
        OperationalObservation(
            verdict=TrialVerdict.PASS,
            latency_ms=float(index),
            cost_usd=0.001,
            tool_calls=1,
            retries=0,
        )
        for index in range(1, 21)
    )
    summary = OperationalSummary(
        observations=observations,
        inclusion=OperationalInclusion.ALL_ATTEMPTS,
    )
    gate = OperationalReleaseGate(
        OperationalTailPolicy(
            minimum_samples=20,
            max_latency_p95_ms=18.0,
        )
    )

    result = gate.decide(summary)

    assert result.decision is GateDecision.REJECT
    assert "latency p95" in result.reasons[0]


def test_resolved_only_operational_gate_keeps_excluded_uncertainty_visible() -> None:
    observations = tuple(
        OperationalObservation(
            verdict=TrialVerdict.PASS,
            latency_ms=1.0,
            cost_usd=0.001,
            tool_calls=1,
            retries=0,
        )
        for _ in range(20)
    ) + (
        OperationalObservation(
            verdict=TrialVerdict.BLOCKED,
            latency_ms=20.0,
            cost_usd=0.010,
            tool_calls=2,
            retries=2,
        ),
    )
    summary = OperationalSummary(
        observations=observations,
        inclusion=OperationalInclusion.RESOLVED_ONLY,
    )
    gate = OperationalReleaseGate(
        OperationalTailPolicy(
            minimum_samples=20,
            max_latency_p95_ms=5.0,
        )
    )

    result = gate.decide(summary)

    assert result.decision is GateDecision.INCONCLUSIVE
    assert "excluded 1 blocked" in result.reasons[0]


def test_worst_slice_and_family_gate_is_non_compensatory() -> None:
    policy = ReleasePolicy(
        min_resolved_trials=2,
        min_success_rate=0.50,
        min_wilson_low=0.0,
    )
    gate = SliceReleaseGate(policy, required_risk_families=("safety", "quality"))
    strong = SliceEvidence(
        slice_id="quality.easy",
        risk_family="quality",
        reliability=_report(TrialVerdict.PASS, TrialVerdict.PASS),
    )
    unsafe = SliceEvidence(
        slice_id="safety.auth",
        risk_family="safety",
        reliability=_report(TrialVerdict.FAIL, TrialVerdict.FAIL),
    )

    result = gate.decide((strong, unsafe))

    assert result.decision is GateDecision.REJECT
    assert result.worst_slice == "safety.auth"
    families = {item.risk_family: item for item in result.family_results}
    assert families["safety"].decision is GateDecision.REJECT
    assert families["quality"].decision is GateDecision.ACCEPT


def test_missing_required_risk_family_is_inconclusive_not_accepted() -> None:
    policy = ReleasePolicy(
        min_resolved_trials=2,
        min_success_rate=0.50,
        min_wilson_low=0.0,
    )
    gate = SliceReleaseGate(policy, required_risk_families=("safety", "quality"))
    only_quality = SliceEvidence(
        slice_id="quality.easy",
        risk_family="quality",
        reliability=_report(TrialVerdict.PASS, TrialVerdict.PASS),
    )

    result = gate.decide((only_quality,))

    assert result.decision is GateDecision.INCONCLUSIVE
    assert any("safety" in reason for reason in result.reasons)


def test_critical_slice_violation_cannot_be_compensated_by_other_slices() -> None:
    policy = ReleasePolicy(
        min_resolved_trials=2,
        min_success_rate=0.0,
        min_wilson_low=0.0,
    )
    gate = SliceReleaseGate(policy)
    safe = SliceEvidence(
        slice_id="family.safe",
        risk_family="family",
        reliability=_report(TrialVerdict.PASS, TrialVerdict.PASS),
    )
    critical = SliceEvidence(
        slice_id="family.critical",
        risk_family="family",
        reliability=_report(TrialVerdict.PASS, TrialVerdict.PASS),
        critical_violations=1,
    )

    result = gate.decide((safe, critical))

    assert result.decision is GateDecision.REJECT
    assert any("critical violations" in reason for reason in result.reasons)


def test_slice_gate_result_rejects_duplicate_family_cache() -> None:
    family = RiskFamilyResult(
        risk_family="safety",
        decision=GateDecision.ACCEPT,
        worst_slice="safety.a",
        reasons=(),
    )

    with pytest.raises(ValueError, match="unique"):
        SliceGateResult(
            decision=GateDecision.ACCEPT,
            worst_slice="safety.a",
            family_results=(family, family),
            reasons=(),
        )
