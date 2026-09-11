from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.runtime.reset_isolation import (
    ResetIsolationContext,
    ResetIsolationError,
    ResetIsolationObservation,
    ResetIsolationReceipt,
)
from agent_evals.runtime.session import EvaluationSession, IndependenceStatus


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="verified-reset-v1",
        instructions="Return the expected state.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="subject-adapter",
        adapter_version="7",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="session.verified-reset",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Exercise evaluator-owned between-attempt reset evidence.",
        required_outcomes={"status": "ok"},
    )


def _adapter(calls: list[str]) -> ScriptedAdapter:
    def script(
        _subject_value: SubjectFingerprint,
        _scenario_value: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        calls.append(trial_id)
        return AdapterResult(final_state={"status": "ok"})

    return ScriptedAdapter(script, name="runtime-scripted")


class _Control:
    strategy_name = "fixture-reset"
    strategy_version = "2"

    def __init__(self) -> None:
        self.contexts: list[ResetIsolationContext] = []

    async def reset(self, *, context: ResetIsolationContext) -> ResetIsolationObservation:
        self.contexts.append(context)
        return ResetIsolationObservation(
            control_evidence_identity=_sha(
                f"{context.campaign_id}:{context.attempt_index}:{context.previous_evidence_root}"
            )
        )


class _FailingControl(_Control):
    async def reset(self, *, context: ResetIsolationContext) -> ResetIsolationObservation:
        self.contexts.append(context)
        raise RuntimeError("secret provider detail must not become the public error")


class _MalformedObservationControl(_Control):
    async def reset(self, *, context: ResetIsolationContext) -> object:
        self.contexts.append(context)
        return {"control_evidence_identity": _sha("not-a-typed-observation")}


@pytest.mark.asyncio
async def test_verified_campaign_binds_every_between_attempt_transition() -> None:
    calls: list[str] = []
    control = _Control()

    evaluated = await EvaluationSession().run(
        _adapter(calls),
        subject=_subject(),
        scenario=_scenario(),
        trials=3,
        k=2,
        campaign_id="verified-campaign",
        independence_status=IndependenceStatus.VERIFIED,
        reset_control=control,
    )

    assert calls == [
        "campaign:verified-campaign:attempt:0000",
        "campaign:verified-campaign:attempt:0001",
        "campaign:verified-campaign:attempt:0002",
    ]
    assert len(control.contexts) == 2
    assert [context.attempt_index for context in control.contexts] == [1, 2]
    assert [context.previous_trial_id for context in control.contexts] == calls[:2]
    assert [context.next_trial_id for context in control.contexts] == calls[1:]
    assert all(context.subject_identity == _subject().identity for context in control.contexts)
    assert all(context.scenario_identity == _scenario().identity for context in control.contexts)
    assert all(context.runtime_adapter_name == "runtime-scripted" for context in control.contexts)
    assert all(context.subject_adapter == "subject-adapter" for context in control.contexts)
    assert all(context.subject_adapter_version == "7" for context in control.contexts)

    assert evaluated.independence_status is IndependenceStatus.VERIFIED
    assert evaluated.independence_basis is None
    assert evaluated.reset_strategy_name == "fixture-reset"
    assert evaluated.reset_strategy_version == "2"
    assert len(evaluated.reset_isolation_receipts) == 2
    evaluated.validate()

    metrics = evaluated.independence_qualified_metrics()
    assert metrics.status is IndependenceStatus.VERIFIED
    assert metrics.basis is None
    assert metrics.reset_strategy_name == "fixture-reset"
    assert metrics.reset_strategy_version == "2"
    assert metrics.reset_receipt_roots == tuple(
        receipt.receipt_root for receipt in evaluated.reset_isolation_receipts
    )
    assert metrics.pass_at_k == evaluated.reliability.pass_at_k
    assert metrics.pass_power_k == evaluated.reliability.pass_power_k


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trials", "control", "match"),
    (
        (2, None, "requires a reset/isolation control"),
        (1, _Control(), "at least two trials"),
    ),
)
async def test_verified_request_fails_before_subject_execution(
    trials: int,
    control: _Control | None,
    match: str,
) -> None:
    calls: list[str] = []

    with pytest.raises(ValueError, match=match):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=trials,
            independence_status=IndependenceStatus.VERIFIED,
            reset_control=control,
        )

    assert calls == []


