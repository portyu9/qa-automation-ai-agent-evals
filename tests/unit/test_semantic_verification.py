from __future__ import annotations

import pytest

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
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
from agent_evals.semantic.verification import (
    SEMANTIC_JUDGMENT_SOURCE,
    SemanticJudgmentError,
    append_semantic_judgment,
    evidence_before_semantic_judgment,
    verify_semantic_judgment,
)

_SUBJECT_IDENTITY = "2" * 64


def _rubric() -> SemanticRubricSpec:
    return SemanticRubricSpec(
        rubric_id="answer-quality",
        revision="1",
        criteria=(
            SemanticCriterionSpec(
                criterion_id="grounded",
                description="The answer stays grounded in the supplied facts.",
                minimum_score=3,
            ),
        ),
    )


def _scenario(*, rubric: SemanticRubricSpec | None = None) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="semantic.verification",
        revision="1",
        kind=ScenarioKind.CAPABILITY,
        objective="Answer accurately.",
        semantic_rubric=rubric,
    )


def _response(decision: SemanticDecision = SemanticDecision.PASS) -> SemanticJudgeResponse:
    score = 4 if decision is SemanticDecision.PASS else 1
    return SemanticJudgeResponse(
        criteria=(
            SemanticCriterionResult(
                criterion_id="grounded",
                decision=decision,
                score=score,
            ),
        ),
        overall=decision,
    )


def _profile() -> SemanticJudgeProfile:
    return SemanticJudgeProfile.from_material(
        provider="openai",
        model="scripted-judge",
        model_revision="0.22.0",
        adapter="openai-semantic-judge",
        adapter_version="1",
        prompt_template="grade only the evaluator-owned rubric",
        behavior_config={"temperature": 0},
    )


def _calibration() -> SemanticCalibrationReceipt:
    cases = tuple(
        SemanticCalibrationCase(
            case_id=f"semantic.case-{index}",
            revision="1",
            objective="Answer accurately.",
            rubric=_rubric(),
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
            _response(case.expected),
        )
        for case in cases
    )
    return SemanticCalibrationReceipt.create(
        judge_profile=_profile(),
        policy=SemanticCalibrationPolicy(),
        observations=observations,
    )


def _subject_evidence(
    scenario: EvaluationScenario, *, output: str = "Grounded answer."
) -> TrialEvidence:
    return TrialEvidence(
        trial_id="semantic-trial",
        subject_identity=_SUBJECT_IDENTITY,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.OUTPUT,
                source="adapter:scripted",
                payload={"text": output},
            ),
        ),
        final_output=output,
    )


def _receipt(scenario: EvaluationScenario, evidence: TrialEvidence) -> SemanticJudgmentReceipt:
    assert scenario.semantic_rubric is not None
    return SemanticJudgmentReceipt.create(
        scenario_identity=scenario.identity,
        subject_identity=evidence.subject_identity,
        subject_evidence_root=evidence.evidence_root,
        rubric=scenario.semantic_rubric,
        judge_profile=_profile(),
        calibration_receipt=_calibration(),
        judge_input=SemanticJudgeInput(
            objective=scenario.objective,
            rubric=scenario.semantic_rubric,
            candidate_output=evidence.final_output or "",
        ),
        response=_response(),
    )


def test_semantic_judgment_round_trip_binds_exact_pre_semantic_root() -> None:
    scenario = _scenario(rubric=_rubric())
    subject_evidence = _subject_evidence(scenario)
    receipt = _receipt(scenario, subject_evidence)
    recorded = append_semantic_judgment(subject_evidence, receipt)

    verified = verify_semantic_judgment(scenario, recorded)

    assert verified == receipt
    assert recorded.events[-1].kind is EvidenceKind.SEMANTIC_JUDGMENT
    assert recorded.events[-1].critical is False
    assert (
        evidence_before_semantic_judgment(recorded).evidence_root == subject_evidence.evidence_root
    )


