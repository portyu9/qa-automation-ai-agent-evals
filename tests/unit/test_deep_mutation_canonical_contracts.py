from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import BaseModel

import agent_evals.evidence.store as evidence_store
import agent_evals.retrieval.receipt as retrieval_receipt
import agent_evals.retrieval.verification as retrieval_verification
import agent_evals.semantic.receipt as semantic_receipt
import agent_evals.side_effect.receipt as side_effect_receipt
from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.retrieval.models import (
    RetrievalChunkSpec,
    RetrievalContractSpec,
    RetrievalCorpusSpec,
    RetrievalPoisonRelation,
    RetrievalPoisonSpec,
    RetrievalQuerySpec,
)
from agent_evals.retrieval.ranker import rank_corpus


class _ProbeModel(BaseModel):
    value: int


def _retrieval_chunk(chunk_id: str, content: str) -> RetrievalChunkSpec:
    return RetrievalChunkSpec(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source=f"fixture://{chunk_id}",
        content=content,
        metadata={"priority": 1},
    )


def _retrieval_contract(*, poison: bool = True) -> RetrievalContractSpec:
    corpus = RetrievalCorpusSpec(
        corpus_id="mutation-retrieval",
        revision="1",
        chunks=(
            _retrieval_chunk("good", "alpha beta baseline guidance"),
            _retrieval_chunk("other", "alpha background"),
            _retrieval_chunk("third", "unrelated material"),
        ),
    )
    poison_spec = None
    if poison:
        poison_spec = RetrievalPoisonSpec(
            poison_id="mutation-poison",
            revision="1",
            base_corpus_identity=corpus.identity,
            inserted_chunk=_retrieval_chunk(
                "aaa-poison",
                "alpha beta alpha beta controlled poison",
            ),
            relation=RetrievalPoisonRelation.DISPLACE_CHUNK,
            expected_displaced_chunk_id="other",
        )
    return RetrievalContractSpec(
        tool_name="retrieve_context",
        corpus=corpus,
        query=RetrievalQuerySpec(query="alpha beta", top_k=2),
        poison=poison_spec,
    )


def _retrieval_scenario(contract: RetrievalContractSpec | None) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="mutation.retrieval-receipt",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Preserve the exact verified retrieval relation.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"retrieve_context"})),
        retrieval=contract,
    )


def _retrieval_output(contract: RetrievalContractSpec) -> str:
    corpus = contract.corpus if contract.poison is None else contract.poison.apply(contract.corpus)
    return rank_corpus(corpus, contract.query).canonical_json


def _retrieval_evidence(
    contract: RetrievalContractSpec,
) -> tuple[
    EvaluationScenario,
    TrialEvidence,
    retrieval_receipt.RetrievalDeliveryReceipt,
]:
    scenario = _retrieval_scenario(contract)
    output = _retrieval_output(contract)
    receipt = retrieval_receipt.RetrievalDeliveryReceipt.create(
        scenario_identity=scenario.identity,
        contract=contract,
        call_id="call-1",
        model_visible_result=output,
    )
    evidence = TrialEvidence(
        trial_id="mutation-retrieval",
        subject_identity="7" * 64,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.TOOL_REQUEST,
                source="test",
                payload={
                    "tool": contract.tool_name,
                    "call_id": receipt.call_id,
                    "arguments": json.dumps(
                        {"query": contract.query.query},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ),
            receipt.to_event(sequence=1),
            EvidenceEvent(
                sequence=2,
                kind=EvidenceKind.TOOL_RESULT,
                source="test",
                payload={"call_id": receipt.call_id, "output": output},
            ),
        ),
    )
    return scenario, evidence, receipt


def _reroot_retrieval_receipt(
    receipt: retrieval_receipt.RetrievalDeliveryReceipt,
    **updates: object,
) -> retrieval_receipt.RetrievalDeliveryReceipt:
    unsigned = receipt.model_dump(mode="python", exclude={"receipt_root"})
    unsigned.update(updates)
    return retrieval_receipt.RetrievalDeliveryReceipt.model_validate(
        {**unsigned, "receipt_root": retrieval_receipt._receipt_root(unsigned)}
    )


def _assert_retrieval_error(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
    expected: str,
) -> None:
    with pytest.raises(retrieval_verification.RetrievalDeliveryError) as captured:
        retrieval_verification.verify_retrieval_delivery(scenario, evidence)
    assert str(captured.value) == expected


