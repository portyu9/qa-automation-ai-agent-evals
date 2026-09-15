from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel

import agent_evals.semantic.receipt as semantic_receipt
import agent_evals.semantic.verification as semantic_verification
import agent_evals.side_effect.receipt as side_effect_receipt
import agent_evals.side_effect.verification as side_effect_verification
from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.contracts.semantic import SemanticCriterionSpec, SemanticRubricSpec
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.semantic.calibration import (
    SemanticCalibrationCase,
    SemanticCalibrationObservation,
    SemanticCalibrationPolicy,
    SemanticCalibrationReceipt,
)
from agent_evals.semantic.models import (
    SemanticCriterionResult,
    SemanticDecision,
    SemanticJudgeInput,
    SemanticJudgeProfile,
    SemanticJudgeResponse,
)
from agent_evals.semantic.receipt import SemanticJudgmentReceipt
from agent_evals.side_effect.models import SideEffectIdempotencySpec, canonical_json_sha256
from agent_evals.side_effect.receipt import (
    SideEffectAttemptDigest,
    SideEffectIdempotencyReceipt,
    SideEffectReceiptError,
)

_SEMANTIC_SUBJECT = "2" * 64
_SIDE_EFFECT_SUBJECT = "3" * 64


def _semantic_rubric(*, revision: str = "1") -> SemanticRubricSpec:
    return SemanticRubricSpec(
        rubric_id="mutation-semantic",
        revision=revision,
        criteria=(
            SemanticCriterionSpec(
                criterion_id="grounded",
                description="The answer remains grounded.",
                minimum_score=3,
            ),
        ),
    )


def _semantic_scenario(
    *,
    rubric: SemanticRubricSpec | None = None,
    scenario_id: str = "mutation.semantic-receipt",
) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id=scenario_id,
        revision="1",
        kind=ScenarioKind.CAPABILITY,
        objective="Answer accurately.",
        semantic_rubric=rubric,
    )


def _semantic_response() -> SemanticJudgeResponse:
    return SemanticJudgeResponse(
        criteria=(
            SemanticCriterionResult(
                criterion_id="grounded",
                decision=SemanticDecision.PASS,
                score=4,
            ),
        ),
        overall=SemanticDecision.PASS,
    )


def _semantic_profile(*, model_revision: str = "1") -> SemanticJudgeProfile:
    return SemanticJudgeProfile.from_material(
        provider="test",
        model="mutation-judge",
        model_revision=model_revision,
        adapter="mutation-judge",
        adapter_version="1",
        prompt_template="grade only the evaluator-owned rubric",
        behavior_config={"temperature": 0},
    )


def _semantic_calibration(
    *,
    profile: SemanticJudgeProfile | None = None,
) -> SemanticCalibrationReceipt:
    judge_profile = profile or _semantic_profile()
    rubric = _semantic_rubric()
    cases = tuple(
        SemanticCalibrationCase(
            case_id=f"mutation.semantic.case-{index}",
            revision="1",
            objective="Answer accurately.",
            rubric=rubric,
            candidate_output=f"candidate-{index}",
            expected=expected,
            tags=(frozenset({"judge-prompt-injection"}) if index == 4 else frozenset()),
        )
        for index, expected in enumerate(
            (
                SemanticDecision.PASS,
                SemanticDecision.PASS,
                SemanticDecision.FAIL,
                SemanticDecision.FAIL,
            ),
            start=1,
        )
    )
    observations = tuple(
        SemanticCalibrationObservation.from_case_response(
            case,
            SemanticJudgeResponse(
                criteria=(
                    SemanticCriterionResult(
                        criterion_id="grounded",
                        decision=case.expected,
                        score=4 if case.expected is SemanticDecision.PASS else 1,
                    ),
                ),
                overall=case.expected,
            ),
        )
        for case in cases
    )
    return SemanticCalibrationReceipt.create(
        judge_profile=judge_profile,
        policy=SemanticCalibrationPolicy(),
        observations=observations,
    )


