from __future__ import annotations

from dataclasses import dataclass
from time import sleep

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner


def _subject(*, adapter: str) -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="fixture",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter=adapter,
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="runtime.metric-provenance-deadline",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Keep provenance validation inside the evaluator deadline",
    )


@dataclass
class _SlowProvenanceAdapter:
    executed: bool = False

    @property
    def name(self) -> str:
        return "slow-metric-provenance"

    @property
    def metric_provenance_assertion(self) -> dict[str, object]:
        sleep(0.02)
        return {"token_source": "fixture:slow-provenance"}

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        self.executed = True
        return AdapterResult(input_tokens=99)


@pytest.mark.asyncio
async def test_metric_provenance_validation_consumes_evaluator_deadline() -> None:
    adapter = _SlowProvenanceAdapter()

    result = await TrialRunner(deadline_seconds=0.001).run(
        adapter,
        subject=_subject(adapter=adapter.name),
        scenario=_scenario(),
        trial_id="metric-provenance-deadline",
    )

    assert adapter.executed is False
    assert result.verdict is TrialVerdict.BLOCKED
    assert result.evidence.input_tokens == 0
    assert result.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert result.evidence.events[0].payload["code"] == "trial_deadline_exceeded"
    assert result.evaluator_elapsed_ms is not None
    assert result.evaluator_elapsed_ms >= 1.0


@dataclass
class _MalformedNameAdapter:
    executed: bool = False

    @property
    def name(self) -> str:
        return " malformed-adapter "

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        self.executed = True
        return AdapterResult(input_tokens=99)


@pytest.mark.asyncio
async def test_malformed_adapter_identity_fails_closed_before_execution() -> None:
    adapter = _MalformedNameAdapter()

    result = await TrialRunner().run(
        adapter,
        subject=_subject(adapter="malformed-adapter"),
        scenario=_scenario(),
        trial_id="malformed-adapter-name",
    )

    assert adapter.executed is False
    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert result.evidence.events[0].payload == {
        "code": "invalid_metric_provenance",
        "reason": "adapter metric provenance assertion is invalid or unbounded",
    }
