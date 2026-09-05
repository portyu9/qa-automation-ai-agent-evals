from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

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
from agent_evals.retrieval.ranker import RetrievalHit, RetrievalResult, rank_corpus
from agent_evals.retrieval.receipt import RetrievalDeliveryReceipt, RetrievalReceiptError
from agent_evals.retrieval.verification import RetrievalDeliveryError, verify_retrieval_delivery


def _chunk(chunk_id: str, content: str) -> RetrievalChunkSpec:
    return RetrievalChunkSpec(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source=f"fixture://{chunk_id}",
        content=content,
        metadata={"priority": 1},
    )


def _corpus() -> RetrievalCorpusSpec:
    return RetrievalCorpusSpec(
        corpus_id="verification-kb",
        revision="1",
        chunks=(
            _chunk("good", "alpha beta baseline guidance"),
            _chunk("other", "alpha background"),
            _chunk("third", "unrelated material"),
        ),
    )


def _contract(*, poison: bool = True) -> RetrievalContractSpec:
    corpus = _corpus()
    perturbation = None
    if poison:
        perturbation = RetrievalPoisonSpec(
            poison_id="verification-poison",
            revision="1",
            base_corpus_identity=corpus.identity,
            inserted_chunk=_chunk("aaa-poison", "alpha beta alpha beta controlled poison"),
            relation=RetrievalPoisonRelation.DISPLACE_CHUNK,
            expected_displaced_chunk_id="other",
        )
    return RetrievalContractSpec(
        tool_name="retrieve_context",
        corpus=corpus,
        query=RetrievalQuerySpec(query="alpha beta", top_k=2),
        poison=perturbation,
    )


def _scenario(contract: RetrievalContractSpec | None) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="retrieval.fail-closed",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Use the exact bound retrieval context.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"retrieve_context"})),
        retrieval=contract,
    )


def _active_json(contract: RetrievalContractSpec) -> str:
    corpus = contract.corpus if contract.poison is None else contract.poison.apply(contract.corpus)
    return rank_corpus(corpus, contract.query).canonical_json


def _evidence(contract: RetrievalContractSpec) -> TrialEvidence:
    scenario = _scenario(contract)
    output = _active_json(contract)
    receipt = RetrievalDeliveryReceipt.create(
        scenario_identity=scenario.identity,
        contract=contract,
        call_id="call-1",
        model_visible_result=output,
    )
    return TrialEvidence(
        trial_id="retrieval-fail-closed",
        subject_identity="1" * 64,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.TOOL_REQUEST,
                source="openai-agents:new_items",
                payload={
                    "tool": contract.tool_name,
                    "call_id": "call-1",
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
                source="openai-agents:new_items",
                payload={"call_id": "call-1", "output": output},
            ),
        ),
        final_output="done",
    )


