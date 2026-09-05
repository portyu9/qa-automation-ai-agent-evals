from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.semantic.calibration import (
    SemanticCalibrationCase,
    SemanticCalibrationObservation,
    SemanticCalibrationPolicy,
    SemanticCalibrationReceipt,
)
from agent_evals.semantic.models import (
    SemanticCriterionResult,
    SemanticCriterionSpec,
    SemanticDecision,
    SemanticJudgeInput,
    SemanticJudgeProfile,
    SemanticJudgeResponse,
    SemanticRubricSpec,
)
from agent_evals.semantic.receipt import SemanticJudgmentReceipt

_SCENARIO_IDENTITY = "1" * 64
_SUBJECT_IDENTITY = "2" * 64
_SUBJECT_EVIDENCE_ROOT = "3" * 64


def _rubric(*, threshold: int = 3) -> SemanticRubricSpec:
    return SemanticRubricSpec(
        rubric_id="answer-quality",
        revision="1",
        criteria=(
            SemanticCriterionSpec(
                criterion_id="grounded",
                description="The answer stays within the supplied task facts.",
                minimum_score=threshold,
            ),
            SemanticCriterionSpec(
                criterion_id="complete",
                description="The answer addresses every requested semantic requirement.",
                minimum_score=threshold,
            ),
        ),
    )


def _response(
    *,
    grounded: SemanticDecision = SemanticDecision.PASS,
    grounded_score: int | None = 4,
    complete: SemanticDecision = SemanticDecision.PASS,
    complete_score: int | None = 4,
    overall: SemanticDecision = SemanticDecision.PASS,
) -> SemanticJudgeResponse:
    return SemanticJudgeResponse(
        criteria=(
            SemanticCriterionResult(
                criterion_id="grounded",
                decision=grounded,
                score=grounded_score,
            ),
            SemanticCriterionResult(
                criterion_id="complete",
                decision=complete,
                score=complete_score,
            ),
        ),
        overall=overall,
    )


def _profile(*, prompt: str = "grade only the evaluator-owned rubric") -> SemanticJudgeProfile:
    return SemanticJudgeProfile.from_material(
        provider="openai",
        model="scripted-judge",
        model_revision="0.22.0",
        adapter="openai-semantic-judge",
        adapter_version="1",
        prompt_template=prompt,
        behavior_config={"temperature": 0, "seed": 7},
    )


def _calibration_case(
    case_id: str,
    expected: SemanticDecision,
    *,
    tags: frozenset[str] = frozenset(),
) -> SemanticCalibrationCase:
    return SemanticCalibrationCase(
        case_id=case_id,
        revision="1",
        objective="Answer the supplied customer question safely and completely.",
        rubric=_rubric(),
        candidate_output=f"candidate:{case_id}",
        expected=expected,
        tags=tags,
    )


def _accepted_calibration() -> SemanticCalibrationReceipt:
    cases = (
        _calibration_case("semantic.good-1", SemanticDecision.PASS),
        _calibration_case("semantic.good-2", SemanticDecision.PASS),
        _calibration_case("semantic.bad-1", SemanticDecision.FAIL),
        _calibration_case(
            "semantic.bad-2",
            SemanticDecision.FAIL,
            tags=frozenset({"judge-prompt-injection"}),
        ),
    )
    fail_response = _response(
        grounded=SemanticDecision.FAIL,
        grounded_score=1,
        overall=SemanticDecision.FAIL,
    )
    observations = (
        SemanticCalibrationObservation.from_case_response(cases[0], _response()),
        SemanticCalibrationObservation.from_case_response(cases[1], _response()),
        SemanticCalibrationObservation.from_case_response(cases[2], fail_response),
        SemanticCalibrationObservation.from_case_response(cases[3], fail_response),
    )
    return SemanticCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=SemanticCalibrationPolicy(),
        observations=observations,
    )


def _receipt(*, candidate: str = "Grounded and complete.") -> SemanticJudgmentReceipt:
    rubric = _rubric()
    return SemanticJudgmentReceipt.create(
        scenario_identity=_SCENARIO_IDENTITY,
        subject_identity=_SUBJECT_IDENTITY,
        subject_evidence_root=_SUBJECT_EVIDENCE_ROOT,
        rubric=rubric,
        judge_profile=_profile(),
        calibration_receipt=_accepted_calibration(),
        judge_input=SemanticJudgeInput(
            objective="Answer the customer question safely and completely.",
            rubric=rubric,
            candidate_output=candidate,
        ),
        response=_response(),
    )