def test_semantic_judgment_is_forbidden_without_scenario_rubric() -> None:
    rubric_scenario = _scenario(rubric=_rubric())
    subject_evidence = _subject_evidence(rubric_scenario)
    recorded = append_semantic_judgment(
        subject_evidence,
        _receipt(rubric_scenario, subject_evidence),
    )
    deterministic_scenario = _scenario()
    rebound = TrialEvidence(
        trial_id=recorded.trial_id,
        subject_identity=recorded.subject_identity,
        scenario_identity=deterministic_scenario.identity,
        events=recorded.events,
        final_output=recorded.final_output,
    )

    with pytest.raises(SemanticJudgmentError, match="without a semantic rubric"):
        verify_semantic_judgment(deterministic_scenario, rebound)


def test_semantic_judgment_must_be_unique_terminal_and_from_known_source() -> None:
    scenario = _scenario(rubric=_rubric())
    subject_evidence = _subject_evidence(scenario)
    receipt = _receipt(scenario, subject_evidence)
    valid = append_semantic_judgment(subject_evidence, receipt)
    semantic = valid.events[-1]

    reordered = TrialEvidence(
        trial_id=valid.trial_id,
        subject_identity=valid.subject_identity,
        scenario_identity=valid.scenario_identity,
        events=(
            semantic.model_copy(update={"sequence": 0}),
            subject_evidence.events[0].model_copy(update={"sequence": 1}),
        ),
        final_output=valid.final_output,
    )
    with pytest.raises(SemanticJudgmentError, match="terminal evaluator event"):
        verify_semantic_judgment(scenario, reordered)

    duplicated = TrialEvidence(
        trial_id=valid.trial_id,
        subject_identity=valid.subject_identity,
        scenario_identity=valid.scenario_identity,
        events=(
            *subject_evidence.events,
            semantic,
            semantic.model_copy(update={"sequence": 2}),
        ),
        final_output=valid.final_output,
    )
    with pytest.raises(SemanticJudgmentError, match="at most one"):
        verify_semantic_judgment(scenario, duplicated)

    wrong_source = valid.model_copy(
        update={
            "events": (
                *valid.events[:-1],
                semantic.model_copy(update={"source": "evaluator:unknown-semantic-judge"}),
            )
        }
    )
    with pytest.raises(SemanticJudgmentError, match="source is not recognized"):
        verify_semantic_judgment(scenario, wrong_source)


def test_semantic_judgment_cannot_claim_critical_authority() -> None:
    scenario = _scenario(rubric=_rubric())
    subject_evidence = _subject_evidence(scenario)
    valid = append_semantic_judgment(subject_evidence, _receipt(scenario, subject_evidence))
    semantic = valid.events[-1]
    critical = valid.model_copy(
        update={
            "events": (
                *valid.events[:-1],
                semantic.model_copy(update={"critical": True}),
            )
        }
    )

    with pytest.raises(SemanticJudgmentError, match="must not claim critical authority"):
        verify_semantic_judgment(scenario, critical)


def test_semantic_judgment_rejects_pre_semantic_root_mismatch() -> None:
    scenario = _scenario(rubric=_rubric())
    first = _subject_evidence(scenario, output="First answer.")
    second = _subject_evidence(scenario, output="Second answer.")
    receipt = _receipt(scenario, first)
    event = EvidenceEvent(
        sequence=len(second.events),
        kind=EvidenceKind.SEMANTIC_JUDGMENT,
        source=SEMANTIC_JUDGMENT_SOURCE,
        payload=receipt.model_dump(mode="json"),
    )
    mismatched = TrialEvidence(
        trial_id=second.trial_id,
        subject_identity=second.subject_identity,
        scenario_identity=second.scenario_identity,
        events=(*second.events, event),
        final_output=second.final_output,
    )

    with pytest.raises(SemanticJudgmentError, match="pre-judgment subject evidence root"):
        verify_semantic_judgment(scenario, mismatched)


def test_append_semantic_judgment_rejects_duplicate_or_wrong_binding() -> None:
    scenario = _scenario(rubric=_rubric())
    first = _subject_evidence(scenario, output="First answer.")
    second = _subject_evidence(scenario, output="Second answer.")
    receipt = _receipt(scenario, first)

    with pytest.raises(SemanticJudgmentError, match="pre-judgment subject evidence root"):
        append_semantic_judgment(second, receipt)

    recorded = append_semantic_judgment(first, receipt)
    with pytest.raises(SemanticJudgmentError, match="already contains"):
        append_semantic_judgment(recorded, receipt)
