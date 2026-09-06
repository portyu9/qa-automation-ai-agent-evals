from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.openai_side_effect_idempotency import (
    OpenAIAgentsSideEffectIdempotencyAdapter,
)
from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.side_effect.models import SideEffectIdempotencySpec, canonical_json_sha256
from agent_evals.side_effect.receipt import SideEffectAttemptDigest, SideEffectIdempotencyReceipt
from agent_evals.side_effect.verification import verify_side_effect_observation


def _spec() -> SideEffectIdempotencySpec:
    return SideEffectIdempotencySpec(
        tool="apply_change",
        key_argument="operation_id",
        expected_arguments={"operation_id": "op-7", "value": 3},
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="side-effect.live-authority",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Apply one logical operation twice without a duplicate physical effect.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"apply_change"}),
            max_tool_calls=2,
        ),
        side_effect_idempotency=_spec(),
    )


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="side-effect-authority-test",
        model="subject-model",
        application_revision="rev-1",
        instructions="Apply the controlled operation twice.",
        tool_schema={"apply_change": {"operation_id": "string", "value": "integer"}},
        policy={"allowed": ["apply_change"]},
        memory_policy={"retention": "trial"},
        adapter="side-effect-live-static",
        adapter_version="1",
    )


def _fabricated_passing_receipt() -> SideEffectIdempotencyReceipt:
    scenario = _scenario()
    spec = _spec()
    before = canonical_json_sha256({"effects": []})
    after_first = canonical_json_sha256({"effects": [{"operation_id": "op-7", "value": 3}]})
    return SideEffectIdempotencyReceipt.create(
        scenario_identity=scenario.identity,
        contract=spec,
        attempts=(
            SideEffectAttemptDigest(
                ordinal=1,
                call_id="call-1",
                arguments_sha256=spec.expected_arguments_sha256,
                key_sha256=spec.key_sha256,
                before_effect_sha256=before,
                after_effect_sha256=after_first,
                mutated=True,
            ),
            SideEffectAttemptDigest(
                ordinal=2,
                call_id="call-2",
                arguments_sha256=spec.expected_arguments_sha256,
                key_sha256=spec.key_sha256,
                before_effect_sha256=after_first,
                after_effect_sha256=after_first,
                mutated=False,
            ),
        ),
    )


def _evidence(*, subject: SubjectFingerprint, trial_id: str) -> TrialEvidence:
    scenario = _scenario()
    arguments = json.dumps(_spec().expected_arguments, separators=(",", ":"))
    receipt = _fabricated_passing_receipt()
    return TrialEvidence(
        trial_id=trial_id,
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.TOOL_REQUEST,
                source="adapter:test",
                payload={
                    "tool": "apply_change",
                    "call_id": "call-1",
                    "arguments": arguments,
                },
            ),
            EvidenceEvent(
                sequence=1,
                kind=EvidenceKind.TOOL_RESULT,
                source="adapter:test",
                payload={
                    "tool": "apply_change",
                    "call_id": "call-1",
                    "output": "created",
                },
            ),
            EvidenceEvent(
                sequence=2,
                kind=EvidenceKind.TOOL_REQUEST,
                source="adapter:test",
                payload={
                    "tool": "apply_change",
                    "call_id": "call-2",
                    "arguments": arguments,
                },
            ),
            EvidenceEvent(
                sequence=3,
                kind=EvidenceKind.TOOL_RESULT,
                source="adapter:test",
                payload={
                    "tool": "apply_change",
                    "call_id": "call-2",
                    "output": "duplicate",
                },
            ),
            receipt.to_event(sequence=4),
        ),
    )


@dataclass(slots=True)
class _GenericLiveAdapter:
    evidence: TrialEvidence

    @property
    def name(self) -> str:
        return "side-effect-live-static"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        return AdapterResult(
            events=self.evidence.events,
            final_state=self.evidence.final_state,
            final_output=self.evidence.final_output,
        )


class _ObserverSubclass(OpenAIAgentsSideEffectIdempotencyAdapter):
    def __init__(self, evidence: TrialEvidence) -> None:
        self._test_evidence = evidence

    @property
    def name(self) -> str:
        return "side-effect-observer-subclass"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        return AdapterResult(
            events=self._test_evidence.events,
            final_state=self._test_evidence.final_state,
            final_output=self._test_evidence.final_output,
        )


def test_fabricated_receipt_is_internally_gradeable_without_producer_authority() -> None:
    subject = _subject()
    scenario = _scenario()
    evidence = _evidence(subject=subject, trial_id="side-effect-direct-control")
    receipt = verify_side_effect_observation(scenario, evidence)

    assert receipt is not None
    assert receipt.mutation_count == 1
    assert receipt.attempts[0].mutated is True
    assert receipt.attempts[1].mutated is False
    assert all(
        result.verdict is TrialVerdict.PASS
        for result in grade_deterministic_evidence(scenario, evidence)
    )


@pytest.mark.asyncio
async def test_generic_live_adapter_cannot_self_author_passing_side_effect_observation() -> None:
    subject = _subject()
    scenario = _scenario()
    trial_id = "side-effect-live-injection"
    evidence = _evidence(subject=subject, trial_id=trial_id)

    result = await TrialRunner().run(
        _GenericLiveAdapter(evidence),
        subject=subject,
        scenario=scenario,
        trial_id=trial_id,
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.events[-2].kind is EvidenceKind.SIDE_EFFECT_OBSERVATION
    assert result.evidence.events[-1].kind is EvidenceKind.EVALUATION_ERROR
    assert result.evidence.events[-1].payload["code"] == "side_effect_observation_live_injection"


@pytest.mark.asyncio
async def test_exact_evidence_replay_preserves_historical_side_effect_observation() -> None:
    subject = _subject()
    scenario = _scenario()
    trial_id = "side-effect-exact-replay"
    evidence = _evidence(subject=subject, trial_id=trial_id)

    result = await TrialRunner().run(
        EvidenceReplayAdapter(evidence),
        subject=subject,
        scenario=scenario,
        trial_id=trial_id,
    )

    assert result.verdict is TrialVerdict.PASS
    assert tuple(oracle.name for oracle in result.oracle_results) == (
        "policy",
        "side-effect-idempotency",
        "outcome",
    )
    assert all(oracle.verdict is TrialVerdict.PASS for oracle in result.oracle_results)
    assert result.evidence == evidence
    assert result.evidence.evidence_root == evidence.evidence_root


@pytest.mark.asyncio
async def test_side_effect_observer_subclass_cannot_inherit_live_observation_authority() -> None:
    subject = _subject()
    scenario = _scenario()
    trial_id = "side-effect-observer-subclass"
    evidence = _evidence(subject=subject, trial_id=trial_id)

    result = await TrialRunner().run(
        _ObserverSubclass(evidence),
        subject=subject,
        scenario=scenario,
        trial_id=trial_id,
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.events[-1].payload["code"] == "side_effect_observation_live_injection"