def test_semantic_judgment_receipt_binds_pre_semantic_trial_and_excludes_raw_candidate() -> None:
    marker = "RAW-SUBJECT-OUTPUT-MUST-NOT-BE-DUPLICATED-IN-RECEIPT"
    receipt = _receipt(candidate=marker)

    assert receipt.scenario_identity == _SCENARIO_IDENTITY
    assert receipt.subject_identity == _SUBJECT_IDENTITY
    assert receipt.subject_evidence_root == _SUBJECT_EVIDENCE_ROOT
    assert receipt.rubric_identity == receipt.rubric.identity
    assert receipt.decision is SemanticDecision.PASS
    assert marker not in json.dumps(receipt.model_dump(mode="json"), sort_keys=True)


def test_semantic_judgment_requires_accepted_exact_profile_calibration() -> None:
    calibration = _accepted_calibration()
    rejected = SemanticCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=SemanticCalibrationPolicy(min_cases=5),
        observations=calibration.observations,
    )
    rubric = _rubric()
    judge_input = SemanticJudgeInput(
        objective="Answer safely.",
        rubric=rubric,
        candidate_output="Candidate.",
    )

    with pytest.raises(ValueError, match="accepted calibration"):
        SemanticJudgmentReceipt.create(
            scenario_identity=_SCENARIO_IDENTITY,
            subject_identity=_SUBJECT_IDENTITY,
            subject_evidence_root=_SUBJECT_EVIDENCE_ROOT,
            rubric=rubric,
            judge_profile=_profile(),
            calibration_receipt=rejected,
            judge_input=judge_input,
            response=_response(),
        )

    with pytest.raises(ValueError, match="does not match calibrated judge profile"):
        SemanticJudgmentReceipt.create(
            scenario_identity=_SCENARIO_IDENTITY,
            subject_identity=_SUBJECT_IDENTITY,
            subject_evidence_root=_SUBJECT_EVIDENCE_ROOT,
            rubric=rubric,
            judge_profile=_profile(prompt="drifted prompt"),
            calibration_receipt=calibration,
            judge_input=judge_input,
            response=_response(),
        )


def test_semantic_judgment_rejects_input_rubric_drift() -> None:
    rubric = _rubric()
    with pytest.raises(ValueError, match="input rubric does not match"):
        SemanticJudgmentReceipt.create(
            scenario_identity=_SCENARIO_IDENTITY,
            subject_identity=_SUBJECT_IDENTITY,
            subject_evidence_root=_SUBJECT_EVIDENCE_ROOT,
            rubric=rubric,
            judge_profile=_profile(),
            calibration_receipt=_accepted_calibration(),
            judge_input=SemanticJudgeInput(
                objective="Answer safely.",
                rubric=_rubric(threshold=4),
                candidate_output="Candidate.",
            ),
            response=_response(),
        )


def test_semantic_judgment_revalidates_embedded_rubric_identity_before_outer_root() -> None:
    payload = _receipt().model_dump(mode="json")
    payload["rubric"]["criteria"][0]["minimum_score"] = 4

    with pytest.raises(ValidationError, match="rubric identity does not match embedded rubric"):
        SemanticJudgmentReceipt.model_validate(payload)


def test_semantic_judgment_rederives_criterion_semantics_before_outer_root() -> None:
    payload = _receipt().model_dump(mode="json")
    payload["criteria"][0]["score"] = 1

    with pytest.raises(ValidationError, match="contradicts its score"):
        SemanticJudgmentReceipt.model_validate(payload)


def test_semantic_judgment_revalidates_response_digest_before_outer_root() -> None:
    payload = _receipt().model_dump(mode="json")
    payload["judge_response_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="response digest"):
        SemanticJudgmentReceipt.model_validate(payload)


def test_semantic_judgment_rejects_outer_root_tampering() -> None:
    payload = _receipt().model_dump(mode="json")
    payload["receipt_root"] = "0" * 64

    with pytest.raises(ValidationError, match="receipt root"):
        SemanticJudgmentReceipt.model_validate(payload)


def test_semantic_judgment_binds_subject_evidence_root() -> None:
    first = _receipt()
    second = SemanticJudgmentReceipt.create(
        scenario_identity=_SCENARIO_IDENTITY,
        subject_identity=_SUBJECT_IDENTITY,
        subject_evidence_root="4" * 64,
        rubric=_rubric(),
        judge_profile=_profile(),
        calibration_receipt=_accepted_calibration(),
        judge_input=SemanticJudgeInput(
            objective="Answer the customer question safely and completely.",
            rubric=_rubric(),
            candidate_output="Grounded and complete.",
        ),
        response=_response(),
    )

    assert first.subject_evidence_root != second.subject_evidence_root
    assert first.receipt_root != second.receipt_root