def _semantic_evidence(
    scenario: EvaluationScenario,
    *,
    output: str | None = "Grounded answer.",
    metrics: bool = False,
) -> TrialEvidence:
    events: tuple[EvidenceEvent, ...]
    if output is None:
        events = ()
    else:
        events = (
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.OUTPUT,
                source="adapter:scripted",
                payload={"text": output},
            ),
        )
    kwargs: dict[str, Any] = {}
    if metrics:
        kwargs.update(
            elapsed_ms=12.5,
            input_tokens=3,
            output_tokens=4,
            estimated_cost_usd=0.001,
        )
    return TrialEvidence(
        trial_id="mutation-semantic",
        subject_identity=_SEMANTIC_SUBJECT,
        scenario_identity=scenario.identity,
        events=events,
        final_output=output,
        **kwargs,
    )


def _semantic_receipt(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
    *,
    rubric: SemanticRubricSpec | None = None,
    candidate_output: str | None = None,
    subject_identity: str | None = None,
    scenario_identity: str | None = None,
) -> SemanticJudgmentReceipt:
    selected_rubric = rubric or scenario.semantic_rubric
    assert selected_rubric is not None
    return SemanticJudgmentReceipt.create(
        scenario_identity=scenario_identity or scenario.identity,
        subject_identity=subject_identity or evidence.subject_identity,
        subject_evidence_root=evidence.evidence_root,
        rubric=selected_rubric,
        judge_profile=_semantic_profile(),
        calibration_receipt=_semantic_calibration(),
        judge_input=SemanticJudgeInput(
            objective=scenario.objective,
            rubric=selected_rubric,
            candidate_output=(
                evidence.final_output if candidate_output is None else candidate_output
            )
            or "",
        ),
        response=_semantic_response(),
    )


def _semantic_event(
    receipt: SemanticJudgmentReceipt,
    *,
    sequence: int,
    source: str = semantic_verification.SEMANTIC_JUDGMENT_SOURCE,
    critical: bool = False,
) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.SEMANTIC_JUDGMENT,
        source=source,
        payload=receipt.model_dump(mode="json"),
        critical=critical,
    )


def _assert_semantic_error(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
    expected: str,
) -> None:
    with pytest.raises(semantic_verification.SemanticJudgmentError) as captured:
        semantic_verification.verify_semantic_judgment(scenario, evidence)
    assert str(captured.value) == expected


def test_semantic_evidence_frontier_diagnostics_are_exact() -> None:
    rubric = _semantic_rubric()
    scenario = _semantic_scenario(rubric=rubric)
    base = _semantic_evidence(scenario)
    receipt = _semantic_receipt(scenario, base)
    semantic = _semantic_event(receipt, sequence=1)

    duplicated = base.model_copy(
        update={
            "events": (
                base.events[0],
                semantic,
                semantic.model_copy(update={"sequence": 2}),
            )
        }
    )
    _assert_semantic_error(
        scenario,
        duplicated,
        "semantic evidence permits at most one recorded judgment",
    )

    reordered = base.model_copy(
        update={
            "events": (
                semantic.model_copy(update={"sequence": 0}),
                base.events[0].model_copy(update={"sequence": 1}),
            )
        }
    )
    _assert_semantic_error(
        scenario,
        reordered,
        "semantic judgment must be the terminal evaluator event",
    )

    unknown_source = base.model_copy(
        update={"events": (base.events[0], _semantic_event(receipt, sequence=1, source="unknown"))}
    )
    _assert_semantic_error(
        scenario,
        unknown_source,
        "semantic judgment source is not recognized",
    )

    critical = base.model_copy(
        update={"events": (base.events[0], _semantic_event(receipt, sequence=1, critical=True))}
    )
    _assert_semantic_error(
        scenario,
        critical,
        "semantic judgment evidence must not claim critical authority",
    )

    malformed_payload = dict(semantic.payload)
    malformed_payload["receipt_root"] = "0" * 64
    malformed = base.model_copy(
        update={
            "events": (
                base.events[0],
                semantic.model_copy(update={"payload": malformed_payload}),
            )
        }
    )
    _assert_semantic_error(
        scenario,
        malformed,
        "semantic judgment receipt is malformed",
    )

    foreign_subject = _semantic_receipt(
        scenario,
        base,
        subject_identity="4" * 64,
    )
    subject_mismatch = base.model_copy(
        update={"events": (base.events[0], _semantic_event(foreign_subject, sequence=1))}
    )
    _assert_semantic_error(
        scenario,
        subject_mismatch,
        "semantic judgment subject identity does not match evidence",
    )

    foreign_scenario = _semantic_receipt(
        scenario,
        base,
        scenario_identity="5" * 64,
    )
    scenario_mismatch = base.model_copy(
        update={"events": (base.events[0], _semantic_event(foreign_scenario, sequence=1))}
    )
    _assert_semantic_error(
        scenario,
        scenario_mismatch,
        "semantic judgment scenario identity does not match evidence",
    )

    other_base = _semantic_evidence(scenario, output="Different answer.")
    wrong_root = _semantic_receipt(scenario, other_base)
    root_mismatch = base.model_copy(
        update={"events": (base.events[0], _semantic_event(wrong_root, sequence=1))}
    )
    _assert_semantic_error(
        scenario,
        root_mismatch,
        "semantic judgment does not bind the exact pre-judgment subject evidence root",
    )


