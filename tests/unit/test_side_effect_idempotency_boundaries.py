from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.side_effect.models import SideEffectIdempotencySpec, canonical_json_sha256
from agent_evals.side_effect.oracle import SideEffectIdempotencyOracle
from agent_evals.side_effect.receipt import (
    SideEffectAttemptDigest,
    SideEffectIdempotencyReceipt,
    SideEffectReceiptError,
)
from agent_evals.side_effect.verification import (
    SideEffectObservationError,
    verify_side_effect_observation,
)


def _spec(*, require_first_mutation: bool = True) -> SideEffectIdempotencySpec:
    return SideEffectIdempotencySpec(
        tool="apply_change",
        key_argument="operation_id",
        expected_arguments={"operation_id": "op-7", "value": 3},
        require_first_mutation=require_first_mutation,
    )


def _scenario(*, spec: SideEffectIdempotencySpec | None = None) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="side-effect.boundaries",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Verify duplicate-attempt side-effect evidence boundaries.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"apply_change"})),
        side_effect_idempotency=spec or _spec(),
    )


def _attempt(
    ordinal: int,
    call_id: str,
    *,
    before: str,
    after: str,
    arguments_sha256: str | None = None,
    key_sha256: str | None = None,
    mutated: bool | None = None,
) -> SideEffectAttemptDigest:
    spec = _spec()
    return SideEffectAttemptDigest(
        ordinal=ordinal,
        call_id=call_id,
        arguments_sha256=arguments_sha256 or spec.expected_arguments_sha256,
        key_sha256=key_sha256 or spec.key_sha256,
        before_effect_sha256=before,
        after_effect_sha256=after,
        mutated=(before != after) if mutated is None else mutated,
    )


def _receipt() -> SideEffectIdempotencyReceipt:
    spec = _spec()
    empty = canonical_json_sha256({"effects": []})
    once = canonical_json_sha256({"effects": [{"operation_id": "op-7"}]})
    return SideEffectIdempotencyReceipt.create(
        scenario_identity=_scenario().identity,
        contract=spec,
        attempts=(
            _attempt(1, "call-1", before=empty, after=once),
            _attempt(2, "call-2", before=once, after=once),
        ),
    )


def _evidence(
    receipt: SideEffectIdempotencyReceipt | None = None,
    *,
    observation_source: str = "bridge:side-effect-idempotency",
    observation_critical: bool = False,
) -> TrialEvidence:
    scenario = _scenario()
    args = json.dumps(_spec().expected_arguments, separators=(",", ":"))
    observation = receipt or _receipt()
    return TrialEvidence(
        trial_id="side-effect-boundary-trial",
        subject_identity="1" * 64,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.TOOL_REQUEST,
                source="test",
                payload={"tool": "apply_change", "call_id": "call-1", "arguments": args},
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
                payload={"tool": "apply_change", "call_id": "call-2", "arguments": args},
            ),
            EvidenceEvent(
                sequence=3,
                kind=EvidenceKind.TOOL_RESULT,
                source="test",
                payload={"tool": "apply_change", "call_id": "call-2", "output": "duplicate"},
            ),
            EvidenceEvent(
                sequence=4,
                kind=EvidenceKind.SIDE_EFFECT_OBSERVATION,
                source=observation_source,
                payload=observation.model_dump(mode="json"),
                critical=observation_critical,
            ),
        ),
    )


def test_spec_rejects_whitespace_nonstring_object_keys_and_unsupported_values() -> None:
    with pytest.raises(ValidationError, match="surrounding whitespace"):
        SideEffectIdempotencySpec(
            tool=" apply_change",
            key_argument="operation_id",
            expected_arguments={"operation_id": "op-7"},
        )
    with pytest.raises(ValidationError, match="object keys must be strings"):
        SideEffectIdempotencySpec(
            tool="apply_change",
            key_argument="operation_id",
            expected_arguments={"operation_id": "op-7", 1: "bad"},  # type: ignore[dict-item]
        )
    with pytest.raises(ValidationError, match="unsupported side-effect JSON value type"):
        SideEffectIdempotencySpec(
            tool="apply_change",
            key_argument="operation_id",
            expected_arguments={"operation_id": "op-7", "bad": {1, 2}},
        )


def test_attempt_digest_rejects_incorrect_mutation_flag() -> None:
    before = canonical_json_sha256([])
    after = canonical_json_sha256([1])

    with pytest.raises(ValidationError, match="mutation flag disagrees"):
        _attempt(1, "call-1", before=before, after=after, mutated=False)


