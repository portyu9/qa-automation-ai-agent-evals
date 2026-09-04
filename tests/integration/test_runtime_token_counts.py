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
        scenario_id="tokens.runtime",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Validate normalized token counts",
    )


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
@pytest.mark.parametrize("value", [True, "7", 7.0, 7.5])
def test_trial_evidence_rejects_coercive_token_count_types(field: str, value: object) -> None:
    data = {
        "trial_id": "tokens",
        "subject_identity": SUBJECT,
        "scenario_identity": SCENARIO,
        field: value,
    }

    with pytest.raises(ValidationError):
        TrialEvidence.model_validate(data)


def test_trial_evidence_accepts_integer_token_counts() -> None:
    evidence = TrialEvidence(
        trial_id="valid-tokens",
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        input_tokens=7,
        output_tokens=3,
    )

    assert evidence.input_tokens == 7
    assert evidence.output_tokens == 3
    assert evidence.evidence_root


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_result",
    [
        AdapterResult(input_tokens="7"),  # type: ignore[arg-type]
        AdapterResult(output_tokens=True),
    ],
)
async def test_runtime_blocks_coercive_adapter_token_counts(adapter_result: AdapterResult) -> None:
    adapter = ScriptedAdapter(lambda _subject, _scenario, _trial: adapter_result)

    result = await TrialRunner().run(
        adapter,
        subject=subject(),
        scenario=scenario(),
        trial_id="invalid-token-count",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.input_tokens == 0
    assert result.evidence.output_tokens == 0
    assert result.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert result.evidence.events[0].payload == {
        "code": "invalid_adapter_result",
        "reason": "adapter result failed normalized evidence validation",
    }
    assert result.evidence.evidence_root