def test_semantic_scenario_binding_diagnostics_are_exact() -> None:
    rubric = _semantic_rubric()
    scenario = _semantic_scenario(rubric=rubric)
    base = _semantic_evidence(scenario)
    receipt = _semantic_receipt(scenario, base)
    recorded = semantic_verification.append_semantic_judgment(base, receipt)

    no_rubric = _semantic_scenario(rubric=None, scenario_id="mutation.semantic-no-rubric")
    rebound = recorded.model_copy(update={"scenario_identity": no_rubric.identity})
    _assert_semantic_error(
        no_rubric,
        rebound,
        "semantic judgment evidence exists for a scenario without a semantic rubric",
    )

    foreign = _semantic_scenario(rubric=rubric, scenario_id="mutation.semantic-foreign")
    foreign_base = _semantic_evidence(foreign)
    foreign_recorded = semantic_verification.append_semantic_judgment(
        foreign_base,
        _semantic_receipt(foreign, foreign_base),
    )
    _assert_semantic_error(
        scenario,
        foreign_recorded,
        "semantic judgment scenario identity does not match",
    )

    alternate_rubric = _semantic_rubric(revision="2")
    alternate_receipt = _semantic_receipt(
        scenario,
        base,
        rubric=alternate_rubric,
    )
    alternate_recorded = semantic_verification.append_semantic_judgment(
        base,
        alternate_receipt,
    )
    _assert_semantic_error(
        scenario,
        alternate_recorded,
        "semantic judgment rubric identity does not match scenario",
    )

    no_output = _semantic_evidence(scenario, output=None)
    no_output_receipt = _semantic_receipt(
        scenario,
        no_output,
        candidate_output="",
    )
    no_output_recorded = semantic_verification.append_semantic_judgment(
        no_output,
        no_output_receipt,
    )
    _assert_semantic_error(
        scenario,
        no_output_recorded,
        "recorded semantic judgment requires the exact candidate final output",
    )

    wrong_input = _semantic_receipt(
        scenario,
        base,
        candidate_output="Different candidate.",
    )
    wrong_input_recorded = semantic_verification.append_semantic_judgment(base, wrong_input)
    _assert_semantic_error(
        scenario,
        wrong_input_recorded,
        "semantic judgment input digest does not match the exact scenario objective, rubric, "
        "and candidate output",
    )


