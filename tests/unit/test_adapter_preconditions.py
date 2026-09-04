from __future__ import annotations

import asyncio

import pytest

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="adapter-preconditions",
        instructions="Follow the evaluation contract.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="precondition-test",
        adapter_version="1",
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="adapter.precondition",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Exercise adapter precondition handling.",
        authority=AuthorityPolicy(),
    )


class PreconditionAdapter:
    @property
    def name(self) -> str:
        return "precondition-test"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        raise AdapterPreconditionError(
            code="fixture_unavailable",
            reason="controlled evaluation fixture is unavailable",
        )


def test_adapter_precondition_error_exposes_only_bounded_structured_fields() -> None:
    error = AdapterPreconditionError(
        code="fixture_unavailable",
        reason="controlled evaluation fixture is unavailable",
    )

    assert error.code == "fixture_unavailable"
    assert error.reason == "controlled evaluation fixture is unavailable"
    assert str(error) == error.reason


@pytest.mark.parametrize("code", ["", "UPPER", "bad-code", "space code"])
def test_adapter_precondition_error_rejects_invalid_codes(code: str) -> None:
    with pytest.raises(ValueError, match="lowercase alphanumeric/underscore"):
        AdapterPreconditionError(code=code, reason="safe reason")


@pytest.mark.parametrize("reason", ["", "x" * 513])
def test_adapter_precondition_error_rejects_missing_or_oversized_reason(reason: str) -> None:
    with pytest.raises(ValueError, match=r"1\.\.512"):
        AdapterPreconditionError(code="fixture_unavailable", reason=reason)


def test_trial_runner_classifies_adapter_precondition_as_blocked_evaluation_error() -> None:
    result = asyncio.run(
        TrialRunner().run(
            PreconditionAdapter(),
            subject=subject(),
            scenario=scenario(),
            trial_id="precondition-blocked",
        )
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.critical_violations == 0
    assert len(result.evidence.events) == 1
    event = result.evidence.events[0]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.source == "adapter:precondition-test"
    assert event.critical is True
    assert event.payload == {
        "code": "fixture_unavailable",
        "reason": "controlled evaluation fixture is unavailable",
    }
