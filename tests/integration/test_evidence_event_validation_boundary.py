from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner

SUBJECT_IDENTITY = "a" * 64
SCENARIO_IDENTITY = "b" * 64


def _event() -> EvidenceEvent:
    return EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.STATE,
        source="adapter",
        payload={"status": "observed"},
        critical=False,
    )


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="boundary-test",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={"retention": "none"},
        adapter="malformed-event",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="evidence.scalar-boundary",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Reject malformed evidence event scalar types",
    )


@pytest.mark.parametrize("invalid", ["0", 0.0, True])
def test_evidence_event_rejects_non_integer_sequence_surrogates(invalid: object) -> None:
    data = _event().model_dump(mode="python")
    data["sequence"] = invalid

    with pytest.raises(ValidationError):
        EvidenceEvent.model_validate(data)


@pytest.mark.parametrize("invalid", ["false", "true", 0, 1])
def test_evidence_event_rejects_non_boolean_criticality_surrogates(invalid: object) -> None:
    data = _event().model_dump(mode="python")
    data["critical"] = invalid

    with pytest.raises(ValidationError):
        EvidenceEvent.model_validate(data)


def test_trial_evidence_revalidates_existing_event_instances() -> None:
    unsafe = _event().model_copy(update={"sequence": "0", "critical": "false"})

    with pytest.raises(ValidationError):
        TrialEvidence(
            trial_id="trial-unsafe-event",
            subject_identity=SUBJECT_IDENTITY,
            scenario_identity=SCENARIO_IDENTITY,
            events=(unsafe,),
        )


def test_valid_evidence_event_json_round_trip_remains_supported() -> None:
    event = _event()

    assert EvidenceEvent.model_validate_json(event.model_dump_json()) == event


class MalformedEventAdapter:
    @property
    def name(self) -> str:
        return "malformed-event"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        malformed = cast(
            EvidenceEvent,
            {
                "sequence": "0",
                "kind": EvidenceKind.STATE.value,
                "source": "adapter",
                "payload": {"status": "observed"},
                "critical": "false",
            },
        )
        return AdapterResult(events=(malformed,))


@pytest.mark.asyncio
async def test_runtime_blocks_malformed_event_scalars_before_oracle_grading() -> None:
    result = await TrialRunner().run(
        MalformedEventAdapter(),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="trial-malformed-event",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.final_state == {}
    assert len(result.evidence.events) == 1
    event = result.evidence.events[0]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.source == "evaluator:adapter:malformed-event"
    assert event.critical is True
    assert event.payload == {
        "code": "invalid_adapter_result",
        "reason": "adapter result failed normalized evidence validation",
    }