def _hit(*, rank: int = 1, chunk_id: str = "hit") -> RetrievalHit:
    content = "alpha beta"
    return RetrievalHit(
        rank=rank,
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        source=f"fixture://{chunk_id}",
        score=100,
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def test_contracts_fail_closed_on_ambiguous_poison_configuration() -> None:
    corpus = _corpus()

    with pytest.raises(ValidationError, match="surrounding whitespace"):
        RetrievalChunkSpec(
            chunk_id="spaced-source",
            document_id="doc-spaced-source",
            source=" fixture://source",
            content="content",
        )
    with pytest.raises(ValidationError, match="unsupported retrieval JSON"):
        RetrievalChunkSpec(
            chunk_id="bad-metadata",
            document_id="doc-bad-metadata",
            source="fixture://bad-metadata",
            content="content",
            metadata={"opaque": object()},
        )
    with pytest.raises(ValidationError, match="requires an expected displaced chunk"):
        RetrievalPoisonSpec(
            poison_id="missing-displaced",
            revision="1",
            base_corpus_identity=corpus.identity,
            inserted_chunk=_chunk("poison-a", "alpha beta"),
            relation=RetrievalPoisonRelation.DISPLACE_CHUNK,
        )
    with pytest.raises(ValidationError, match="valid only for displace_chunk"):
        RetrievalPoisonSpec(
            poison_id="unexpected-displaced",
            revision="1",
            base_corpus_identity=corpus.identity,
            inserted_chunk=_chunk("poison-b", "alpha beta"),
            expected_displaced_chunk_id="good",
        )

    duplicate = RetrievalPoisonSpec(
        poison_id="duplicate",
        revision="1",
        base_corpus_identity=corpus.identity,
        inserted_chunk=_chunk("good", "replacement attempt"),
    )
    with pytest.raises(ValueError, match="cannot replace"):
        duplicate.apply(corpus)

    with pytest.raises(ValidationError, match="top_k cannot exceed"):
        RetrievalContractSpec(
            corpus=corpus,
            query=RetrievalQuerySpec(query="alpha", top_k=4),
        )

    wrong_base = RetrievalPoisonSpec(
        poison_id="wrong-base",
        revision="1",
        base_corpus_identity="0" * 64,
        inserted_chunk=_chunk("poison-c", "alpha beta"),
    )
    with pytest.raises(ValidationError, match="exact scenario base corpus"):
        RetrievalContractSpec(
            corpus=corpus,
            query=RetrievalQuerySpec(query="alpha", top_k=2),
            poison=wrong_base,
        )


def test_ranker_and_result_models_reject_ambiguous_material() -> None:
    with pytest.raises(ValidationError, match="content digest"):
        RetrievalHit(
            rank=1,
            chunk_id="bad-digest",
            document_id="doc-bad-digest",
            source="fixture://bad-digest",
            score=1,
            content="content",
            content_sha256="0" * 64,
        )
    with pytest.raises(ValidationError, match="contiguous"):
        RetrievalResult(query="alpha", hits=(_hit(rank=2),))

    first = _hit(rank=1, chunk_id="duplicate")
    second = _hit(rank=2, chunk_id="duplicate")
    with pytest.raises(ValidationError, match="duplicate chunk"):
        RetrievalResult(query="alpha", hits=(first, second))

    corpus = RetrievalCorpusSpec(
        corpus_id="tokenizer-kb",
        revision="1",
        chunks=(_chunk("a", "ALPHA—beta"), _chunk("b", "alpha gamma")),
    )
    result = rank_corpus(corpus, RetrievalQuerySpec(query="Alpha BETA", top_k=2))
    assert result.hits[0].chunk_id == "a"
    assert result.sha256 == hashlib.sha256(result.canonical_json.encode()).hexdigest()


def test_receipt_covers_clean_path_and_rejects_corruption() -> None:
    contract = _contract(poison=False)
    scenario = _scenario(contract)
    output = _active_json(contract)
    receipt = RetrievalDeliveryReceipt.create(
        scenario_identity=scenario.identity,
        contract=contract,
        call_id="plain-call",
        model_visible_result=output,
    )
    assert receipt.baseline_hits == receipt.active_hits
    assert receipt.poison_identity is None

    with pytest.raises(RetrievalReceiptError, match="non-empty"):
        RetrievalDeliveryReceipt.create(
            scenario_identity=scenario.identity,
            contract=contract,
            call_id="",
            model_visible_result=output,
        )

    poisoned = _contract()
    poisoned_receipt = RetrievalDeliveryReceipt.create(
        scenario_identity=_scenario(poisoned).identity,
        contract=poisoned,
        call_id="poisoned-call",
        model_visible_result=_active_json(poisoned),
    )
    raw = poisoned_receipt.model_dump(mode="python")

    missing_attacked = dict(raw)
    missing_attacked["attacked_corpus_identity"] = None
    with pytest.raises(ValidationError, match="identities must appear together"):
        RetrievalDeliveryReceipt.model_validate(missing_attacked)

    noncontiguous = dict(raw)
    noncontiguous["baseline_hits"] = [{**raw["baseline_hits"][0], "rank": 2}]
    with pytest.raises(ValidationError, match="contiguous"):
        RetrievalDeliveryReceipt.model_validate(noncontiguous)


def test_receipt_rejects_invalid_poison_application_and_displacement() -> None:
    contract = _contract()
    assert contract.poison is not None
    invalid_poison = contract.poison.model_copy(update={"base_corpus_identity": "0" * 64})
    invalid_contract = contract.model_copy(update={"poison": invalid_poison})
    with pytest.raises(RetrievalReceiptError, match="could not be applied"):
        RetrievalDeliveryReceipt.create(
            scenario_identity=_scenario(contract).identity,
            contract=invalid_contract,
            call_id="wrong-base",
            model_visible_result=_active_json(contract),
        )

    corpus = _corpus()
    insufficient = RetrievalContractSpec(
        corpus=corpus,
        query=RetrievalQuerySpec(query="alpha beta", top_k=2),
        poison=RetrievalPoisonSpec(
            poison_id="wrong-displacement",
            revision="1",
            base_corpus_identity=corpus.identity,
            inserted_chunk=_chunk("aaa-poison", "alpha beta alpha beta"),
            relation=RetrievalPoisonRelation.DISPLACE_CHUNK,
            expected_displaced_chunk_id="good",
        ),
    )
    assert insufficient.poison is not None
    attacked = insufficient.poison.apply(corpus)
    with pytest.raises(RetrievalReceiptError, match="did not displace"):
        RetrievalDeliveryReceipt.create(
            scenario_identity=_scenario(insufficient).identity,
            contract=insufficient,
            call_id="wrong-displacement",
            model_visible_result=rank_corpus(attacked, insufficient.query).canonical_json,
        )


def test_verifier_rejects_delivery_and_scenario_ambiguity() -> None:
    no_contract = _scenario(None)
    empty = TrialEvidence(
        trial_id="no-retrieval",
        subject_identity="1" * 64,
        scenario_identity=no_contract.identity,
        events=(),
    )
    assert verify_retrieval_delivery(no_contract, empty) is None

    contract = _contract()
    scenario = _scenario(contract)
    evidence = _evidence(contract)
    request, delivery, result = evidence.events

    with pytest.raises(RetrievalDeliveryError, match="no retrieval contract"):
        verify_retrieval_delivery(no_contract, empty.model_copy(update={"events": (delivery,)}))

    duplicate_delivery = evidence.model_copy(
        update={
            "events": (
                request,
                delivery,
                delivery.model_copy(update={"sequence": 2}),
                result.model_copy(update={"sequence": 3}),
            )
        }
    )
    with pytest.raises(RetrievalDeliveryError, match="exactly one delivery"):
        verify_retrieval_delivery(scenario, duplicate_delivery)

    critical = evidence.model_copy(
        update={"events": (request, delivery.model_copy(update={"critical": True}), result)}
    )
    with pytest.raises(RetrievalDeliveryError, match="non-critical"):
        verify_retrieval_delivery(scenario, critical)

    unknown_source = evidence.model_copy(
        update={
            "events": (
                request,
                delivery.model_copy(update={"source": "bridge:unknown"}),
                result,
            )
        }
    )
    with pytest.raises(RetrievalDeliveryError, match="source is not recognized"):
        verify_retrieval_delivery(scenario, unknown_source)

    with pytest.raises(RetrievalDeliveryError, match="evidence scenario identity"):
        verify_retrieval_delivery(
            scenario,
            evidence.model_copy(update={"scenario_identity": "0" * 64}),
        )


def test_verifier_rejects_request_argument_and_result_ambiguity() -> None:
    contract = _contract()
    scenario = _scenario(contract)
    evidence = _evidence(contract)
    request, delivery, result = evidence.events

    wrong_call_request = request.model_copy(
        update={"payload": {**request.payload, "call_id": "other"}}
    )
    with pytest.raises(RetrievalDeliveryError, match="call identity"):
        verify_retrieval_delivery(
            scenario,
            evidence.model_copy(update={"events": (wrong_call_request, delivery, result)}),
        )

    for arguments, message in (
        ({"query": "alpha beta"}, "canonical JSON text"),
        ("{", "invalid JSON"),
        ('{"query":"alpha beta","query":"alpha beta"}', "invalid JSON"),
        ('{"query":"different"}', "exact bound query"),
    ):
        changed = request.model_copy(
            update={"payload": {**request.payload, "arguments": arguments}}
        )
        with pytest.raises(RetrievalDeliveryError, match=message):
            verify_retrieval_delivery(
                scenario,
                evidence.model_copy(update={"events": (changed, delivery, result)}),
            )

    duplicate_result = evidence.model_copy(
        update={
            "events": (
                request,
                delivery,
                result,
                result.model_copy(update={"sequence": 3}),
            )
        }
    )
    with pytest.raises(RetrievalDeliveryError, match="exactly one matching tool result"):
        verify_retrieval_delivery(scenario, duplicate_result)

    non_string_result = result.model_copy(update={"payload": {"call_id": "call-1", "output": {}}})
    with pytest.raises(RetrievalDeliveryError, match="canonical JSON string"):
        verify_retrieval_delivery(
            scenario,
            evidence.model_copy(update={"events": (request, delivery, non_string_result)}),
        )

    mismatched_result = result.model_copy(update={"payload": {"call_id": "call-1", "output": "{}"}})
    with pytest.raises(RetrievalDeliveryError, match="cannot be reconstructed"):
        verify_retrieval_delivery(
            scenario,
            evidence.model_copy(update={"events": (request, delivery, mismatched_result)}),
        )


def test_verifier_rejects_invalid_or_foreign_receipt() -> None:
    contract = _contract()
    scenario = _scenario(contract)
    evidence = _evidence(contract)
    request, delivery, result = evidence.events

    malformed_payload = dict(delivery.payload)
    malformed_payload["receipt_root"] = "0" * 64
    malformed_delivery = delivery.model_copy(update={"payload": malformed_payload})
    with pytest.raises(RetrievalDeliveryError, match="schema validation"):
        verify_retrieval_delivery(
            scenario,
            evidence.model_copy(update={"events": (request, malformed_delivery, result)}),
        )

    foreign = RetrievalDeliveryReceipt.create(
        scenario_identity="0" * 64,
        contract=contract,
        call_id="call-1",
        model_visible_result=_active_json(contract),
    )
    with pytest.raises(RetrievalDeliveryError, match="receipt scenario identity"):
        verify_retrieval_delivery(
            scenario,
            evidence.model_copy(update={"events": (request, foreign.to_event(sequence=1), result)}),
        )
