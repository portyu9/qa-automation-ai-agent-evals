from __future__ import annotations

from dataclasses import replace

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.runtime.session import EvaluationSession, IndependenceStatus


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="independence-status-v1",
        instructions="Return the expected state.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="scripted",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="session.independence",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Exercise repeated-trial independence qualification.",
        required_outcomes={"status": "ok"},
    )


def _adapter(calls: list[str] | None = None) -> ScriptedAdapter:
    def script(
        _subject_value: SubjectFingerprint,
        _scenario_value: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        if calls is not None:
            calls.append(trial_id)
        return AdapterResult(final_state={"status": "ok"})

    return ScriptedAdapter(script)


@pytest.mark.asyncio
async def test_session_defaults_to_unverified_independence() -> None:
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=3,
        k=2,
        campaign_id="independence-default",
    )

    assert evaluated.independence_status is IndependenceStatus.UNVERIFIED
    assert evaluated.independence_basis is None
    assert evaluated.reliability.pass_at_k == 1.0
    assert evaluated.reliability.pass_power_k == 1.0
    with pytest.raises(ValueError, match="session independence is unverified"):
        evaluated.independence_qualified_metrics()


@pytest.mark.asyncio
async def test_operator_assertion_qualifies_metrics_without_becoming_verified() -> None:
    basis = "Operator resets the isolated test fixture and application state between attempts."
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=3,
        k=2,
        campaign_id="independence-operator-asserted",
        independence_status=IndependenceStatus.OPERATOR_ASSERTED,
        independence_basis=basis,
    )

    metrics = evaluated.independence_qualified_metrics()

    assert evaluated.independence_status is IndependenceStatus.OPERATOR_ASSERTED
    assert metrics.status is IndependenceStatus.OPERATOR_ASSERTED
    assert metrics.basis == basis
    assert metrics.k == evaluated.reliability.k
    assert metrics.pass_at_k == evaluated.reliability.pass_at_k
    assert metrics.pass_power_k == evaluated.reliability.pass_power_k


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "basis", "message"),
    [
        (
            IndependenceStatus.OPERATOR_ASSERTED,
            None,
            "operator_asserted independence requires",
        ),
        (
            IndependenceStatus.OPERATOR_ASSERTED,
            " surrounding whitespace ",
            "operator_asserted independence requires",
        ),
        (
            IndependenceStatus.UNVERIFIED,
            "operator says reset",
            "unverified independence must not carry",
        ),
        (
            IndependenceStatus.VERIFIED,
            "claimed reset receipt",
            "verified independence requires evaluator-owned reset/isolation receipt verification",
        ),
        (
            "operator_asserted",
            "operator says reset",
            "independence_status must be an exact IndependenceStatus member",
        ),
    ],
)
async def test_invalid_independence_metadata_fails_before_adapter_execution(
    status: object,
    basis: str | None,
    message: str,
) -> None:
    calls: list[str] = []

    with pytest.raises(ValueError, match=message):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=2,
            independence_status=status,  # type: ignore[arg-type]
            independence_basis=basis,
        )

    assert calls == []


@pytest.mark.asyncio
async def test_direct_result_cannot_self_elevate_to_verified_independence() -> None:
    evaluated = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
    )
    forged = replace(
        evaluated,
        independence_status=IndependenceStatus.VERIFIED,
        independence_basis="caller-created receipt claim",
    )

    with pytest.raises(
        ValueError,
        match="verified independence requires evaluator-owned reset/isolation receipt verification",
    ):
        forged.validate()


@pytest.mark.asyncio
async def test_independence_basis_is_bounded_before_adapter_execution() -> None:
    calls: list[str] = []

    with pytest.raises(ValueError, match="independence_basis must be at most"):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=1,
            independence_status=IndependenceStatus.OPERATOR_ASSERTED,
            independence_basis="x" * 2_001,
        )

    assert calls == []