def test_semantic_prejudgment_reconstruction_and_append_preserve_metrics() -> None:
    scenario = _semantic_scenario(rubric=_semantic_rubric())
    base = _semantic_evidence(scenario, metrics=True)
    receipt = _semantic_receipt(scenario, base)
    recorded = semantic_verification.append_semantic_judgment(base, receipt)
    reconstructed = semantic_verification.evidence_before_semantic_judgment(recorded)

    assert reconstructed.elapsed_ms == 12.5
    assert reconstructed.input_tokens == 3
    assert reconstructed.output_tokens == 4
    assert reconstructed.estimated_cost_usd == 0.001
    assert recorded.elapsed_ms == 12.5
    assert recorded.input_tokens == 3
    assert recorded.output_tokens == 4
    assert recorded.estimated_cost_usd == 0.001

    empty = _semantic_evidence(scenario, output=None)
    with pytest.raises(semantic_verification.SemanticJudgmentError) as captured:
        semantic_verification.evidence_before_semantic_judgment(empty)
    assert str(captured.value) == "trial does not end with semantic judgment evidence"


def test_semantic_append_binding_diagnostics_are_exact() -> None:
    scenario = _semantic_scenario(rubric=_semantic_rubric())
    base = _semantic_evidence(scenario)
    receipt = _semantic_receipt(scenario, base)
    recorded = semantic_verification.append_semantic_judgment(base, receipt)

    with pytest.raises(semantic_verification.SemanticJudgmentError) as captured:
        semantic_verification.append_semantic_judgment(recorded, receipt)
    assert str(captured.value) == "trial already contains semantic judgment evidence"

    foreign_subject = _semantic_receipt(
        scenario,
        base,
        subject_identity="4" * 64,
    )
    with pytest.raises(semantic_verification.SemanticJudgmentError) as captured:
        semantic_verification.append_semantic_judgment(base, foreign_subject)
    assert str(captured.value) == "semantic judgment subject identity does not match"

    foreign_scenario = _semantic_receipt(
        scenario,
        base,
        scenario_identity="5" * 64,
    )
    with pytest.raises(semantic_verification.SemanticJudgmentError) as captured:
        semantic_verification.append_semantic_judgment(base, foreign_scenario)
    assert str(captured.value) == "semantic judgment scenario identity does not match"

    other_base = _semantic_evidence(scenario, output="Different answer.")
    wrong_root = _semantic_receipt(scenario, other_base)
    with pytest.raises(semantic_verification.SemanticJudgmentError) as captured:
        semantic_verification.append_semantic_judgment(base, wrong_root)
    assert str(captured.value) == (
        "semantic judgment does not bind the exact pre-judgment subject evidence root"
    )


def test_semantic_receipt_creation_and_calibration_diagnostics_are_exact() -> None:
    scenario = _semantic_scenario(rubric=_semantic_rubric())
    base = _semantic_evidence(scenario)
    assert scenario.semantic_rubric is not None
    alternate_rubric = _semantic_rubric(revision="2")

    with pytest.raises(ValueError) as captured:
        SemanticJudgmentReceipt.create(
            scenario_identity=scenario.identity,
            subject_identity=base.subject_identity,
            subject_evidence_root=base.evidence_root,
            rubric=scenario.semantic_rubric,
            judge_profile=_semantic_profile(),
            calibration_receipt=_semantic_calibration(),
            judge_input=SemanticJudgeInput(
                objective=scenario.objective,
                rubric=alternate_rubric,
                candidate_output=base.final_output or "",
            ),
            response=_semantic_response(),
        )
    assert str(captured.value) == (
        "semantic judge input rubric does not match the scenario rubric"
    )

    calibration = _semantic_calibration()
    assert (
        semantic_receipt._revalidate_calibration(
            calibration.model_dump(mode="json")  # type: ignore[arg-type]
        )
        == calibration
    )

    rejected = calibration.model_copy(update={"accepted": False})
    with pytest.raises(ValueError) as captured:
        semantic_receipt._require_accepted_matching_calibration(
            rejected,
            judge_profile=_semantic_profile(),
        )
    assert str(captured.value) == "semantic judgment requires an accepted calibration receipt"

    with pytest.raises(ValueError) as captured:
        semantic_receipt._require_accepted_matching_calibration(
            calibration,
            judge_profile=_semantic_profile(model_revision="2"),
        )
    assert str(captured.value) == (
        "semantic judgment judge profile does not match calibrated judge profile"
    )

    with pytest.raises(ValueError) as captured:
        semantic_receipt._receipt_root({"unsupported": object()})
    assert str(captured.value) == (
        "semantic judgment receipt material contains unsupported JSON value type object"
    )