def test_receipt_roots_use_exact_domain_separation() -> None:
    material = {"z": 1, "a": "x"}
    canonical = b'{"a":"x","z":1}'

    retrieval_root = retrieval_receipt._receipt_root(material)
    semantic_root = semantic_receipt._receipt_root(material)
    side_effect_root = side_effect_receipt._receipt_root(material)

    assert (
        retrieval_root
        == hashlib.sha256(b"agent-evals/retrieval-delivery-receipt/v1\0" + canonical).hexdigest()
    )
    assert (
        semantic_root
        == hashlib.sha256(b"agent-evals/semantic-judgment-receipt/v1\0" + canonical).hexdigest()
    )
    assert (
        side_effect_root
        == hashlib.sha256(
            b"agent-evals/side-effect-idempotency-receipt/v1\0" + canonical
        ).hexdigest()
    )
    assert len({retrieval_root, semantic_root, side_effect_root}) == 3


def test_receipt_canonicalization_preserves_declared_unicode_policy() -> None:
    material = {"z": 1, "a": "Ω"}
    escaped = b'{"a":"\\u03a9","z":1}'
    unicode_bytes = '{"a":"Ω","z":1}'.encode()

    assert (
        retrieval_receipt._receipt_root(material)
        == hashlib.sha256(b"agent-evals/retrieval-delivery-receipt/v1\0" + escaped).hexdigest()
    )
    assert (
        side_effect_receipt._receipt_root(material)
        == hashlib.sha256(b"agent-evals/side-effect-idempotency-receipt/v1\0" + escaped).hexdigest()
    )
    assert semantic_receipt._canonical_json_bytes(material) == unicode_bytes
    assert (
        semantic_receipt._receipt_root(material)
        == hashlib.sha256(b"agent-evals/semantic-judgment-receipt/v1\0" + unicode_bytes).hexdigest()
    )


@pytest.mark.parametrize(
    ("root_fn", "label"),
    [
        (retrieval_receipt._receipt_root, "retrieval receipt material"),
        (semantic_receipt._receipt_root, "semantic judgment receipt material"),
        (side_effect_receipt._receipt_root, "side-effect receipt material"),
    ],
)
def test_receipt_roots_preserve_resource_limit_labels(
    root_fn: object,
    label: str,
) -> None:
    assert callable(root_fn)
    with pytest.raises(ValueError, match=label):
        root_fn({"unsupported": object()})


def test_retrieval_resource_limit_label_is_exact() -> None:
    with pytest.raises(ValueError) as captured:
        retrieval_receipt._receipt_root({"unsupported": object()})
    assert str(captured.value) == (
        "retrieval receipt material contains unsupported JSON value type object"
    )


def test_retrieval_json_default_is_explicit_and_fail_closed() -> None:
    assert retrieval_receipt._json_default(_ProbeModel(value=7)) == {"value": 7}
    assert retrieval_receipt._json_default(RetrievalPoisonRelation.ENTER_TOP_K) == "enter_top_k"
    with pytest.raises(
        TypeError,
        match=r"^unsupported receipt value type: object$",
    ):
        retrieval_receipt._json_default(object())


def test_side_effect_json_default_is_explicit_and_fail_closed() -> None:
    assert side_effect_receipt._json_default(_ProbeModel(value=7)) == {"value": 7}
    with pytest.raises(
        TypeError,
        match=r"^unsupported side-effect receipt value type: object$",
    ):
        side_effect_receipt._json_default(object())


def test_semantic_canonicalization_rejects_nonfinite_or_unsupported_material() -> None:
    for value in ({"value": float("nan")}, {"value": object()}):
        with pytest.raises(
            ValueError,
            match=r"^semantic judgment material must be finite JSON-compatible data$",
        ):
            semantic_receipt._canonical_json_bytes(value)


def test_evidence_store_canonical_json_is_sorted_compact_and_finite() -> None:
    material = {"z": 1, "a": "Ω"}
    expected = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    assert evidence_store._canonical_json_bytes(material) == expected
    assert expected == b'{"a":"\\u03a9","z":1}'
    with pytest.raises(ValueError):
        evidence_store._canonical_json_bytes({"value": float("nan")})


def test_retrieval_receipt_creation_diagnostics_are_exact() -> None:
    contract = _retrieval_contract()
    scenario = _retrieval_scenario(contract)
    output = _retrieval_output(contract)

    with pytest.raises(retrieval_receipt.RetrievalReceiptError) as captured:
        retrieval_receipt.RetrievalDeliveryReceipt.create(
            scenario_identity=scenario.identity,
            contract=contract,
            call_id="",
            model_visible_result=output,
        )
    assert str(captured.value) == "retrieval tool call identity must be non-empty"

    assert contract.poison is not None
    invalid_poison = contract.poison.model_copy(update={"base_corpus_identity": "0" * 64})
    invalid_contract = contract.model_copy(update={"poison": invalid_poison})
    with pytest.raises(retrieval_receipt.RetrievalReceiptError) as captured:
        retrieval_receipt.RetrievalDeliveryReceipt.create(
            scenario_identity=scenario.identity,
            contract=invalid_contract,
            call_id="call-1",
            model_visible_result=output,
        )
    assert str(captured.value) == "retrieval poison could not be applied"

    with pytest.raises(retrieval_receipt.RetrievalReceiptError) as captured:
        retrieval_receipt.RetrievalDeliveryReceipt.create(
            scenario_identity=scenario.identity,
            contract=contract,
            call_id="call-1",
            model_visible_result="{}",
        )
    assert str(captured.value) == (
        "model-visible retrieval result does not equal the canonical active ranking"
    )


