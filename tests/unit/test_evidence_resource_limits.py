from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence import models as evidence_models
from agent_evals.evidence.limits import (
    EVENT_PAYLOAD_BUDGET,
    FINAL_STATE_BUDGET,
    MAX_FINAL_OUTPUT_UTF8_BYTES,
    MAX_TRIAL_EVENTS,
    RECEIPT_MATERIAL_BUDGET,
    JsonMaterialBudget,
    ResourceLimitError,
    validate_json_material,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner

_SUBJECT = "a" * 64
_SCENARIO = "b" * 64
_EVIDENCE_ROOT_DOMAIN = b"agent-evals/trial-evidence/v2\0"


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="resource-limit-test",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="resource-limit-test",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="evidence.resource-limits",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Reject evaluator inputs that exceed declared resource ceilings.",
    )


def _nested_list(depth: int) -> object:
    value: object = "leaf"
    for _ in range(depth):
        value = [value]
    return value


def _old_canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _old_v2_root(evidence: TrialEvidence) -> str:
    envelope_identity = _old_canonical_json_bytes(
        {
            "trial_id": evidence.trial_id,
            "subject_identity": evidence.subject_identity,
            "scenario_identity": evidence.scenario_identity,
        }
    )
    chain = hashlib.sha256(_EVIDENCE_ROOT_DOMAIN + envelope_identity).digest()
    for event in evidence.events:
        canonical = _old_canonical_json_bytes(event.model_dump(mode="json"))
        chain = hashlib.sha256(chain + hashlib.sha256(canonical).digest()).digest()
    terminal = _old_canonical_json_bytes(
        {
            "final_state": evidence.final_state,
            "final_output": evidence.final_output,
            "elapsed_ms": evidence.elapsed_ms,
            "input_tokens": evidence.input_tokens,
            "output_tokens": evidence.output_tokens,
            "estimated_cost_usd": evidence.estimated_cost_usd,
        }
    )
    return hashlib.sha256(_EVIDENCE_ROOT_DOMAIN + chain + terminal).hexdigest()


def test_iterative_budget_accepts_exact_depth_and_rejects_next_level() -> None:
    budget = JsonMaterialBudget(max_depth=32, max_nodes=128, max_utf8_bytes=1024)

    validate_json_material(_nested_list(32), budget=budget, label="fixture")

    with pytest.raises(ResourceLimitError, match="nesting depth"):
        validate_json_material(_nested_list(33), budget=budget, label="fixture")


def test_iterative_budget_rejects_cycle_without_recursive_descent() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)

    with pytest.raises(ResourceLimitError, match="reference cycle"):
        validate_json_material(cyclic, budget=EVENT_PAYLOAD_BUDGET, label="fixture")


def test_iterative_budget_rejects_wide_container_before_scheduling_children() -> None:
    value = [None] * (EVENT_PAYLOAD_BUDGET.max_nodes + 1)

    with pytest.raises(ResourceLimitError, match="node count"):
        validate_json_material(value, budget=EVENT_PAYLOAD_BUDGET, label="fixture")


def test_event_payload_accepts_exact_material_byte_ceiling() -> None:
    key = "x"
    payload = {key: "a" * (EVENT_PAYLOAD_BUDGET.max_utf8_bytes - len(key))}

    event = EvidenceEvent(sequence=0, kind=EvidenceKind.STATE, source="fixture", payload=payload)

    assert len(event.payload["x"]) == EVENT_PAYLOAD_BUDGET.max_utf8_bytes - 1


def test_event_payload_rejects_over_budget_before_canonicalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "x"
    payload = {key: "a" * EVENT_PAYLOAD_BUDGET.max_utf8_bytes}

    def should_not_run(_value: object) -> bytes:
        raise AssertionError("canonicalization must not run for over-budget payload")

    monkeypatch.setattr(evidence_models, "_canonical_json_bytes", should_not_run)

    with pytest.raises(ValidationError, match="resource limits"):
        EvidenceEvent(sequence=0, kind=EvidenceKind.STATE, source="fixture", payload=payload)


def test_final_state_rejects_excessive_nesting_before_canonicalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: object = {"leaf": True}
    for index in range(FINAL_STATE_BUDGET.max_depth + 1):
        state = {f"level-{index}": state}

    def should_not_run(_value: object) -> bytes:
        raise AssertionError("canonicalization must not run for over-depth final_state")

    monkeypatch.setattr(evidence_models, "_canonical_json_bytes", should_not_run)

    with pytest.raises(ValidationError, match="resource limits"):
        TrialEvidence(
            trial_id="over-depth-state",
            subject_identity=_SUBJECT,
            scenario_identity=_SCENARIO,
            final_state=state,  # type: ignore[arg-type]
        )


def test_final_output_accepts_exact_utf8_ceiling_and_rejects_next_byte() -> None:
    accepted = TrialEvidence(
        trial_id="output-at-limit",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        final_output="a" * MAX_FINAL_OUTPUT_UTF8_BYTES,
    )
    assert len(accepted.final_output or "") == MAX_FINAL_OUTPUT_UTF8_BYTES

    with pytest.raises(ValidationError, match="final_output exceeds"):
        TrialEvidence(
            trial_id="output-over-limit",
            subject_identity=_SUBJECT,
            scenario_identity=_SCENARIO,
            final_output="a" * (MAX_FINAL_OUTPUT_UTF8_BYTES + 1),
        )


def test_trial_event_count_rejects_before_nested_event_validation() -> None:
    # Deliberately malformed child entries demonstrate that the collection-size validator wins
    # before Pydantic spends work validating each individual event.
    events = [{}] * (MAX_TRIAL_EVENTS + 1)

    with pytest.raises(ValidationError, match="maximum event count"):
        TrialEvidence.model_validate(
            {
                "trial_id": "too-many-events",
                "subject_identity": _SUBJECT,
                "scenario_identity": _SCENARIO,
                "events": events,
            }
        )


def test_accepted_material_keeps_historical_v2_root_algorithm() -> None:
    evidence = TrialEvidence(
        trial_id="root-compatibility",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.STATE,
                source="fixture",
                payload={"nested": {"value": [1, 2, 3]}},
            ),
        ),
        final_state={"status": "ok"},
        final_output="done",
        elapsed_ms=12.5,
        input_tokens=7,
        output_tokens=3,
        estimated_cost_usd=0.125,
    )

    assert evidence.evidence_root == _old_v2_root(evidence)


@pytest.mark.asyncio
async def test_trial_runner_blocks_oversized_adapter_output_before_oracle_grading() -> None:
    adapter = ScriptedAdapter(
        lambda _subject, _scenario, _trial: AdapterResult(
            final_output="x" * (MAX_FINAL_OUTPUT_UTF8_BYTES + 1)
        ),
        name="oversized-output-fixture",
    )

    result = await TrialRunner().run(
        adapter,
        subject=_subject(),
        scenario=_scenario(),
        trial_id="oversized-adapter-output",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert result.evidence.events[0].payload == {
        "code": "invalid_adapter_result",
        "reason": "adapter result failed normalized evidence validation",
    }


def test_receipt_budget_is_larger_than_event_payload_budget_but_still_finite() -> None:
    assert RECEIPT_MATERIAL_BUDGET.max_utf8_bytes > EVENT_PAYLOAD_BUDGET.max_utf8_bytes
    assert RECEIPT_MATERIAL_BUDGET.max_nodes > EVENT_PAYLOAD_BUDGET.max_nodes