def _side_effect_spec() -> SideEffectIdempotencySpec:
    return SideEffectIdempotencySpec(
        tool="apply_change",
        key_argument="operation_id",
        expected_arguments={"operation_id": "op-7", "value": 3},
    )


def _side_effect_scenario(*, with_spec: bool = True) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="mutation.side-effect-receipt",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Observe one duplicate logical operation.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"apply_change"})),
        side_effect_idempotency=_side_effect_spec() if with_spec else None,
    )


def _side_effect_attempts() -> tuple[SideEffectAttemptDigest, SideEffectAttemptDigest]:
    spec = _side_effect_spec()
    before = canonical_json_sha256({"effects": []})
    after = canonical_json_sha256({"effects": ["op-7"]})
    return (
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


def _side_effect_receipt(
    *,
    scenario_identity: str | None = None,
) -> SideEffectIdempotencyReceipt:
    scenario = _side_effect_scenario()
    return SideEffectIdempotencyReceipt.create(
        scenario_identity=scenario_identity or scenario.identity,
        contract=_side_effect_spec(),
        attempts=_side_effect_attempts(),
    )


def _side_effect_events(
    receipt: SideEffectIdempotencyReceipt,
) -> tuple[EvidenceEvent, ...]:
    arguments = json.dumps(_side_effect_spec().expected_arguments, separators=(",", ":"))
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


def _side_effect_evidence(
    events: tuple[EvidenceEvent, ...],
    *,
    scenario: EvaluationScenario,
) -> TrialEvidence:
    return TrialEvidence(
        trial_id="mutation-side-effect",
        subject_identity=_SIDE_EFFECT_SUBJECT,
        scenario_identity=scenario.identity,
        events=events,
    )


def _reroot_side_effect_receipt(
    receipt: SideEffectIdempotencyReceipt,
    **updates: object,
) -> SideEffectIdempotencyReceipt:
    unsigned = receipt.model_dump(mode="python", exclude={"receipt_root"})
    unsigned.update(updates)
    return SideEffectIdempotencyReceipt.model_validate(
        {**unsigned, "receipt_root": side_effect_receipt._receipt_root(unsigned)}
    )


def _assert_side_effect_error(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
    expected: str,
) -> None:
    with pytest.raises(side_effect_verification.SideEffectObservationError) as captured:
        side_effect_verification.verify_side_effect_observation(scenario, evidence)
    assert str(captured.value) == expected


def test_side_effect_frontier_and_receipt_binding_diagnostics_are_exact() -> None:
    scenario = _side_effect_scenario()
    receipt = _side_effect_receipt()
    events = _side_effect_events(receipt)
    evidence = _side_effect_evidence(events, scenario=scenario)

    unconfigured = _side_effect_scenario(with_spec=False)
    unconfigured_evidence = evidence.model_copy(update={"scenario_identity": unconfigured.identity})
    _assert_side_effect_error(
        unconfigured,
        unconfigured_evidence,
        "side-effect observation is invalid when the scenario has no idempotency contract",
    )

    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"events": events[:-1]}),
        "scenario idempotency contract requires exactly one side-effect observation receipt",
    )

    observation = events[-1]
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(
            update={
                "events": (
                    *events[:-1],
                    observation.model_copy(update={"critical": True}),
                )
            }
        ),
        "side-effect observation evidence must remain non-critical",
    )
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(
            update={
                "events": (
                    *events[:-1],
                    observation.model_copy(update={"source": "bridge:unknown"}),
                )
            }
        ),
        "side-effect observation evidence source is not recognized",
    )

    malformed = dict(observation.payload)
    malformed["receipt_root"] = "0" * 64
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(
            update={
                "events": (
                    *events[:-1],
                    observation.model_copy(update={"payload": malformed}),
                )
            }
        ),
        "side-effect observation receipt failed schema validation",
    )

    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"scenario_identity": "4" * 64}),
        "side-effect evidence scenario identity does not match scenario",
    )

    foreign_scenario = _side_effect_receipt(scenario_identity="4" * 64)
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(
            update={"events": (*events[:-1], foreign_scenario.to_event(sequence=4))}
        ),
        "side-effect receipt scenario identity does not match scenario",
    )

    foreign_contract = _reroot_side_effect_receipt(receipt, contract_identity="5" * 64)
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(
            update={"events": (*events[:-1], foreign_contract.to_event(sequence=4))}
        ),
        "side-effect receipt contract identity does not match scenario",
    )

    foreign_tool = _reroot_side_effect_receipt(receipt, tool="different_tool")
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"events": (*events[:-1], foreign_tool.to_event(sequence=4))}),
        "side-effect receipt tool identity does not match scenario",
    )

    foreign_operation = _reroot_side_effect_receipt(
        receipt,
        logical_operation_identity="6" * 64,
    )
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(
            update={"events": (*events[:-1], foreign_operation.to_event(sequence=4))}
        ),
        "side-effect receipt logical-operation identity does not match scenario",
    )


