from __future__ import annotations

from typing import Literal, cast

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner

SUBJECT_IDENTITY = "a" * 64
SCENARIO_IDENTITY = "b" * 64
MetricField = Literal["elapsed_ms", "estimated_cost_usd"]


def _evidence() -> TrialEvidence:
    return TrialEvidence(
        trial_id="trial-terminal-metric",
        subject_identity=SUBJECT_IDENTITY,
        scenario_identity=SCENARIO_IDENTITY,
        elapsed_ms=1.5,
        estimated_cost_usd=0.25,
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
        adapter="malformed-terminal-metric",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="evidence.terminal-metric-boundary",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Reject malformed terminal metric scalar types",
    )


@pytest.mark.parametrize("field", ["elapsed_ms", "estimated_cost_usd"])
@pytest.mark.parametrize("invalid", ["1.5", True])
def test_trial_evidence_rejects_terminal_metric_type_surrogates(
    field: MetricField,
    invalid: object,
) -> None:
    data = _evidence().model_dump(mode="python")
    data[field] = invalid

    with pytest.raises(ValidationError):
        TrialEvidence.model_validate(data)


@pytest.mark.parametrize("field", ["elapsed_ms", "estimated_cost_usd"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_trial_evidence_preserves_non_finite_metric_rejection(
    field: MetricField,
    invalid: float,
) -> None:
    data = _evidence().model_dump(mode="python")
    data[field] = invalid

    with pytest.raises(ValidationError):
        TrialEvidence.model_validate(data)


def test_trial_evidence_strict_float_metrics_accept_numeric_integers() -> None:
    evidence = TrialEvidence(
        trial_id="trial-integer-metrics",
        subject_identity=SUBJECT_IDENTITY,
        scenario_identity=SCENARIO_IDENTITY,
        elapsed_ms=1,
        estimated_cost_usd=2,
    )

    assert evidence.elapsed_ms == 1.0
    assert evidence.estimated_cost_usd == 2.0


def test_valid_terminal_metrics_json_round_trip_remains_supported() -> None:
    evidence = _evidence()

    assert TrialEvidence.model_validate_json(evidence.model_dump_json()) == evidence


class MalformedTerminalMetricAdapter:
    def __init__(self, field: MetricField, value: object) -> None:
        self._field = field
        self._value = value

    @property
    def name(self) -> str:
        return "malformed-terminal-metric"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        if self._field == "elapsed_ms":
            return AdapterResult(elapsed_ms=cast(float, self._value))
        return AdapterResult(estimated_cost_usd=cast(float, self._value))


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["elapsed_ms", "estimated_cost_usd"])
@pytest.mark.parametrize("invalid", ["1.5", True])
async def test_runtime_blocks_malformed_terminal_metrics_before_oracle_grading(
    field: MetricField,
    invalid: object,
) -> None:
    result = await TrialRunner().run(
        MalformedTerminalMetricAdapter(field, invalid),
        subject=_subject(),
        scenario=_scenario(),
        trial_id=f"trial-malformed-{field}",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.final_state == {}
    assert len(result.evidence.events) == 1
    event = result.evidence.events[0]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.source == "evaluator:adapter:malformed-terminal-metric"
    assert event.critical is True
    assert event.payload == {
        "code": "invalid_adapter_result",
        "reason": "adapter result failed normalized evidence validation",
    }