@pytest.mark.asyncio
async def test_non_verified_session_rejects_reset_control_before_execution() -> None:
    calls: list[str] = []

    with pytest.raises(ValueError, match="only for verified independence"):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=2,
            reset_control=_Control(),
        )

    assert calls == []


@pytest.mark.asyncio
async def test_verified_session_rejects_operator_basis_before_execution() -> None:
    calls: list[str] = []

    with pytest.raises(ValueError, match="must not carry an operator assertion basis"):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=2,
            independence_status=IndependenceStatus.VERIFIED,
            independence_basis="operator says reset happened",
            reset_control=_Control(),
        )

    assert calls == []


@pytest.mark.asyncio
async def test_reset_failure_stops_before_affected_next_trial() -> None:
    calls: list[str] = []
    control = _FailingControl()

    with pytest.raises(ResetIsolationError, match="failed before attempt 1") as exc_info:
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=3,
            campaign_id="fail-before-next",
            independence_status=IndependenceStatus.VERIFIED,
            reset_control=control,
        )

    assert "secret provider detail" not in str(exc_info.value)
    assert calls == ["campaign:fail-before-next:attempt:0000"]
    assert len(control.contexts) == 1


@pytest.mark.asyncio
async def test_malformed_control_observation_stops_before_next_trial() -> None:
    calls: list[str] = []

    with pytest.raises(ResetIsolationError, match="exact ResetIsolationObservation"):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=2,
            campaign_id="malformed-observation",
            independence_status=IndependenceStatus.VERIFIED,
            reset_control=_MalformedObservationControl(),  # type: ignore[arg-type]
        )

    assert calls == ["campaign:malformed-observation:attempt:0000"]


@pytest.mark.asyncio
async def test_invalid_control_strategy_metadata_fails_before_subject_execution() -> None:
    calls: list[str] = []
    control = _Control()
    control.strategy_name = " bad "

    with pytest.raises(ResetIsolationError, match="strategy name"):
        await EvaluationSession().run(
            _adapter(calls),
            subject=_subject(),
            scenario=_scenario(),
            trials=2,
            independence_status=IndependenceStatus.VERIFIED,
            reset_control=control,
        )

    assert calls == []


@pytest.mark.asyncio
async def test_subject_adapter_cannot_be_the_reset_control_object() -> None:
    calls: list[str] = []

    class DualRoleAdapter(ScriptedAdapter):
        strategy_name = "forbidden-dual-role"
        strategy_version = "1"

        async def reset(self, *, context: ResetIsolationContext) -> ResetIsolationObservation:
            return ResetIsolationObservation(control_evidence_identity=_sha(context.next_trial_id))

    adapter = DualRoleAdapter(
        lambda _subject_value, _scenario_value, trial_id: (
            calls.append(trial_id) or AdapterResult(final_state={"status": "ok"})
        ),
        name="dual-role",
    )

    with pytest.raises(ValueError, match="separate from the subject adapter"):
        await EvaluationSession().run(
            adapter,
            subject=_subject(),
            scenario=_scenario(),
            trials=2,
            independence_status=IndependenceStatus.VERIFIED,
            reset_control=adapter,
        )

    assert calls == []


@pytest.mark.asyncio
async def test_verified_result_rejects_missing_and_replayed_receipts() -> None:
    evaluated = await EvaluationSession().run(
        _adapter([]),
        subject=_subject(),
        scenario=_scenario(),
        trials=3,
        campaign_id="receipt-sequence",
        independence_status=IndependenceStatus.VERIFIED,
        reset_control=_Control(),
    )

    with pytest.raises(ValueError, match="receipt sequence is invalid"):
        replace(
            evaluated,
            reset_isolation_receipts=evaluated.reset_isolation_receipts[:1],
        ).validate()

    replayed = (
        evaluated.reset_isolation_receipts[0],
        evaluated.reset_isolation_receipts[0],
    )
    with pytest.raises(ValueError, match="receipt sequence is invalid"):
        replace(evaluated, reset_isolation_receipts=replayed).validate()


