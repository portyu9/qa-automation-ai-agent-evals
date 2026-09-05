from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.side_effect.models import SideEffectIdempotencySpec, canonical_json_sha256
from agent_evals.side_effect.oracle import SideEffectIdempotencyOracle
from agent_evals.side_effect.receipt import SideEffectAttemptDigest, SideEffectIdempotencyReceipt
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
        scenario_id="side-effect.idempotency",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Apply one logical change safely across a duplicate attempt.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"apply_change"})),
        side_effect_idempotency=spec or _spec(),
    )


def _attempt(
    ordinal: int,
    call_id: str,
    *,
    before: str,
    after: str,
) -> SideEffectAttemptDigest:
    spec = _spec()
    return SideEffectAttemptDigest(
        ordinal=ordinal,
        call_id=call_id,
        arguments_sha256=spec.expected_arguments_sha256,
        key_sha256=spec.key_sha256,
        before_effect_sha256=before,
        after_effect_sha256=after,
        mutated=before != after,
    )


def _receipt(*, second_mutates: bool = False) -> SideEffectIdempotencyReceipt:
    spec = _spec()
    empty = canonical_json_sha256({"effects": []})
    once = canonical_json_sha256({"effects": [{"operation_id": "op-7"}]})
    twice = canonical_json_sha256(
        {"effects": [{"operation_id": "op-7"}, {"operation_id": "op-7"}]}
    )
    return SideEffectIdempotencyReceipt.create(
        scenario_identity=_scenario().identity,
        contract=spec,
        attempts=(
            _attempt(1, "call-1", before=empty, after=once),
            _attempt(2, "call-2", before=once, after=twice if second_mutates else once),
        ),
    )


def _evidence(receipt: SideEffectIdempotencyReceipt) -> TrialEvidence:
    args = json.dumps(_spec().expected_arguments, separators=(",", ":"))
    events = (
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
        receipt.to_event(sequence=4),
    )
    scenario = _scenario()
    return TrialEvidence(
        trial_id="side-effect-trial",
        subject_identity="1" * 64,
        scenario_identity=scenario.identity,
        events=events,
    )


def test_contract_identity_is_canonical_and_operation_bound() -> None:
    left = _spec()
    right = SideEffectIdempotencySpec(
        tool="apply_change",
        key_argument="operation_id",
        expected_arguments={"value": 3, "operation_id": "op-7"},
    )
    changed = SideEffectIdempotencySpec(
        tool="apply_change",
        key_argument="operation_id",
        expected_arguments={"operation_id": "op-8", "value": 3},
    )

    assert left.identity == right.identity
    assert left.logical_operation_identity == right.logical_operation_identity
    assert left.identity != changed.identity
    assert left.logical_operation_identity != changed.logical_operation_identity


def test_contract_rejects_missing_or_ambiguous_operation_key_and_non_finite_json() -> None:
    with pytest.raises(ValidationError):
        SideEffectIdempotencySpec(
            tool="apply_change",
            key_argument="operation_id",
            expected_arguments={"value": 3},
        )
    with pytest.raises(ValidationError):
        SideEffectIdempotencySpec(
            tool="apply_change",
            key_argument="operation_id",
            expected_arguments={"operation_id": True},
        )
    with pytest.raises(ValidationError):
        SideEffectIdempotencySpec(
            tool="apply_change",
            key_argument="operation_id",
            expected_arguments={"operation_id": "op-7", "value": float("nan")},
        )


def test_effect_digest_is_mapping_order_independent() -> None:
    assert canonical_json_sha256({"b": 2, "a": [1, 2]}) == canonical_json_sha256(
        {"a": [1, 2], "b": 2}
    )


def test_receipt_preserves_bad_subject_behavior_as_valid_observation() -> None:
    receipt = _receipt(second_mutates=True)

    assert receipt.mutation_count == 2
    assert receipt.attempts[0].mutated is True
    assert receipt.attempts[1].mutated is True


def test_receipt_rejects_discontinuous_effect_chronology() -> None:
    spec = _spec()
    empty = canonical_json_sha256([])
    once = canonical_json_sha256([1])
    unrelated = canonical_json_sha256(["external-change"])

    with pytest.raises(ValidationError, match="chronology is discontinuous"):
        SideEffectIdempotencyReceipt.create(
            scenario_identity=_scenario().identity,
            contract=spec,
            attempts=(
                _attempt(1, "call-1", before=empty, after=once),
                _attempt(2, "call-2", before=unrelated, after=unrelated),
            ),
        )


def test_verifier_rederives_exact_request_result_and_receipt_relation() -> None:
    receipt = _receipt()
    evidence = _evidence(receipt)

    assert verify_side_effect_observation(_scenario(), evidence) == receipt


def test_verifier_rejects_duplicate_key_argument_json() -> None:
    receipt = _receipt()
    evidence = _evidence(receipt)
    events = list(evidence.events)
    request = events[2]
    events[2] = request.model_copy(
        update={
            "payload": {
                **request.payload,
                "arguments": '{"operation_id":"op-7","operation_id":"op-7","value":3}',
            }
        }
    )
    tampered = evidence.model_copy(update={"events": tuple(events)})

    with pytest.raises(SideEffectObservationError, match="strict JSON"):
        verify_side_effect_observation(_scenario(), tampered)


def test_verifier_rejects_receipt_after_changed_scenario_contract() -> None:
    evidence = _evidence(_receipt())
    changed = _scenario(
        spec=SideEffectIdempotencySpec(
            tool="apply_change",
            key_argument="operation_id",
            expected_arguments={"operation_id": "op-8", "value": 3},
        )
    )

    with pytest.raises(SideEffectObservationError, match="scenario identity"):
        verify_side_effect_observation(changed, evidence)


def test_oracle_passes_one_mutation_and_fails_duplicate_physical_mutation() -> None:
    oracle = SideEffectIdempotencyOracle()
    passing = oracle.grade(_scenario(), _evidence(_receipt()))
    failing = oracle.grade(_scenario(), _evidence(_receipt(second_mutates=True)))

    assert passing.verdict is TrialVerdict.PASS
    assert failing.verdict is TrialVerdict.FAIL
    assert failing.critical is True
    assert any("second observable physical effect" in reason for reason in failing.reasons)


def test_oracle_can_require_first_attempt_to_create_observable_effect() -> None:
    spec = _spec()
    stable = canonical_json_sha256({"effects": []})
    receipt = SideEffectIdempotencyReceipt.create(
        scenario_identity=_scenario().identity,
        contract=spec,
        attempts=(
            _attempt(1, "call-1", before=stable, after=stable),
            _attempt(2, "call-2", before=stable, after=stable),
        ),
    )
    result = SideEffectIdempotencyOracle().grade(_scenario(), _evidence(receipt))

    assert result.verdict is TrialVerdict.FAIL
    assert result.critical is True
    assert result.reasons == (
        "first logical-operation attempt produced no required observable effect",
    )
