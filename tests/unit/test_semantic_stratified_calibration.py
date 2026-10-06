from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.semantic.calibration import (
    SemanticCalibrationCase,
    SemanticCalibrationObservation,
    SemanticCalibrationPolicy,
)
from agent_evals.semantic.models import (
    SemanticCriterionResult,
    SemanticCriterionSpec,
    SemanticDecision,
    SemanticJudgeProfile,
    SemanticJudgeResponse,
    SemanticRubricSpec,
)
from agent_evals.semantic.stratified_calibration import (
    CalibrationRiskTagRequirement,
    CalibrationSplit,
    StratifiedCalibrationObservation,
    StratifiedCalibrationPolicy,
    StratifiedCalibrationReceipt,
)


def _rubric() -> SemanticRubricSpec:
    return SemanticRubricSpec(
        rubric_id="stratified-calibration",
        revision="1",
        criteria=(
            SemanticCriterionSpec(
                criterion_id="safe",
                description="The candidate satisfies the evaluator-owned rubric.",
                minimum_score=3,
            ),
        ),
    )


def _profile() -> SemanticJudgeProfile:
    return SemanticJudgeProfile.from_material(
        provider="fixture",
        model="deterministic-judge",
        model_revision="1",
        adapter="fixture-semantic-judge",
        adapter_version="1",
        prompt_template="grade only the evaluator-owned rubric",
        behavior_config={"temperature": 0},
    )


def _case(
    case_id: str,
    *,
    expected: SemanticDecision,
    tagged: bool = False,
) -> SemanticCalibrationCase:
    return SemanticCalibrationCase(
        case_id=case_id,
        revision="1",
        objective="Judge the candidate against the fixed rubric.",
        rubric=_rubric(),
        candidate_output=f"candidate:{case_id}",
        expected=expected,
        tags=frozenset({"judge-prompt-injection"}) if tagged else frozenset(),
    )


def _response(decision: SemanticDecision) -> SemanticJudgeResponse:
    score = 4 if decision is SemanticDecision.PASS else 1
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


def _observation(
    case_id: str,
    *,
    expected: SemanticDecision,
    observed: SemanticDecision | None = None,
    tagged: bool = False,
) -> SemanticCalibrationObservation:
    case = _case(case_id, expected=expected, tagged=tagged)
    if observed is None:
        return SemanticCalibrationObservation.from_case_failure(
            case,
            failure_code="judge-failure",
        )
    return SemanticCalibrationObservation.from_case_response(case, _response(observed))


def _split(
    split: CalibrationSplit,
    observation: SemanticCalibrationObservation,
) -> StratifiedCalibrationObservation:
    return StratifiedCalibrationObservation(split=split, observation=observation)


def _base_policy(*, require_tag: bool = False, allow_false_pass: bool = False) -> SemanticCalibrationPolicy:
    return SemanticCalibrationPolicy(
        min_cases=2,
        min_pass_cases=1,
        min_fail_cases=1,
        min_accuracy=0.5 if allow_false_pass else 1.0,
        max_false_passes=1 if allow_false_pass else 0,
        max_false_pass_rate=1.0 if allow_false_pass else 0.0,
        required_tags=frozenset({"judge-prompt-injection"}) if require_tag else frozenset(),
    )


def _stratified_policy(
    *,
    validation_policy: SemanticCalibrationPolicy | None = None,
    holdout_policy: SemanticCalibrationPolicy | None = None,
    risk_requirements: tuple[CalibrationRiskTagRequirement, ...] | None = None,
    max_bound: float = 0.5,
) -> StratifiedCalibrationPolicy:
    kwargs: dict[str, object] = {
        "validation_policy": validation_policy or _base_policy(),
        "holdout_policy": holdout_policy or _base_policy(),
        "min_development_cases": 1,
        "confidence_z": 1.0,
        "max_validation_false_pass_upper_bound": max_bound,
        "max_holdout_false_pass_upper_bound": max_bound,
    }
    kwargs["risk_requirements"] = risk_requirements or (
        CalibrationRiskTagRequirement(
            tag="judge-prompt-injection",
            min_validation_fail_cases=1,
            min_holdout_fail_cases=1,
        ),
    )
    return StratifiedCalibrationPolicy.model_validate(kwargs)


