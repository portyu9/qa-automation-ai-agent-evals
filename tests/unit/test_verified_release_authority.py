from __future__ import annotations

from typing import cast

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialVerdict
from agent_evals.gates import release as release_gate_module
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.runtime.release_verification import verify_session_release_criticality
from agent_evals.runtime.session import EvaluationSession
from agent_evals.statistics.reliability import ReliabilityReport
from agent_evals.verification import (
    PrivilegedProducerRole,
    ProducerCapabilityAuthority,
    VerifiedCriticalityRecord,
)


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="fixture",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="scripted",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="verified.release-criticality",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Derive release criticality from finalized evaluator records",
    )


def _policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=0,
        max_inconclusive_trials=0,
    )


def test_producer_capabilities_are_bound_to_exact_authority_instance() -> None:
    authority = ProducerCapabilityAuthority()
    other = ProducerCapabilityAuthority()
    capability = authority.issue(
        role=PrivilegedProducerRole.ATTACK_INJECTOR,
        producer_id="injector.static",
    )

    authority.require(
        capability,
        role=PrivilegedProducerRole.ATTACK_INJECTOR,
        producer_id="injector.static",
    )

    with pytest.raises(ValueError, match="different authority"):
        other.require(capability, role=PrivilegedProducerRole.ATTACK_INJECTOR)
    with pytest.raises(ValueError, match="role mismatch"):
        authority.require(capability, role=PrivilegedProducerRole.PROTOCOL_BRIDGE)
    with pytest.raises(ValueError, match="identity mismatch"):
        authority.require(
            capability,
            role=PrivilegedProducerRole.ATTACK_INJECTOR,
            producer_id="injector.other",
        )


@pytest.mark.asyncio
async def test_release_gate_derives_criticality_from_finalized_session() -> None:
    clean_session = await EvaluationSession().run(
        ScriptedAdapter(lambda _subject, _scenario, _trial: AdapterResult()),
        subject=_subject(),
        scenario=_scenario(),
        trials=1,
        campaign_id="release-clean",
    )
    clean = verify_session_release_criticality(clean_session)
    gate = ReleaseGate(_policy())

    assert (
        gate.decide_verified(clean_session.reliability, criticality=clean).decision
        is GateDecision.ACCEPT
    )

    violation = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.POLICY_VIOLATION,
        source="adapter:test",
        payload={"reason": "explicit policy fact"},
        critical=True,
    )
    critical_session = await EvaluationSession().run(
        ScriptedAdapter(lambda _subject, _scenario, _trial: AdapterResult(events=(violation,))),
        subject=_subject(),
        scenario=_scenario(),
        trials=1,
        campaign_id="release-critical",
    )
    critical = verify_session_release_criticality(critical_session)

    assert critical.critical_violations == 1
    rejected = gate.decide_verified(
        critical_session.reliability,
        criticality=critical,
    )
    assert rejected.decision is GateDecision.REJECT
    assert "critical violations 1 exceed maximum 0" in rejected.reasons


@pytest.mark.asyncio
async def test_verified_criticality_is_bound_to_exact_reliability_report() -> None:
    session = await EvaluationSession().run(
        ScriptedAdapter(lambda _subject, _scenario, _trial: AdapterResult()),
        subject=_subject(),
        scenario=_scenario(),
        trials=1,
        campaign_id="release-binding",
    )
    criticality = verify_session_release_criticality(session)
    different_report = ReliabilityReport.from_verdicts((TrialVerdict.PASS, TrialVerdict.PASS))

    with pytest.raises(ValueError) as exc_info:
        ReleaseGate(_policy()).decide_verified(
            different_report,
            criticality=criticality,
        )
    assert (
        str(exc_info.value) == "verified criticality does not bind the supplied reliability report"
    )


def test_verified_criticality_cannot_be_caller_issued() -> None:
    with pytest.raises(TypeError, match="only be issued"):
        VerifiedCriticalityRecord(
            subject_identity="1" * 64,
            scenario_identity="2" * 64,
            trial_evidence_roots=("3" * 64,),
            reliability_sha256="4" * 64,
            critical_violations=0,
            _issuer=object(),
        )


def test_verified_release_exact_type_guards_fail_closed() -> None:
    report = ReliabilityReport.from_verdicts((TrialVerdict.PASS,))
    gate = ReleaseGate(_policy())

    with pytest.raises(ValueError) as criticality_error:
        gate.decide_verified(
            report,
            criticality=cast(VerifiedCriticalityRecord, object()),
        )
    assert str(criticality_error.value) == "criticality must be an exact VerifiedCriticalityRecord"

    with pytest.raises(ValueError) as report_error:
        release_gate_module._reliability_report_sha256(cast(ReliabilityReport, object()))
    assert str(report_error.value) == "report must be an exact ReliabilityReport"


def test_reliability_report_binding_digest_has_stable_golden_vector() -> None:
    report = ReliabilityReport.from_verdicts(
        (
            TrialVerdict.PASS,
            TrialVerdict.FAIL,
            TrialVerdict.BLOCKED,
            TrialVerdict.INCONCLUSIVE,
        ),
        k=2,
    )

    assert (
        release_gate_module._reliability_report_sha256(report)
        == "f82fd1e2b955901006fee74cf63510c035492b38db21b2500964cbc2538c0810"
    )
