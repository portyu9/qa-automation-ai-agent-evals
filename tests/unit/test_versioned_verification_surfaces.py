from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.contracts.outcome_selector import OutcomeSelectorV1
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.evidence.payloads import (
    EvaluationErrorEventV1,
    ReceiptEventV1,
    RuntimeErrorEventV1,
    ToolRequestEventV1,
    project_typed_event,
)
from agent_evals.oracles.deterministic import OracleResult, OutcomeOracle, PolicyOracle
from agent_evals.oracles.failures import OracleFailureCode, structured_oracle_failures
from agent_evals.receipts import ReceiptEnvelopeV1


def test_outcome_selector_v1_is_unambiguous_and_canonical() -> None:
    dotted_key = OutcomeSelectorV1.from_segments(("a.b",))
    nested = OutcomeSelectorV1.from_segments(("a", "b"))
    escaped = OutcomeSelectorV1.from_segments(("a/b", "~key"))

    assert dotted_key.pointer == "/a.b"
    assert nested.pointer == "/a/b"
    assert dotted_key.pointer != nested.pointer
    assert escaped.pointer == "/a~1b/~0key"

    state = {"a.b": "flat", "a": {"b": "nested"}, "a/b": {"~key": 7}}
    assert dotted_key.lookup(state) == (True, "flat")
    assert nested.lookup(state) == (True, "nested")
    assert escaped.lookup(state) == (True, 7)

    with pytest.raises(ValidationError, match=r"canonical|unsupported escape"):
        OutcomeSelectorV1(pointer="/a~2b")


def test_typed_event_projection_discriminates_core_payloads() -> None:
    evaluation_error = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.EVALUATION_ERROR,
        source="evaluator:test",
        payload={"code": "invalid_adapter_result", "reason": "bad result"},
        critical=True,
    )
    request = EvidenceEvent(
        sequence=1,
        kind=EvidenceKind.TOOL_REQUEST,
        source="adapter:test",
        payload={"tool": "lookup", "call_id": "call-1", "arguments": "{}"},
    )

    projected_error = project_typed_event(evaluation_error)
    projected_request = project_typed_event(request)

    assert type(projected_error) is EvaluationErrorEventV1
    assert projected_error.payload.code == "invalid_adapter_result"
    assert type(projected_request) is ToolRequestEventV1
    assert projected_request.payload.call_id == "call-1"


def test_typed_runtime_error_projection_rejects_shape_drift() -> None:
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.RUNTIME_ERROR,
        source="adapter:test",
        payload={"exception_type": "RuntimeError"},
        critical=True,
    )

    with pytest.raises(ValidationError):
        project_typed_event(event)

    valid = event.model_copy(
        update={"payload": {"exception_type": "RuntimeError", "detail_retained": False}}
    )
    projected = project_typed_event(valid)
    assert type(projected) is RuntimeErrorEventV1


def test_receipt_projection_and_common_envelope_do_not_upgrade_authority() -> None:
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.ATTACK_DELIVERY,
        source="injector:test",
        payload={
            "schema_version": "agent-evals/attack-delivery/v1",
            "receipt_root": "a" * 64,
            "scenario_identity": "b" * 64,
        },
    )

    projected = project_typed_event(event)
    envelope = ReceiptEnvelopeV1.from_event(event)

    assert type(projected) is ReceiptEventV1
    assert projected.payload.receipt_root == "a" * 64
    assert envelope.receipt_root == "a" * 64
    assert envelope.event_digest == event.digest

    tampered = json.loads(envelope.model_dump_json())
    tampered["payload_sha256"] = "c" * 64
    with pytest.raises(ValidationError, match="envelope root mismatch"):
        ReceiptEnvelopeV1.model_validate(tampered)

    ordinary = EvidenceEvent(
        sequence=1,
        kind=EvidenceKind.OUTPUT,
        source="adapter:test",
        payload={
            "schema_version": "agent-evals/fake-receipt/v1",
            "receipt_root": "d" * 64,
            "output": "not a receipt",
        },
    )
    with pytest.raises(ValueError, match="receipt-bearing"):
        ReceiptEnvelopeV1.from_event(ordinary)


def test_structured_oracle_failure_projection_preserves_original_reason() -> None:
    outcome = OracleResult(
        name="outcome",
        verdict=TrialVerdict.FAIL,
        reasons=("required outcome 'state.ok' is missing from terminal state",),
    )
    policy = OracleResult(
        name="policy",
        verdict=TrialVerdict.FAIL,
        reasons=("unauthorized resource requested by 'write': {}",),
        critical=True,
    )

    outcome_failure = structured_oracle_failures(outcome)
    policy_failure = structured_oracle_failures(policy)

    assert outcome_failure[0].code is OracleFailureCode.OUTCOME_REQUIRED_MISSING
    assert outcome_failure[0].reason == outcome.reasons[0]
    assert policy_failure[0].code is OracleFailureCode.POLICY_RESOURCE
    assert policy_failure[0].reason == policy.reasons[0]


def test_current_deterministic_oracles_emit_failure_codes_directly() -> None:
    scenario = EvaluationScenario(
        scenario_id="failure.codes",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Emit stable deterministic failure codes",
        required_outcomes={"state.ok": True},
    )
    outcome_evidence = TrialEvidence(
        trial_id="outcome-failure",
        subject_identity="1" * 64,
        scenario_identity=scenario.identity,
        final_state={},
    )
    outcome = OutcomeOracle().grade(scenario, outcome_evidence)

    assert outcome.failure_codes == (OracleFailureCode.OUTCOME_REQUIRED_MISSING,)
    assert structured_oracle_failures(outcome)[0].code is OracleFailureCode.OUTCOME_REQUIRED_MISSING

    policy_event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.POLICY_VIOLATION,
        source="adapter:test",
        payload={"reason": "explicit policy fact"},
        critical=True,
    )
    policy_evidence = TrialEvidence(
        trial_id="policy-failure",
        subject_identity="1" * 64,
        scenario_identity=scenario.identity,
        events=(policy_event,),
        final_state={"state": {"ok": True}},
    )
    policy = PolicyOracle().grade(scenario, policy_evidence)

    assert policy.failure_codes == (OracleFailureCode.POLICY_EXPLICIT,)