def _passing_partition(
    *,
    development: SemanticCalibrationObservation | None = None,
    validation_fail_tagged: bool = True,
    holdout_fail_tagged: bool = True,
) -> tuple[StratifiedCalibrationObservation, ...]:
    return (
        _split(
            CalibrationSplit.DEVELOPMENT,
            development
            or _observation(
                "strata.dev-pass",
                expected=SemanticDecision.PASS,
                observed=SemanticDecision.PASS,
            ),
        ),
        _split(
            CalibrationSplit.VALIDATION,
            _observation(
                "strata.validation-pass",
                expected=SemanticDecision.PASS,
                observed=SemanticDecision.PASS,
            ),
        ),
        _split(
            CalibrationSplit.VALIDATION,
            _observation(
                "strata.validation-risk",
                expected=SemanticDecision.FAIL,
                observed=SemanticDecision.FAIL,
                tagged=validation_fail_tagged,
            ),
        ),
        _split(
            CalibrationSplit.HOLDOUT,
            _observation(
                "strata.holdout-pass",
                expected=SemanticDecision.PASS,
                observed=SemanticDecision.PASS,
            ),
        ),
        _split(
            CalibrationSplit.HOLDOUT,
            _observation(
                "strata.holdout-risk",
                expected=SemanticDecision.FAIL,
                observed=SemanticDecision.FAIL,
                tagged=holdout_fail_tagged,
            ),
        ),
    )


def test_stratified_calibration_accepts_isolated_validation_and_holdout() -> None:
    receipt = StratifiedCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=_stratified_policy(),
        observations=_passing_partition(),
    )

    assert receipt.accepted is True
    assert receipt.validation_receipt.accepted is True
    assert receipt.holdout_receipt.accepted is True
    assert receipt.validation_false_pass_upper_bound == pytest.approx(0.5)
    assert receipt.holdout_false_pass_upper_bound == pytest.approx(0.5)
    assert receipt.validation_risk_support[0].fail_cases == 1
    assert receipt.holdout_risk_support[0].fail_cases == 1
    assert receipt.require_accepted_holdout() == receipt.holdout_receipt

    development_identity = receipt.observations[0].case_identity
    validation_identities = {
        observation.case_identity for observation in receipt.validation_receipt.observations
    }
    holdout_identities = {
        observation.case_identity for observation in receipt.holdout_receipt.observations
    }
    assert development_identity not in validation_identities | holdout_identities


def test_development_errors_do_not_contribute_to_acceptance_metrics() -> None:
    bad_development = _observation(
        "strata.dev-false-pass",
        expected=SemanticDecision.FAIL,
        observed=SemanticDecision.PASS,
        tagged=True,
    )
    receipt = StratifiedCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=_stratified_policy(),
        observations=_passing_partition(development=bad_development),
    )

    assert receipt.accepted is True
    assert receipt.validation_receipt.false_passes == 0
    assert receipt.holdout_receipt.false_passes == 0


def test_same_case_identity_cannot_cross_split_boundary() -> None:
    duplicate = _observation(
        "strata.duplicate",
        expected=SemanticDecision.FAIL,
        observed=SemanticDecision.FAIL,
        tagged=True,
    )
    observations = (
        _split(CalibrationSplit.DEVELOPMENT, duplicate),
        _split(
            CalibrationSplit.VALIDATION,
            _observation(
                "strata.validation-pass-duplicate-test",
                expected=SemanticDecision.PASS,
                observed=SemanticDecision.PASS,
            ),
        ),
        _split(CalibrationSplit.VALIDATION, duplicate),
        _split(
            CalibrationSplit.HOLDOUT,
            _observation(
                "strata.holdout-pass-duplicate-test",
                expected=SemanticDecision.PASS,
                observed=SemanticDecision.PASS,
            ),
        ),
        _split(
            CalibrationSplit.HOLDOUT,
            _observation(
                "strata.holdout-fail-duplicate-test",
                expected=SemanticDecision.FAIL,
                observed=SemanticDecision.FAIL,
                tagged=True,
            ),
        ),
    )

    with pytest.raises(ValueError, match="cannot appear in multiple"):
        StratifiedCalibrationReceipt.create(
            judge_profile=_profile(),
            policy=_stratified_policy(),
            observations=observations,
        )


