from __future__ import annotations

import json

import pytest

from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.side_effect.models import SideEffectIdempotencySpec, canonical_json_sha256
from agent_evals.side_effect.receipt import SideEffectAttemptDigest, SideEffectIdempotencyReceipt
from agent_evals.side_effect.verification import (
    SideEffectObservationError,
    verify_side_effect_observation,
)


def _spec() -> SideEffectIdempotencySpec:
    return SideEffectIdempotencySpec(
        tool="apply_change",
        key_argument="operation_id",
        expected_arguments={"operation_id": "op-7", "value": 3},
    )


def _scenario(*, with_spec: bool = True) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="side-effect.fail-closed",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Observe one duplicate logical operation.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"apply_change"})),
        side_effect_idempotency=_spec() if with_spec else None,
    )


def _receipt() -> SideEffectIdempotencyReceipt:
    spec = _spec()
    before = canonical_json_sha256({"effects": []})
    after = canonical_json_sha256({"effects": ["op-7"]})
    attempts = (
        SideEffectAttemptDigest(
            ordinal=1,
            call_id="call-1",
            arguments_sha256=spec.expected_arguments_sha256,
            key_sha256=spec.key_sha256,
            before_effect_sha256=before,
            after_effect_sha256=after,
            mutated=True,
        ),
        SideEffectAttemptDigest(
            ordinal=2,
            call_id="call-2",
            arguments_sha256=spec.expected_arguments_sha256,
            key_sha256=spec.key_sha256,
            before_effect_sha256=after,
            after_effect_sha256=after,
            mutated=False,
        ),
    )
    return SideEffectIdempotencyReceipt.create(
        scenario_identity=_scenario().identity,
        contract=spec,
        attempts=attempts,
    )


def _events(receipt: SideEffectIdempotencyReceipt) -> tuple[EvidenceEvent, ...]:
    arguments = json.dumps(_spec().expected_arguments, separators=(",", ":"))
    return (
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.TOOL_REQUEST,
            source="test",
            payload={"tool": "apply_change", "call_id": "call-1", "arguments": arguments},
        ),
        EvidenceEvent(
            sequence=1,
            kind=EvidenceKind.TOOL_RESULT,
            source="test",
            payload={"tool": "apply_change", "call_id": "call-1", "output": "created"},
        ),
        EvidenceEvent(
            sequence=2,
            kind=EvidenceKind.TOOL_REQUEST,
            source="test",
            payload={"tool": "apply_change", "call_id": "call-2", "arguments": arguments},
        ),
        EvidenceEvent(
            sequence=3,
            kind=EvidenceKind.TOOL_RESULT,
            source="test",
            payload={"tool": "apply_change", "call_id": "call-2", "output": "duplicate"},
        ),
        receipt.to_event(sequence=4),
    )


def _evidence(events: tuple[EvidenceEvent, ...], *, scenario: EvaluationScenario) -> TrialEvidence:
    return TrialEvidence(
        trial_id="fail-closed",
        subject_identity="2" * 64,
        scenario_identity=scenario.identity,
        events=events,
    )


def test_unconfigured_scenario_rejects_side_effect_observation() -> None:
    configured = _scenario()
    unconfigured = _scenario(with_spec=False)
    evidence = _evidence(_events(_receipt()), scenario=unconfigured).model_copy(
        update={"scenario_identity": unconfigured.identity}
    )

    with pytest.raises(SideEffectObservationError, match="does not configure"):
        verify_side_effect_observation(unconfigured, evidence)

    assert configured.identity != unconfigured.identity


def test_receipt_root_tampering_is_blocked() -> None:
    scenario = _scenario()
    events = list(_events(_receipt()))
    payload = dict(events[-1].payload)
    payload["receipt_root"] = "0" * 64
    events[-1] = events[-1].model_copy(update={"payload": payload})

    with pytest.raises(SideEffectObservationError, match="malformed"):
        verify_side_effect_observation(scenario, _evidence(tuple(events), scenario=scenario))


def test_request_call_order_tampering_is_blocked() -> None:
    scenario = _scenario()
    events = list(_events(_receipt()))
    first_payload = dict(events[0].payload)
    second_payload = dict(events[2].payload)
    first_payload["call_id"] = "call-2"
    second_payload["call_id"] = "call-1"
    events[0] = events[0].model_copy(update={"payload": first_payload})
    events[2] = events[2].model_copy(update={"payload": second_payload})

    with pytest.raises(SideEffectObservationError, match="call identity"):
        verify_side_effect_observation(scenario, _evidence(tuple(events), scenario=scenario))


def test_same_key_with_changed_arguments_is_blocked() -> None:
    scenario = _scenario()
    events = list(_events(_receipt()))
    payload = dict(events[2].payload)
    payload["arguments"] = '{"operation_id":"op-7","value":4}'
    events[2] = events[2].model_copy(update={"payload": payload})

    with pytest.raises(SideEffectObservationError, match="scenario-bound logical operation"):
        verify_side_effect_observation(scenario, _evidence(tuple(events), scenario=scenario))


def test_different_logical_key_is_blocked() -> None:
    scenario = _scenario()
    events = list(_events(_receipt()))
    payload = dict(events[2].payload)
    payload["arguments"] = '{"operation_id":"op-8","value":3}'
    events[2] = events[2].model_copy(update={"payload": payload})

    with pytest.raises(SideEffectObservationError, match="scenario-bound logical operation"):
        verify_side_effect_observation(scenario, _evidence(tuple(events), scenario=scenario))