def test_retrieval_poison_relation_diagnostics_are_exact() -> None:
    base = _retrieval_contract(poison=False)
    weak_poison = RetrievalPoisonSpec(
        poison_id="weak-poison",
        revision="1",
        base_corpus_identity=base.corpus.identity,
        inserted_chunk=_retrieval_chunk("zzz-poison", "entirely unrelated words"),
    )
    weak = base.model_copy(update={"poison": weak_poison})
    weak_output = _retrieval_output(weak)
    with pytest.raises(retrieval_receipt.RetrievalReceiptError) as captured:
        retrieval_receipt.RetrievalDeliveryReceipt.create(
            scenario_identity=_retrieval_scenario(weak).identity,
            contract=weak,
            call_id="weak-call",
            model_visible_result=weak_output,
        )
    assert str(captured.value) == "controlled poison did not enter the active top-k ranking"

    contract = _retrieval_contract()
    assert contract.poison is not None
    wrong_displacement = contract.poison.model_copy(
        update={"expected_displaced_chunk_id": "third"}
    )
    changed = contract.model_copy(update={"poison": wrong_displacement})
    changed_output = _retrieval_output(changed)
    with pytest.raises(retrieval_receipt.RetrievalReceiptError) as captured:
        retrieval_receipt.RetrievalDeliveryReceipt.create(
            scenario_identity=_retrieval_scenario(changed).identity,
            contract=changed,
            call_id="wrong-displacement",
            model_visible_result=changed_output,
        )
    assert str(captured.value) == (
        "controlled poison did not displace the exact expected baseline chunk"
    )


def test_retrieval_hit_identity_uniqueness_diagnostic_is_exact() -> None:
    first = retrieval_receipt.RetrievalHitDigest(
        rank=1,
        chunk_id="duplicate",
        document_id="doc-one",
        score=10,
        content_sha256="1" * 64,
    )
    second = retrieval_receipt.RetrievalHitDigest(
        rank=2,
        chunk_id="duplicate",
        document_id="doc-two",
        score=9,
        content_sha256="2" * 64,
    )
    with pytest.raises(ValueError) as captured:
        retrieval_receipt._require_contiguous_ranks((first, second), label="active")
    assert str(captured.value) == (
        "retrieval active receipt hits must have unique chunk identities"
    )


def test_retrieval_verifier_frontier_diagnostics_are_exact() -> None:
    contract = _retrieval_contract()
    scenario, evidence, _ = _retrieval_evidence(contract)
    request, delivery, result = evidence.events

    no_contract = _retrieval_scenario(None)
    no_contract_evidence = TrialEvidence(
        trial_id="no-contract",
        subject_identity="7" * 64,
        scenario_identity=no_contract.identity,
        events=(delivery.model_copy(update={"sequence": 0}),),
    )
    _assert_retrieval_error(
        no_contract,
        no_contract_evidence,
        "retrieval delivery evidence is invalid when the scenario has no retrieval contract",
    )

    missing_delivery = evidence.model_copy(
        update={"events": (request, result.model_copy(update={"sequence": 1}))}
    )
    _assert_retrieval_error(
        scenario,
        missing_delivery,
        "scenario retrieval contract requires exactly one delivery receipt",
    )

    _assert_retrieval_error(
        scenario,
        evidence.model_copy(
            update={"events": (request, delivery.model_copy(update={"critical": True}), result)}
        ),
        "retrieval delivery evidence must remain non-critical",
    )
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(
            update={
                "events": (
                    request,
                    delivery.model_copy(update={"source": "bridge:unknown"}),
                    result,
                )
            }
        ),
        "retrieval delivery evidence source is not recognized",
    )

    malformed = dict(delivery.payload)
    malformed["receipt_root"] = "0" * 64
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(
            update={"events": (request, delivery.model_copy(update={"payload": malformed}), result)}
        ),
        "retrieval delivery receipt failed schema validation",
    )
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(update={"scenario_identity": "0" * 64}),
        "retrieval evidence scenario identity does not match scenario",
    )