def test_receipt_shape_rejects_bad_ordinals_duplicate_calls_and_count_or_root_tampering() -> None:
    receipt = _receipt()
    payload = receipt.model_dump(mode="python")

    bad_ordinals = dict(payload)
    bad_ordinals["attempts"] = (
        receipt.attempts[1].model_copy(update={"call_id": "call-x"}),
        receipt.attempts[0].model_copy(update={"call_id": "call-y"}),
    )
    with pytest.raises(ValidationError, match="ordinals"):
        SideEffectIdempotencyReceipt.model_validate(bad_ordinals)

    duplicate_calls = dict(payload)
    duplicate_calls["attempts"] = (
        receipt.attempts[0],
        receipt.attempts[1].model_copy(update={"call_id": "call-1"}),
    )
    with pytest.raises(ValidationError, match="distinct call identities"):
        SideEffectIdempotencyReceipt.model_validate(duplicate_calls)

    wrong_count = dict(payload)
    wrong_count["mutation_count"] = 0
    with pytest.raises(ValidationError, match="mutation count disagrees"):
        SideEffectIdempotencyReceipt.model_validate(wrong_count)

    wrong_root = dict(payload)
    wrong_root["receipt_root"] = "0" * 64
    with pytest.raises(ValidationError, match="receipt root mismatch"):
        SideEffectIdempotencyReceipt.model_validate(wrong_root)


def test_receipt_shape_rejects_attempt_argument_and_key_drift() -> None:
    receipt = _receipt()
    payload = receipt.model_dump(mode="python")

    wrong_arguments = dict(payload)
    wrong_arguments["attempts"] = (
        receipt.attempts[0].model_copy(update={"arguments_sha256": "2" * 64}),
        receipt.attempts[1],
    )
    with pytest.raises(ValidationError, match="canonical arguments"):
        SideEffectIdempotencyReceipt.model_validate(wrong_arguments)

    wrong_key = dict(payload)
    wrong_key["attempts"] = (
        receipt.attempts[0].model_copy(update={"key_sha256": "3" * 64}),
        receipt.attempts[1],
    )
    with pytest.raises(ValidationError, match="logical-operation key"):
        SideEffectIdempotencyReceipt.model_validate(wrong_key)


def test_receipt_create_rejects_scenario_argument_or_key_mismatch() -> None:
    spec = _spec()
    stable = canonical_json_sha256([])

    with pytest.raises(SideEffectReceiptError, match="canonical arguments"):
        SideEffectIdempotencyReceipt.create(
            scenario_identity=_scenario().identity,
            contract=spec,
            attempts=(
                _attempt(1, "call-1", before=stable, after=stable, arguments_sha256="2" * 64),
                _attempt(2, "call-2", before=stable, after=stable, arguments_sha256="2" * 64),
            ),
        )

    with pytest.raises(SideEffectReceiptError, match="logical-operation key"):
        SideEffectIdempotencyReceipt.create(
            scenario_identity=_scenario().identity,
            contract=spec,
            attempts=(
                _attempt(1, "call-1", before=stable, after=stable, key_sha256="3" * 64),
                _attempt(2, "call-2", before=stable, after=stable, key_sha256="3" * 64),
            ),
        )


def test_verifier_rejects_observation_without_contract_and_missing_or_duplicate_receipts() -> None:
    scenario = _scenario().model_copy(update={"side_effect_idempotency": None})
    evidence = _evidence()
    with pytest.raises(SideEffectObservationError, match="no idempotency contract"):
        verify_side_effect_observation(scenario, evidence)

    configured = _scenario()
    without = _evidence().model_copy(update={"events": _evidence().events[:-1]})
    with pytest.raises(SideEffectObservationError, match="exactly one"):
        verify_side_effect_observation(configured, without)

    duplicate = _evidence()
    extra = duplicate.events[-1].model_copy(update={"sequence": 5})
    duplicate = duplicate.model_copy(update={"events": (*duplicate.events, extra)})
    with pytest.raises(SideEffectObservationError, match="exactly one"):
        verify_side_effect_observation(configured, duplicate)


def test_verifier_rejects_critical_unknown_source_and_malformed_receipt() -> None:
    with pytest.raises(SideEffectObservationError, match="non-critical"):
        verify_side_effect_observation(_scenario(), _evidence(observation_critical=True))

    with pytest.raises(SideEffectObservationError, match="source is not recognized"):
        verify_side_effect_observation(
            _scenario(),
            _evidence(observation_source="bridge:unknown"),
        )

    evidence = _evidence()
    events = list(evidence.events)
    events[-1] = events[-1].model_copy(update={"payload": {"schema_version": "bad"}})
    with pytest.raises(SideEffectObservationError, match="schema validation"):
        verify_side_effect_observation(
            _scenario(),
            evidence.model_copy(update={"events": tuple(events)}),
        )


