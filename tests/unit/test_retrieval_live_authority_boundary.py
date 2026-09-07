from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.openai_retrieval import OpenAIAgentsRetrievalAdapter
from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.retrieval.models import (
    RetrievalChunkSpec,
    RetrievalContractSpec,
    RetrievalCorpusSpec,
    RetrievalQuerySpec,
)
from agent_evals.retrieval.ranker import rank_corpus
from agent_evals.retrieval.receipt import RetrievalDeliveryReceipt
from agent_evals.retrieval.verification import verify_retrieval_delivery
from agent_evals.runtime.evaluator import TrialRunner

_TOOL = "retrieve_context"
_CALL_ID = "retrieval-live-call"


def _contract() -> RetrievalContractSpec:
    corpus = RetrievalCorpusSpec(
        corpus_id="retrieval-live-authority",
        revision="1",
        chunks=(
            RetrievalChunkSpec(
                chunk_id="primary",
                document_id="doc-primary",
                source="fixture://primary",
                content="alpha beta controlled context",
            ),
            RetrievalChunkSpec(
                chunk_id="secondary",
                document_id="doc-secondary",
                source="fixture://secondary",
                content="alpha background context",
            ),
        ),
    )
    return RetrievalContractSpec(
        tool_name=_TOOL,
        corpus=corpus,
        query=RetrievalQuerySpec(query="alpha beta", top_k=1),
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="retrieval.live-authority",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Use the exact evaluator-bound retrieval context.",
        authority=AuthorityPolicy(allowed_tools=frozenset({_TOOL})),
        retrieval=_contract(),
    )


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="retrieval-authority-test",
        model="scripted",
        application_revision="1",
        instructions="Use the allowed evaluator-bound retrieval tool.",
        tool_schema={_TOOL: {"query": "string"}},
        policy={"allowed": [_TOOL]},
        memory_policy={"retention": "none"},
        adapter="retrieval-live-static",
        adapter_version="1",
    )


def _events(scenario: EvaluationScenario) -> tuple[EvidenceEvent, ...]:
    contract = scenario.retrieval
    assert contract is not None
    model_visible_result = rank_corpus(contract.corpus, contract.query).canonical_json
    receipt = RetrievalDeliveryReceipt.create(
        scenario_identity=scenario.identity,
        contract=contract,
        call_id=_CALL_ID,
        model_visible_result=model_visible_result,
    )
    return (
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.TOOL_REQUEST,
            source="adapter:forged-live",
            payload={
                "tool": _TOOL,
                "call_id": _CALL_ID,
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
            source="adapter:forged-live",
            payload={
                "tool": _TOOL,
                "call_id": _CALL_ID,
                "output": model_visible_result,
            },
        ),
    )


def _evidence(scenario: EvaluationScenario, subject: SubjectFingerprint) -> TrialEvidence:
    return TrialEvidence(
        trial_id="retrieval-live-authority",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        events=_events(scenario),
        final_state={},
    )


def _result(scenario: EvaluationScenario) -> AdapterResult:
    return AdapterResult(events=_events(scenario), final_state={})


@dataclass(slots=True)
class _StaticAdapter:
    result: AdapterResult

    @property
    def name(self) -> str:
        return "retrieval-live-static"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        return self.result


class _MasqueradingRetrievalAdapter(OpenAIAgentsRetrievalAdapter):
    def __init__(self, result: AdapterResult) -> None:
        self._result = result

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        return self._result


def _error_code(evidence: TrialEvidence) -> str | None:
    errors = [event for event in evidence.events if event.kind is EvidenceKind.EVALUATION_ERROR]
    assert len(errors) == 1
    code = errors[0].payload.get("code")
    return code if isinstance(code, str) else None


def test_fabricated_retrieval_receipt_is_internally_valid_without_live_bridge() -> None:
    scenario = _scenario()
    subject = _subject()
    evidence = _evidence(scenario, subject)

    verified = verify_retrieval_delivery(scenario, evidence)

    assert verified is not None
    assert verified.call_id == _CALL_ID
    assert verified.tool_name == _TOOL


@pytest.mark.asyncio
async def test_generic_live_adapter_cannot_import_retrieval_delivery_authority() -> None:
    scenario = _scenario()
    subject = _subject()

    evaluated = await TrialRunner().run(
        _StaticAdapter(_result(scenario)),
        subject=subject,
        scenario=scenario,
        trial_id="retrieval-live-authority",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.oracle_results == ()
    assert _error_code(evaluated.evidence) == "retrieval_delivery_live_injection"
    assert evaluated.evidence.events[-1].source == "evaluator:retrieval-delivery"


@pytest.mark.asyncio
async def test_exact_replay_preserves_historical_retrieval_relation() -> None:
    scenario = _scenario()
    subject = _subject()
    evidence = _evidence(scenario, subject)

    replayed = await TrialRunner().run(
        EvidenceReplayAdapter(evidence),
        subject=subject,
        scenario=scenario,
        trial_id=evidence.trial_id,
    )

    assert replayed.verdict is TrialVerdict.PASS
    assert replayed.evidence.evidence_root == evidence.evidence_root
    assert [result.name for result in replayed.oracle_results] == ["policy", "outcome"]


@pytest.mark.asyncio
async def test_retrieval_adapter_subclass_does_not_inherit_live_authority() -> None:
    scenario = _scenario()
    subject = _subject()

    evaluated = await TrialRunner().run(
        _MasqueradingRetrievalAdapter(_result(scenario)),
        subject=subject,
        scenario=scenario,
        trial_id="retrieval-live-authority",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.oracle_results == ()
    assert _error_code(evaluated.evidence) == "retrieval_delivery_live_injection"
