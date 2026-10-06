from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.verification import (
    EvidenceChain,
    FactKind,
    FactProducerRole,
    VerificationFactClaim,
    VerificationGraph,
    canonical_identifier,
    verify_fact_claim,
)


def _claim(
    material: bytes,
    *,
    name: str = "policy.checked",
    dependencies: tuple[str, ...] = (),
) -> VerificationFactClaim:
    return VerificationFactClaim.from_material(
        fact_kind=FactKind.PRECONDITION,
        fact_name=name,
        producer=FactProducerRole.EVALUATOR,
        material=material,
        subject_identity="1" * 64,
        scenario_identity="2" * 64,
        trial_id="trial-1",
        dependencies=dependencies,
    )


def _verify(
    claim: VerificationFactClaim,
    material: bytes,
    *,
    name: str = "policy.checked",
    dependencies: tuple[str, ...] = (),
):
    return verify_fact_claim(
        claim,
        expected_kind=FactKind.PRECONDITION,
        expected_name=name,
        expected_producer=FactProducerRole.EVALUATOR,
        material=material,
        expected_dependencies=dependencies,
        expected_subject_identity="1" * 64,
        expected_scenario_identity="2" * 64,
        expected_trial_id="trial-1",
    )


def test_identifier_policy_accepts_canonical_unicode_and_rejects_aliases() -> None:
    assert canonical_identifier("café", label="name") == "café"

    with pytest.raises(ValueError, match="must already satisfy"):
        canonical_identifier("cafe\u0301", label="name")
    with pytest.raises(ValueError, match="surrounding whitespace"):
        canonical_identifier(" tool", label="name")
    with pytest.raises(ValueError, match="forbidden Unicode"):
        canonical_identifier("tool\u0000name", label="name")


def test_fact_claim_requires_independent_material_and_context() -> None:
    claim = _claim(b"verified material")
    verified = _verify(claim, b"verified material")

    assert verified.fact_root == claim.fact_root

    with pytest.raises(ValueError, match="independent expected"):
        _verify(claim, b"different material")
    with pytest.raises(ValueError, match="independent expected"):
        verify_fact_claim(
            claim,
            expected_kind=FactKind.PRECONDITION,
            expected_name="policy.checked",
            expected_producer=FactProducerRole.EXTERNAL,
            material=b"verified material",
            expected_subject_identity="1" * 64,
            expected_scenario_identity="2" * 64,
            expected_trial_id="trial-1",
        )


def test_fact_claim_rejects_root_tamper_and_noncanonical_dependencies() -> None:
    claim = _claim(b"material")
    payload = claim.model_dump(mode="json")
    payload["fact_root"] = "f" * 64

    with pytest.raises(ValidationError, match="fact root mismatch"):
        VerificationFactClaim.model_validate(payload)

    with pytest.raises(ValueError, match="unique canonical sorted"):
        VerificationFactClaim.from_material(
            fact_kind=FactKind.ORACLE,
            fact_name="oracle.policy",
            producer=FactProducerRole.VERIFIER,
            material=b"x",
            dependencies=("b" * 64, "a" * 64),
        )


def test_verification_graph_requires_verified_topological_dependencies() -> None:
    first_claim = _claim(b"first", name="first")
    first = _verify(first_claim, b"first", name="first")
    second_claim = _claim(b"second", name="second", dependencies=(first.fact_root,))
    second = _verify(
        second_claim,
        b"second",
        name="second",
        dependencies=(first.fact_root,),
    )

    graph = VerificationGraph.from_verified((first, second))
    assert len(graph.facts) == 2
    assert len(graph.graph_root) == 64

    with pytest.raises(ValueError, match="topologically prior"):
        VerificationGraph.from_verified((second, first))
    with pytest.raises(ValueError, match="duplicate fact roots"):
        VerificationGraph.from_verified((first, first))


def test_evidence_chain_binds_order_and_previous_roots() -> None:
    a = "a" * 64
    b = "b" * 64
    chain = EvidenceChain.from_event_digests((a, b))
    reversed_chain = EvidenceChain.from_event_digests((b, a))

    assert chain.links[1].previous_root == chain.links[0].chain_root
    assert chain.final_root != reversed_chain.final_root

    payload = json.loads(chain.model_dump_json())
    payload["links"][1]["previous_root"] = "0" * 64
    with pytest.raises(ValidationError, match=r"previous_root relation mismatch|link root mismatch"):
        EvidenceChain.model_validate(payload)
