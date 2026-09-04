from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="scripted",
        adapter_version="1",
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="metrics.runtime",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Validate normalized terminal metrics",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("elapsed_ms", float("nan")),
        ("elapsed_ms", float("inf")),
        ("elapsed_ms", float("-inf")),
        ("estimated_cost_usd", float("nan")),
        ("estimated_cost_usd", float("inf")),
        ("estimated_cost_usd", float("-inf")),
    ],
)
def test_trial_evidence_rejects_nonfinite_terminal_metrics(field: str, value: float) -> None:
    data = {
        "trial_id": "metrics",
        "subject_identity": SUBJECT,
        "scenario_identity": SCENARIO,
        field: value,
    }
    with pytest.raises(ValidationError):
        TrialEvidence.model_validate(data)


def test_trial_evidence_accepts_finite_terminal_metrics() -> None:
    evidence = TrialEvidence(
        trial_id="finite-metrics",
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        elapsed_ms=12,
        estimated_cost_usd=0.125,
    )

    assert evidence.elapsed_ms == 12.0
    assert evidence.estimated_cost_usd == 0.125
    assert evidence.evidence_root


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_result",
    [
        AdapterResult(elapsed_ms=float("inf")),
        AdapterResult(estimated_cost_usd=float("inf")),
    ],
)
async def test_runtime_blocks_nonfinite_adapter_terminal_metrics(
    adapter_result: AdapterResult,
) -> None:
    adapter = ScriptedAdapter(lambda _subject, _scenario, _trial: adapter_result)

    result = await TrialRunner().run(
        adapter,
        subject=subject(),
        scenario=scenario(),
        trial_id="nonfinite-metric",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.estimated_cost_usd == 0.0
    assert result.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert result.evidence.events[0].payload == {
        "code": "invalid_adapter_result",
        "reason": "adapter result failed normalized evidence validation",
    }
    assert result.evidence.evidence_root