def test_side_effect_request_argument_and_chronology_diagnostics_are_exact() -> None:
    scenario = _side_effect_scenario()
    receipt = _side_effect_receipt()
    events = list(_side_effect_events(receipt))
    evidence = _side_effect_evidence(tuple(events), scenario=scenario)

    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"events": tuple(events[1:])}),
        "idempotency contract requires exactly two target tool requests",
    )

    wrong_call_payload = dict(events[0].payload)
    wrong_call_payload["call_id"] = "different-call"
    wrong_call = events[0].model_copy(update={"payload": wrong_call_payload})
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"events": (wrong_call, *events[1:])}),
        "side-effect request 1 call identity does not match receipt",
    )

    non_text_payload = dict(events[0].payload)
    non_text_payload["arguments"] = {"operation_id": "op-7", "value": 3}
    non_text = events[0].model_copy(update={"payload": non_text_payload})
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"events": (non_text, *events[1:])}),
        "side-effect tool arguments must be JSON text",
    )

    invalid_json_payload = dict(events[0].payload)
    invalid_json_payload["arguments"] = "{"
    invalid_json = events[0].model_copy(update={"payload": invalid_json_payload})
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"events": (invalid_json, *events[1:])}),
        "side-effect tool arguments are not strict JSON",
    )

    wrong_arguments_payload = dict(events[0].payload)
    wrong_arguments_payload["arguments"] = '{"operation_id":"op-7","value":4}'
    wrong_arguments = events[0].model_copy(update={"payload": wrong_arguments_payload})
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"events": (wrong_arguments, *events[1:])}),
        "duplicate side-effect attempts must equal the scenario-bound canonical operation",
    )

    with pytest.raises(ValueError) as captured:
        side_effect_verification._reject_duplicate_keys(
            [("operation_id", "op-7"), ("operation_id", "op-8")]
        )
    assert str(captured.value) == "duplicate JSON object member"

    reordered = (
        events[0].model_copy(update={"sequence": 0}),
        events[2].model_copy(update={"sequence": 1}),
        events[1].model_copy(update={"sequence": 2}),
        events[3].model_copy(update={"sequence": 3}),
        events[4].model_copy(update={"sequence": 4}),
    )
    _assert_side_effect_error(
        scenario,
        _side_effect_evidence(reordered, scenario=scenario),
        "side-effect chronology must serialize request/result pairs before observation",
    )


