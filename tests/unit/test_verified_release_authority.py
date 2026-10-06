from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.statistics.reliability import ReliabilityReport
from agent_evals.verification import (
    FactKind,
    FactProducerRole,
    PrivilegedProducerRole,
    ProducerCapabilityAuthority,
    VerificationFactClaim,
    VerificationGraph,
    VerifiedCriticalityRecord,
    verify_fact_claim,
)


def _critical_fact(material: bytes = b"critical"):
    claim = VerificationFactClaim.from_material(
        fact_kind=FactKind.CRITICALITY,
        fact_name="release.critical-policy-fact",
        producer=FactProducerRole.VERIFIER,
        material=material,
        trial_id="trial-1",
    )
    return verify_fact_claim(
        claim,
        expected_kind=FactKind.CRITICALITY,
        expected_name="release.critical-policy-fact",
        expected_producer=FactProducerRole.VERIFIER,
        material=material,
        expected_trial_id="trial-1",
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


def test_release_gate_can_derive_noncompensatory_criticality_from_verified_records() -> None:
    report = ReliabilityReport.from_verdicts((TrialVerdict.PASS,))
    policy = ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=0,
        max_inconclusive_trials=0,
    )
    gate = ReleaseGate(policy)

    baseline_claim = VerificationFactClaim.from_material(
        fact_kind=FactKind.OUTCOME,
        fact_name="outcome.checked",
        producer=FactProducerRole.VERIFIER,
        material=b"outcome",
    )
    baseline = verify_fact_claim(
        baseline_claim,
        expected_kind=FactKind.OUTCOME,
        expected_name="outcome.checked",
        expected_producer=FactProducerRole.VERIFIER,
        material=b"outcome",
    )
    clean_graph = VerificationGraph.from_verified((baseline,))

    critical_claim = VerificationFactClaim.from_material(
        fact_kind=FactKind.CRITICALITY,
        fact_name="release.critical-policy-fact",
        producer=FactProducerRole.VERIFIER,
        material=b"critical",
        dependencies=(baseline.fact_root,),
        trial_id="trial-1",
    )
    critical = verify_fact_claim(
        critical_claim,
        expected_kind=FactKind.CRITICALITY,
        expected_name="release.critical-policy-fact",
        expected_producer=FactProducerRole.VERIFIER,
        material=b"critical",
        expected_dependencies=(baseline.fact_root,),
        expected_trial_id="trial-1",
    )
    critical_graph = VerificationGraph.from_verified((baseline, critical))

    assert gate.decide_verified(report, verification=clean_graph).decision is GateDecision.ACCEPT
    rejected = gate.decide_verified(report, verification=critical_graph)
    assert rejected.decision is GateDecision.REJECT
    assert rejected.reasons == ("critical violations 1 exceed maximum 0",)


def test_verified_criticality_rejects_noncritical_fact_kind() -> None:
    claim = VerificationFactClaim.from_material(
        fact_kind=FactKind.OUTCOME,
        fact_name="outcome.checked",
        producer=FactProducerRole.VERIFIER,
        material=b"outcome",
    )
    verified = verify_fact_claim(
        claim,
        expected_kind=FactKind.OUTCOME,
        expected_name="outcome.checked",
        expected_producer=FactProducerRole.VERIFIER,
        material=b"outcome",
    )

    with pytest.raises(ValueError, match="only criticality facts"):
        VerifiedCriticalityRecord.from_verified((verified,))