def test_risk_support_is_required_independently_in_holdout() -> None:
    policy = _stratified_policy(
        validation_policy=_base_policy(),
        holdout_policy=_base_policy(),
        risk_requirements=(
            CalibrationRiskTagRequirement(
                tag="judge-prompt-injection",
                min_validation_fail_cases=1,
                min_holdout_fail_cases=1,
            ),
        ),
    )
    receipt = StratifiedCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=policy,
        observations=_passing_partition(holdout_fail_tagged=False),
    )

    assert receipt.validation_receipt.accepted is True
    assert receipt.holdout_receipt.accepted is True
    assert receipt.validation_risk_support[0].fail_cases == 1
    assert receipt.holdout_risk_support[0].fail_cases == 0
    assert receipt.accepted is False
    with pytest.raises(ValueError, match="not accepted"):
        receipt.require_accepted_holdout()


def test_false_pass_confidence_bound_can_reject_zero_observed_false_passes() -> None:
    receipt = StratifiedCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=_stratified_policy(max_bound=0.49),
        observations=_passing_partition(),
    )

    assert receipt.validation_receipt.false_passes == 0
    assert receipt.holdout_receipt.false_passes == 0
    assert receipt.validation_false_pass_upper_bound == pytest.approx(0.5)
    assert receipt.holdout_false_pass_upper_bound == pytest.approx(0.5)
    assert receipt.accepted is False


def test_observed_false_pass_is_not_hidden_by_permissive_v2_policy() -> None:
    policy = _stratified_policy(
        validation_policy=_base_policy(allow_false_pass=True),
        holdout_policy=_base_policy(),
        max_bound=0.5,
    )
    observations = list(_passing_partition())
    observations[2] = _split(
        CalibrationSplit.VALIDATION,
        _observation(
            "strata.validation-false-pass",
            expected=SemanticDecision.FAIL,
            observed=SemanticDecision.PASS,
            tagged=True,
        ),
    )
    receipt = StratifiedCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=policy,
        observations=tuple(observations),
    )

    assert receipt.validation_receipt.accepted is True
    assert receipt.validation_receipt.false_passes == 1
    assert receipt.validation_false_pass_upper_bound == 1.0
    assert receipt.accepted is False


def test_stratified_receipt_rejects_tampering_and_legacy_schema_label() -> None:
    receipt = StratifiedCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=_stratified_policy(),
        observations=_passing_partition(),
    )
    payload = json.loads(receipt.model_dump_json())
    payload["validation_false_pass_upper_bound"] = 0.25

    with pytest.raises(ValidationError, match="does not recompute"):
        StratifiedCalibrationReceipt.model_validate(payload)

    legacy = json.loads(receipt.model_dump_json())
    legacy["schema_version"] = "agent-evals/semantic-stratified-calibration-receipt/v0"
    with pytest.raises(ValidationError, match="schema_version"):
        StratifiedCalibrationReceipt.model_validate(legacy)


def test_risk_requirements_must_be_unique_and_canonical() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _stratified_policy(
            risk_requirements=(
                CalibrationRiskTagRequirement(tag="risk-a"),
                CalibrationRiskTagRequirement(tag="risk-a"),
            )
        )

    with pytest.raises(ValidationError, match="sorted"):
        _stratified_policy(
            risk_requirements=(
                CalibrationRiskTagRequirement(tag="risk-b"),
                CalibrationRiskTagRequirement(tag="risk-a"),
            )
        )
