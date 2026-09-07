from __future__ import annotations

import pytest

from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.retrieval.models import (
    RetrievalChunkSpec,
    RetrievalContractSpec,
    RetrievalCorpusSpec,
    RetrievalQuerySpec,
)
from agent_evals.runtime.preconditions import (
    EvaluationPreconditionError,
    _verify_composed_handoff_provenance,
)
from agent_evals.side_effect.models import SideEffectIdempotencySpec

_SUBJECT = "a" * 64
_ROOT = "Root agent"
_TOOL = "lookup"


def _authority() -> AuthorityPolicy:
    return AuthorityPolicy(
        allowed_tools=frozenset({_TOOL}),
        root_agent=_ROOT,
    )


def _scenario(**overrides: object) -> EvaluationScenario:
    material: dict[str, object] = {
        "scenario_id": "composition.handoff-provenance",
        "revision": "1",
        "kind": ScenarioKind.SECURITY,
        "objective": "Exercise a specialized runtime relation under delegated authority.",
        "authority": _authority(),
    }
    material.update(overrides)
    return EvaluationScenario.model_validate(material)


def _retrieval_contract() -> RetrievalContractSpec:
    return RetrievalContractSpec(
        corpus=RetrievalCorpusSpec(
            corpus_id="composition-corpus",
            revision="1",
            chunks=(
                RetrievalChunkSpec(
                    chunk_id="chunk-1",
                    document_id="document-1",
                    source="controlled://composition",
                    content="Evaluator-bound retrieval context.",
                ),
            ),
        ),
        query=RetrievalQuerySpec(query="bound context", top_k=1),
        tool_name=_TOOL,
    )


def _evidence(
    scenario: EvaluationScenario,
    *events: EvidenceEvent,
) -> TrialEvidence:
    return TrialEvidence(
        trial_id="composed-handoff-provenance",
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        events=events,
    )


@pytest.mark.parametrize(
    "scenario",
    [
        _scenario(retrieval=_retrieval_contract()),
        _scenario(
            side_effect_idempotency=SideEffectIdempotencySpec(
                tool=_TOOL,
                key_argument="operation_id",
                expected_arguments={"operation_id": "op-1"},
            )
        ),
    ],
)
def test_specialized_scenario_blocks_missing_tool_request_agent_provenance(
    scenario: EvaluationScenario,
) -> None:
    evidence = _evidence(
        scenario,
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.TOOL_REQUEST,
            source="openai-agents:tool-request",
            payload={"tool": _TOOL, "call_id": "call-1", "arguments": "{}"},
        ),
    )

    with pytest.raises(EvaluationPreconditionError) as captured:
        _verify_composed_handoff_provenance(scenario, evidence)

    assert captured.value.source == "evaluator:handoff-provenance"
    assert captured.value.code == "handoff_provenance_unverified"
    assert "tool_request" in captured.value.reason


def test_protocol_bridge_activates_composed_provenance_requirement() -> None:
    scenario = _scenario()
    evidence = _evidence(
        scenario,
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.PROTOCOL_DELIVERY,
            source="bridge:mcp-agent:test",
            payload={"bridge": "already verified by the preceding protocol precondition"},
        ),
        EvidenceEvent(
            sequence=1,
            kind=EvidenceKind.TOOL_RESULT,
            source="openai-agents:tool-result",
            payload={"tool": _TOOL, "call_id": "call-1", "output": "ok"},
        ),
    )

    with pytest.raises(EvaluationPreconditionError) as captured:
        _verify_composed_handoff_provenance(scenario, evidence)

    assert captured.value.code == "handoff_provenance_unverified"
    assert "tool_result" in captured.value.reason


def test_specialized_handoff_provenance_accepts_stable_agent_and_transition_identities() -> None:
    scenario = _scenario(retrieval=_retrieval_contract())
    evidence = _evidence(
        scenario,
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.HANDOFF,
            source="openai-agents:handoff",
            payload={"source_agent": _ROOT, "target_agent": "Specialist agent"},
        ),
        EvidenceEvent(
            sequence=1,
            kind=EvidenceKind.TOOL_REQUEST,
            source="openai-agents:tool-request",
            payload={
                "agent": "Specialist agent",
                "tool": _TOOL,
                "call_id": "call-1",
                "arguments": "{}",
            },
        ),
        EvidenceEvent(
            sequence=2,
            kind=EvidenceKind.TOOL_RESULT,
            source="openai-agents:tool-result",
            payload={
                "agent": "Specialist agent",
                "tool": _TOOL,
                "call_id": "call-1",
                "output": "ok",
            },
        ),
    )

    _verify_composed_handoff_provenance(scenario, evidence)


def test_ordinary_handoff_scenario_preserves_existing_deterministic_policy_contract() -> None:
    scenario = _scenario()
    evidence = _evidence(
        scenario,
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.TOOL_REQUEST,
            source="openai-agents:tool-request",
            payload={"tool": _TOOL, "call_id": "call-1", "arguments": "{}"},
        ),
    )

    _verify_composed_handoff_provenance(scenario, evidence)