@pytest.mark.asyncio
async def test_verified_result_rejects_cross_campaign_receipt_replay() -> None:
    first = await EvaluationSession().run(
        _adapter([]),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="campaign-one",
        independence_status=IndependenceStatus.VERIFIED,
        reset_control=_Control(),
    )
    second = await EvaluationSession().run(
        _adapter([]),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="campaign-two",
        independence_status=IndependenceStatus.VERIFIED,
        reset_control=_Control(),
    )

    with pytest.raises(ValueError, match="receipt sequence is invalid"):
        replace(
            second,
            reset_isolation_receipts=first.reset_isolation_receipts,
        ).validate()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    (
        "previous_trial",
        "next_trial",
        "subject",
        "runtime_adapter",
        "strategy",
        "previous_root",
    ),
)
async def test_verified_result_rejects_rebound_transition_receipt(mutation: str) -> None:
    evaluated = await EvaluationSession().run(
        _adapter([]),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="binding-probes",
        independence_status=IndependenceStatus.VERIFIED,
        reset_control=_Control(),
    )
    original = evaluated.reset_isolation_receipts[0]
    context = ResetIsolationContext(
        campaign_id=original.campaign_id,
        attempt_index=original.attempt_index,
        previous_trial_id=original.previous_trial_id,
        next_trial_id=original.next_trial_id,
        subject_identity=original.subject_identity,
        scenario_identity=original.scenario_identity,
        runtime_adapter_name=original.runtime_adapter_name,
        subject_adapter=original.subject_adapter,
        subject_adapter_version=original.subject_adapter_version,
        previous_evidence_root=original.previous_evidence_root,
    )
    strategy_name = original.reset_strategy_name

    if mutation == "previous_trial":
        context = replace(context, previous_trial_id="campaign:binding-probes:attempt:9999")
    elif mutation == "next_trial":
        context = replace(context, next_trial_id="campaign:binding-probes:attempt:9999")
    elif mutation == "subject":
        context = replace(context, subject_identity="f" * 64)
    elif mutation == "runtime_adapter":
        context = replace(context, runtime_adapter_name="other-runtime")
    elif mutation == "strategy":
        strategy_name = "other-reset-strategy"
    elif mutation == "previous_root":
        context = replace(context, previous_evidence_root="e" * 64)
    else:
        raise AssertionError(f"unhandled mutation: {mutation}")

    try:
        rebound = ResetIsolationReceipt.create(
            context=context,
            reset_strategy_name=strategy_name,
            reset_strategy_version=original.reset_strategy_version,
            control_evidence_identity=original.control_evidence_identity,
        )
    except ValidationError:
        return

    with pytest.raises(ValueError, match="receipt sequence is invalid"):
        replace(evaluated, reset_isolation_receipts=(rebound,)).validate()


def test_receipt_rejects_malformed_root() -> None:
    context = ResetIsolationContext(
        campaign_id="root-probe",
        attempt_index=1,
        previous_trial_id="campaign:root-probe:attempt:0000",
        next_trial_id="campaign:root-probe:attempt:0001",
        subject_identity="a" * 64,
        scenario_identity="b" * 64,
        runtime_adapter_name="runtime",
        subject_adapter="subject",
        subject_adapter_version="1",
        previous_evidence_root="c" * 64,
    )
    valid = ResetIsolationReceipt.create(
        context=context,
        reset_strategy_name="reset",
        reset_strategy_version="1",
        control_evidence_identity="d" * 64,
    )

    payload = valid.model_dump(mode="python")
    payload["receipt_root"] = "0" * 64
    with pytest.raises(ValidationError, match="receipt root mismatch"):
        ResetIsolationReceipt.model_validate(payload)
