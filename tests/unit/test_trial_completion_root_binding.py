from __future__ import annotations

import pytest

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

SUBJECT = "a" * 64
SCENARIO_CONTRACT = EvaluationScenario(
    scenario_id="assurance.completion-root",
    revision="1",
    kind=ScenarioKind.REGRESSION,
    objective="Verify final trial evidence root binding.",
)
SCENARIO = SCENARIO_CONTRACT.identity


def _policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=1,
        max_inconclusive_trials=0,
    )


def _session(trial: EvaluatedTrial) -> EvaluationSessionResult:
    return EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((trial.verdict,)),
    )


def _report(session: EvaluationSessionResult) -> AssuranceReport:
    return AssuranceReport.from_session(
        session,
        scenario=SCENARIO_CONTRACT,
        release_policy=_policy(),
    )


def _resolved_trial(*, with_event: bool = False) -> EvaluatedTrial:
    events: tuple[EvidenceEvent, ...] = ()
    if with_event:
        events = (
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.STATE,
                source="adapter:test",
                payload={"nested": {"status": "ok"}},
            ),
        )
    return EvaluatedTrial(
        evidence=TrialEvidence(
            trial_id="trial-0",
            subject_identity=SUBJECT,
            scenario_identity=SCENARIO,
            events=events,
            final_state={"nested": {"status": "ok"}},
        ),
        oracle_results=(
            OracleResult(name="policy", verdict=TrialVerdict.PASS),
            OracleResult(name="outcome", verdict=TrialVerdict.PASS),
        ),
        verdict=TrialVerdict.PASS,
    )


def test_resolved_and_blocked_trials_capture_completion_root_automatically() -> None:
    resolved = _resolved_trial()
    blocked = EvaluatedTrial(
        evidence=TrialEvidence(
            trial_id="trial-blocked",
            subject_identity=SUBJECT,
            scenario_identity=SCENARIO,
        ),
        oracle_results=(),
        verdict=TrialVerdict.BLOCKED,
    )

    assert resolved.completion_evidence_root == resolved.evidence.evidence_root
    assert blocked.completion_evidence_root == blocked.evidence.evidence_root


def test_report_rejects_final_state_mutation_after_trial_finalization() -> None:
    trial = _resolved_trial()
    completion_root = trial.completion_evidence_root
    nested = trial.evidence.final_state["nested"]
    assert isinstance(nested, dict)
    nested["status"] = "mutated-after-finalization"

    assert trial.evidence.evidence_root != completion_root
    with pytest.raises(ValueError, match="evidence root changed after evaluation finalization"):
        _report(_session(trial))


def test_report_rejects_event_payload_mutation_after_trial_finalization() -> None:
    trial = _resolved_trial(with_event=True)
    completion_root = trial.completion_evidence_root
    nested = trial.evidence.events[0].payload["nested"]
    assert isinstance(nested, dict)
    nested["status"] = "mutated-after-finalization"

    assert trial.evidence.evidence_root != completion_root
    with pytest.raises(ValueError, match="evidence root changed after evaluation finalization"):
        _report(_session(trial))


def test_unchanged_trial_preserves_assurance_v4_shape_and_root_determinism() -> None:
    trial = _resolved_trial()
    session = _session(trial)

    first = _report(session)
    second = _report(session)
    payload = first.model_dump(mode="json")

    assert first == second
    assert first.report_root == second.report_root
    assert first.trials[0].evidence_root == trial.completion_evidence_root
    assert "completion_evidence_root" not in payload
    assert "completion_evidence_root" not in payload["trials"][0]