def test_retrieval_verifier_receipt_binding_diagnostics_are_exact() -> None:
    contract = _retrieval_contract()
    scenario, evidence, receipt = _retrieval_evidence(contract)
    request, _, result = evidence.events

    foreign_scenario = retrieval_receipt.RetrievalDeliveryReceipt.create(
        scenario_identity="0" * 64,
        contract=contract,
        call_id=receipt.call_id,
        model_visible_result=_retrieval_output(contract),
    )
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(
            update={"events": (request, foreign_scenario.to_event(sequence=1), result)}
        ),
        "retrieval receipt scenario identity does not match scenario",
    )

    foreign_contract = _reroot_retrieval_receipt(receipt, contract_identity="1" * 64)
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(
            update={"events": (request, foreign_contract.to_event(sequence=1), result)}
        ),
        "retrieval receipt contract identity does not match scenario",
    )

    foreign_tool = _reroot_retrieval_receipt(receipt, tool_name="different_retriever")
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(
            update={"events": (request, foreign_tool.to_event(sequence=1), result)}
        ),
        "retrieval receipt tool identity does not match scenario",
    )


def test_retrieval_verifier_request_and_result_diagnostics_are_exact() -> None:
    contract = _retrieval_contract()
    scenario, evidence, _ = _retrieval_evidence(contract)
    request, delivery, result = evidence.events

    missing_request = evidence.model_copy(
        update={
            "events": (
                delivery.model_copy(update={"sequence": 0}),
                result.model_copy(update={"sequence": 1}),
            )
        }
    )
    _assert_retrieval_error(
        scenario,
        missing_request,
        "retrieval contract requires exactly one target tool request",
    )

    wrong_call = request.model_copy(
        update={"payload": {**request.payload, "call_id": "other"}}
    )
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(update={"events": (wrong_call, delivery, result)}),
        "retrieval request call identity does not match receipt",
    )

    missing_result = evidence.model_copy(update={"events": (request, delivery)})
    _assert_retrieval_error(
        scenario,
        missing_result,
        "retrieval receipt requires exactly one matching tool result",
    )

    non_string = result.model_copy(
        update={"payload": {"call_id": "call-1", "output": {}}}
    )
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(update={"events": (request, delivery, non_string)}),
        "retrieval tool result must expose one canonical JSON string",
    )

    reordered = evidence.model_copy(
        update={
            "events": (
                delivery.model_copy(update={"sequence": 0}),
                request.model_copy(update={"sequence": 1}),
                result,
            )
        }
    )
    _assert_retrieval_error(
        scenario,
        reordered,
        "retrieval chronology must order request before delivery before tool result",
    )

    different_output = result.model_copy(
        update={"payload": {"call_id": "call-1", "output": "{}"}}
    )
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(update={"events": (request, delivery, different_output)}),
        "retrieval relation cannot be reconstructed from scenario",
    )


def test_retrieval_verifier_rederived_receipt_diagnostic_is_exact() -> None:
    contract = _retrieval_contract()
    scenario, evidence, receipt = _retrieval_evidence(contract)
    request, _, result = evidence.events
    altered = _reroot_retrieval_receipt(receipt, model_visible_result_sha256="0" * 64)
    _assert_retrieval_error(
        scenario,
        evidence.model_copy(update={"events": (request, altered.to_event(sequence=1), result)}),
        "retrieval receipt does not match rederived scenario relation",
    )


def test_retrieval_request_argument_diagnostics_are_exact() -> None:
    contract = _retrieval_contract()
    scenario, evidence, _ = _retrieval_evidence(contract)
    request, delivery, result = evidence.events

    cases: tuple[tuple[object, str], ...] = (
        (
            {"query": contract.query.query},
            "retrieval tool request arguments must be canonical JSON text",
        ),
        ("{", "retrieval tool request arguments are invalid JSON"),
        (
            '{"query":"alpha beta","query":"alpha beta"}',
            "retrieval tool request arguments are invalid JSON",
        ),
        (
            '{"query":"different"}',
            "retrieval tool request must contain only the exact bound query",
        ),
    )
    for arguments, expected in cases:
        changed = request.model_copy(
            update={"payload": {**request.payload, "arguments": arguments}}
        )
        _assert_retrieval_error(
            scenario,
            evidence.model_copy(update={"events": (changed, delivery, result)}),
            expected,
        )


def test_retrieval_duplicate_json_member_diagnostic_is_exact() -> None:
    with pytest.raises(ValueError) as captured:
        retrieval_verification._reject_duplicate_keys(
            [("query", "alpha beta"), ("query", "different")]
        )
    assert str(captured.value) == "duplicate JSON object member"