def test_verifier_rejects_evidence_identity_and_receipt_binding_drift() -> None:
    scenario = _scenario()
    evidence = _evidence()
    with pytest.raises(SideEffectObservationError, match="evidence scenario identity"):
        verify_side_effect_observation(
            scenario,
            evidence.model_copy(update={"scenario_identity": "2" * 64}),
        )

    for field, message in (
        ("scenario_identity", "receipt scenario identity"),
        ("contract_identity", "contract identity"),
        ("tool", "tool identity"),
        ("logical_operation_identity", "logical-operation identity"),
    ):
        events = list(evidence.events)
        payload = dict(events[-1].payload)
        payload[field] = "different" if field == "tool" else "3" * 64
        events[-1] = events[-1].model_copy(update={"payload": payload})
        with pytest.raises(SideEffectObservationError, match=message):
            verify_side_effect_observation(
                scenario,
                evidence.model_copy(update={"events": tuple(events)}),
            )


def test_verifier_rejects_request_count_call_identity_argument_shape_and_result_count() -> None:
    scenario = _scenario()
    evidence = _evidence()

    without_second_request = evidence.model_copy(
        update={"events": tuple(event for event in evidence.events if event.sequence != 2)}
    )
    with pytest.raises(SideEffectObservationError, match="exactly two target tool requests"):
        verify_side_effect_observation(scenario, without_second_request)

    events = list(evidence.events)
    events[2] = events[2].model_copy(
        update={"payload": {**events[2].payload, "call_id": "wrong-call"}}
    )
    with pytest.raises(SideEffectObservationError, match="call identity"):
        verify_side_effect_observation(
            scenario,
            evidence.model_copy(update={"events": tuple(events)}),
        )

    events = list(evidence.events)
    events[2] = events[2].model_copy(
        update={"payload": {**events[2].payload, "arguments": {"operation_id": "op-7"}}}
    )
    with pytest.raises(SideEffectObservationError, match="must be JSON text"):
        verify_side_effect_observation(
            scenario,
            evidence.model_copy(update={"events": tuple(events)}),
        )

    events = list(evidence.events)
    events[2] = events[2].model_copy(
        update={
            "payload": {
                **events[2].payload,
                "arguments": '{"operation_id":"op-7","value":4}',
            }
        }
    )
    with pytest.raises(SideEffectObservationError, match="scenario-bound canonical operation"):
        verify_side_effect_observation(
            scenario,
            evidence.model_copy(update={"events": tuple(events)}),
        )

    without_second_result = evidence.model_copy(
        update={"events": tuple(event for event in evidence.events if event.sequence != 3)}
    )
    with pytest.raises(SideEffectObservationError, match="exactly one matching tool result"):
        verify_side_effect_observation(scenario, without_second_result)


def test_verifier_rejects_nonserialized_chronology() -> None:
    evidence = _evidence()
    events = list(evidence.events)
    events[1] = events[1].model_copy(update={"sequence": 3})
    events[3] = events[3].model_copy(update={"sequence": 1})
    tampered = evidence.model_copy(update={"events": tuple(events)})

    with pytest.raises(SideEffectObservationError, match="chronology must serialize"):
        verify_side_effect_observation(_scenario(), tampered)


def test_oracle_fallbacks_fail_closed_and_optional_first_mutation_can_pass() -> None:
    oracle = SideEffectIdempotencyOracle()
    no_contract = _scenario().model_copy(update={"side_effect_idempotency": None})
    assert oracle.grade(no_contract, _evidence()).verdict is TrialVerdict.PASS

    missing = _evidence().model_copy(update={"events": _evidence().events[:-1]})
    missing_result = oracle.grade(_scenario(), missing)
    assert missing_result.verdict is TrialVerdict.FAIL
    assert missing_result.critical is True
    assert missing_result.reasons == (
        "verified side-effect observation is unavailable during grading",
    )

    malformed = _evidence()
    events = list(malformed.events)
    events[-1] = events[-1].model_copy(update={"payload": {"schema_version": "bad"}})
    malformed_result = oracle.grade(
        _scenario(),
        malformed.model_copy(update={"events": tuple(events)}),
    )
    assert malformed_result.verdict is TrialVerdict.FAIL
    assert malformed_result.critical is True
    assert malformed_result.reasons == (
        "verified side-effect observation became malformed during grading",
    )

    optional_spec = _spec(require_first_mutation=False)
    stable = canonical_json_sha256([])
    receipt = SideEffectIdempotencyReceipt.create(
        scenario_identity=_scenario(spec=optional_spec).identity,
        contract=optional_spec,
        attempts=(
            SideEffectAttemptDigest(
                ordinal=1,
                call_id="call-1",
                arguments_sha256=optional_spec.expected_arguments_sha256,
                key_sha256=optional_spec.key_sha256,
                before_effect_sha256=stable,
                after_effect_sha256=stable,
                mutated=False,
            ),
            SideEffectAttemptDigest(
                ordinal=2,
                call_id="call-2",
                arguments_sha256=optional_spec.expected_arguments_sha256,
                key_sha256=optional_spec.key_sha256,
                before_effect_sha256=stable,
                after_effect_sha256=stable,
                mutated=False,
            ),
        ),
    )
    result = oracle.grade(_scenario(spec=optional_spec), _evidence(receipt))
    assert result.verdict is TrialVerdict.PASS
    assert result.critical is False