def test_side_effect_attempt_digest_binding_diagnostics_are_exact() -> None:
    scenario = _side_effect_scenario()
    receipt = _side_effect_receipt()
    events = _side_effect_events(receipt)
    evidence = _side_effect_evidence(events, scenario=scenario)

    wrong_argument_attempts = tuple(
        attempt.model_copy(update={"arguments_sha256": "7" * 64})
        for attempt in receipt.attempts
    )
    wrong_arguments = _reroot_side_effect_receipt(
        receipt,
        arguments_sha256="7" * 64,
        attempts=wrong_argument_attempts,
    )
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(
            update={"events": (*events[:-1], wrong_arguments.to_event(sequence=4))}
        ),
        "side-effect request 1 argument digest does not match receipt",
    )

    wrong_key_attempts = tuple(
        attempt.model_copy(update={"key_sha256": "8" * 64})
        for attempt in receipt.attempts
    )
    wrong_key = _reroot_side_effect_receipt(
        receipt,
        key_sha256="8" * 64,
        attempts=wrong_key_attempts,
    )
    _assert_side_effect_error(
        scenario,
        evidence.model_copy(update={"events": (*events[:-1], wrong_key.to_event(sequence=4))}),
        "side-effect request 1 logical-operation key does not match receipt",
    )


def test_side_effect_rederivation_failures_remain_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _side_effect_scenario()
    receipt = _side_effect_receipt()
    events = _side_effect_events(receipt)
    evidence = _side_effect_evidence(events, scenario=scenario)

    def fail_create(*args: object, **kwargs: object) -> SideEffectIdempotencyReceipt:
        del args, kwargs
        raise SideEffectReceiptError("synthetic rederivation failure")

    monkeypatch.setattr(
        side_effect_verification.SideEffectIdempotencyReceipt,
        "create",
        fail_create,
    )
    _assert_side_effect_error(
        scenario,
        evidence,
        "side-effect relation cannot be reconstructed from scenario",
    )


def test_side_effect_rederived_receipt_mismatch_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _side_effect_scenario()
    receipt = _side_effect_receipt()
    events = _side_effect_events(receipt)
    evidence = _side_effect_evidence(events, scenario=scenario)

    def return_different(*args: object, **kwargs: object) -> SideEffectIdempotencyReceipt:
        del args, kwargs
        return receipt.model_copy(update={"receipt_root": "9" * 64})

    monkeypatch.setattr(
        side_effect_verification.SideEffectIdempotencyReceipt,
        "create",
        return_different,
    )
    _assert_side_effect_error(
        scenario,
        evidence,
        "side-effect receipt does not match rederived scenario relation",
    )


def test_side_effect_receipt_creation_and_event_contracts_are_exact() -> None:
    spec = _side_effect_spec()
    attempts = _side_effect_attempts()

    bad_arguments = (
        attempts[0].model_copy(update={"arguments_sha256": "7" * 64}),
        attempts[1],
    )
    with pytest.raises(SideEffectReceiptError) as captured:
        SideEffectIdempotencyReceipt.create(
            scenario_identity=_side_effect_scenario().identity,
            contract=spec,
            attempts=bad_arguments,
        )
    assert str(captured.value) == (
        "observed side-effect attempts do not match scenario-bound canonical arguments"
    )

    bad_key = (
        attempts[0].model_copy(update={"key_sha256": "8" * 64}),
        attempts[1],
    )
    with pytest.raises(SideEffectReceiptError) as captured:
        SideEffectIdempotencyReceipt.create(
            scenario_identity=_side_effect_scenario().identity,
            contract=spec,
            attempts=bad_key,
        )
    assert str(captured.value) == (
        "observed side-effect attempts do not match scenario-bound logical-operation key"
    )

    receipt = _side_effect_receipt()
    event = receipt.to_event(sequence=4)
    assert event.payload == receipt.model_dump(mode="json")
    assert isinstance(event.payload["attempts"], list)

    with pytest.raises(ValueError) as captured:
        side_effect_receipt._receipt_root({"unsupported": object()})
    assert str(captured.value) == (
        "side-effect receipt material contains unsupported JSON value type object"
    )


class _ProbeEnum(StrEnum):
    VALUE = "value"


class _EnumProbe(BaseModel):
    state: _ProbeEnum


def test_side_effect_json_default_uses_json_mode_for_base_models() -> None:
    assert side_effect_receipt._json_default(_EnumProbe(state=_ProbeEnum.VALUE)) == {
        "state": "value"
    }
