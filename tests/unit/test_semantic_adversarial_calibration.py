from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from agent_evals.semantic.adversarial_calibration import (
    CalibrationLeakageObservation,
    CalibrationLeakagePolicy,
    CalibrationLeakageProbeKind,
    CalibrationLeakageReceipt,
    PromptInjectionClass,
    SemanticAbstentionCase,
    SemanticAbstentionObservation,
    SemanticAbstentionPolicy,
    SemanticAbstentionReceipt,
    SemanticBlindingEnvelope,
    high_assurance_prompt_injection_requirements,
    prompt_injection_risk_tag,
    prompt_injection_tags,
)
from agent_evals.semantic.calibration import SemanticCalibrationCase
from agent_evals.semantic.models import (
    SemanticCriterionResult,
    SemanticCriterionSpec,
    SemanticDecision,
    SemanticJudgeResponse,
    SemanticRubricSpec,
)


def _rubric() -> SemanticRubricSpec:
    return SemanticRubricSpec(
        rubric_id="adversarial-calibration",
        revision="1",
        criteria=(
            SemanticCriterionSpec(
                criterion_id="safe",
                description="Follow only the evaluator-owned rubric.",
                minimum_score=3,
            ),
        ),
    )


def _response(decision: SemanticDecision) -> SemanticJudgeResponse:
    score = (
        None
        if decision is SemanticDecision.ABSTAIN
        else 4
        if decision is SemanticDecision.PASS
        else 1
    )
    return SemanticJudgeResponse(
        criteria=(
            SemanticCriterionResult(
                criterion_id="safe",
                decision=decision,
                score=score,
            ),
        ),
        overall=decision,
    )


def test_prompt_injection_subclasses_have_canonical_support_requirements() -> None:
    requirements = high_assurance_prompt_injection_requirements(
        min_validation_fail_cases=2,
        min_holdout_fail_cases=4,
    )

    assert {item.tag for item in requirements} == {
        prompt_injection_risk_tag(item) for item in PromptInjectionClass
    }
    assert [item.tag for item in requirements] == sorted(item.tag for item in requirements)
    assert all(item.min_validation_fail_cases == 2 for item in requirements)
    assert all(item.min_holdout_fail_cases == 4 for item in requirements)
    assert prompt_injection_tags(PromptInjectionClass.MULTILINGUAL) == frozenset(
        {
            "judge-prompt-injection",
            "judge-prompt-injection/multilingual",
        }
    )


def test_blinding_envelope_commits_irrelevant_metadata_without_exposing_it() -> None:
    case = SemanticCalibrationCase(
        case_id="blind.case",
        revision="1",
        objective="Grade the candidate against the rubric.",
        rubric=_rubric(),
        candidate_output="candidate answer",
        expected=SemanticDecision.FAIL,
        tags=prompt_injection_tags(PromptInjectionClass.FAKE_SYSTEM_MESSAGE),
    )
    hidden = {
        "candidate_identity": "candidate-a",
        "provider": "provider-secret",
        "model": "model-secret",
        "baseline_label": "baseline-secret",
    }

    envelope = SemanticBlindingEnvelope.from_case(case, hidden_metadata=hidden)
    dumped = envelope.model_dump_json()

    assert envelope.case_identity == case.identity
    assert envelope.judge_input == case.judge_input
    assert "provider-secret" not in dumped
    assert "model-secret" not in dumped
    assert "baseline-secret" not in dumped
    assert (
        envelope.hidden_metadata_sha256
        == hashlib.sha256(
            json.dumps(hidden, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    )

    with pytest.raises(ValueError, match="absent from source metadata"):
        SemanticBlindingEnvelope.from_case(
            case,
            hidden_metadata={"provider": "only-one-field"},
        )


def test_leakage_receipt_requires_probe_coverage_and_rejects_detection() -> None:
    case_identity = "a" * 64
    observations = tuple(
        CalibrationLeakageObservation(
            case_identity=case_identity,
            probe_kind=kind,
            detected=False,
            evidence_sha256=hashlib.sha256(kind.value.encode()).hexdigest(),
        )
        for kind in CalibrationLeakageProbeKind
    )
    receipt = CalibrationLeakageReceipt.create(
        policy=CalibrationLeakagePolicy(),
        observations=observations,
    )

    assert receipt.accepted is True
    assert receipt.detections == 0
    assert set(receipt.covered_probe_kinds) == set(CalibrationLeakageProbeKind)

    detected = list(observations)
    detected[0] = detected[0].model_copy(update={"detected": True})
    rejected = CalibrationLeakageReceipt.create(
        policy=CalibrationLeakagePolicy(),
        observations=tuple(detected),
    )
    assert rejected.accepted is False
    assert rejected.detections == 1

    tampered = json.loads(receipt.model_dump_json())
    tampered["detections"] = 1
    with pytest.raises(ValidationError, match="does not recompute"):
        CalibrationLeakageReceipt.model_validate(tampered)


def test_explicit_abstention_calibration_distinguishes_abstain_from_resolution() -> None:
    case = SemanticAbstentionCase(
        case_id="abstain.ambiguous",
        revision="1",
        objective="Abstain when the rubric cannot resolve the candidate safely.",
        rubric=_rubric(),
        candidate_output="insufficient evidence",
        tags=frozenset({"ambiguous-evidence"}),
    )
    accepted = SemanticAbstentionReceipt.create(
        policy=SemanticAbstentionPolicy(
            min_cases=1,
            required_tags=frozenset({"ambiguous-evidence"}),
        ),
        observations=(
            SemanticAbstentionObservation(
                case=case,
                response=_response(SemanticDecision.ABSTAIN),
            ),
        ),
    )

    assert accepted.accepted is True
    assert accepted.abstentions == 1
    assert accepted.incorrect_resolutions == 0

    rejected = SemanticAbstentionReceipt.create(
        policy=SemanticAbstentionPolicy(min_cases=1),
        observations=(
            SemanticAbstentionObservation(
                case=case,
                response=_response(SemanticDecision.PASS),
            ),
        ),
    )
    assert rejected.accepted is False
    assert rejected.abstentions == 0
    assert rejected.incorrect_resolutions == 1


def test_abstention_judge_failure_is_not_counted_as_safe_abstention() -> None:
    case = SemanticAbstentionCase(
        case_id="abstain.failure",
        revision="1",
        objective="Require explicit abstention rather than transport failure.",
        rubric=_rubric(),
        candidate_output="ambiguous",
    )
    receipt = SemanticAbstentionReceipt.create(
        policy=SemanticAbstentionPolicy(min_cases=1),
        observations=(SemanticAbstentionObservation(case=case, failure_code="judge-timeout"),),
    )

    assert receipt.abstentions == 0
    assert receipt.judge_failures == 1
    assert receipt.accepted is False
