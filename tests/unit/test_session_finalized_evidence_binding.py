from __future__ import annotations

import pytest

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def _trial(
    *,
    trial_id: str = "trial-0",
    subject_identity: str = SUBJECT,
    scenario_identity: str = SCENARIO,
    with_event: bool = False,
) -> EvaluatedTrial:
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
            trial_id=trial_id,
            subject_identity=subject_identity,
            scenario_identity=scenario_identity,
            events=events,
            final_state={"nested": {"status": "ok"}},
        ),
        oracle_results=(
            OracleResult(name="policy", verdict=TrialVerdict.PASS),
            OracleResult(name="outcome", verdict=TrialVerdict.PASS),
        ),
        verdict=TrialVerdict.PASS,
    )


def _session(
    *trials: EvaluatedTrial,
    reliability: ReliabilityReport | None = None,
    subject_identity: str = SUBJECT,
    scenario_identity: str = SCENARIO,
) -> EvaluationSessionResult:
    if reliability is None:
        reliability = ReliabilityReport.from_verdicts(tuple(trial.verdict for trial in trials))
    return EvaluationSessionResult(
        subject_identity=subject_identity,
        scenario_identity=scenario_identity,
        trials=trials,
        reliability=reliability,
    )


def _release_policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=1.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=0,
        max_inconclusive_trials=0,
    )


def _direct_release(session: EvaluationSessionResult) -> GateDecision:
    return ReleaseGate(_release_policy()).decide(
        session.reliability,
        critical_violations=session.critical_violations,
    ).decision


def test_unchanged_session_remains_release_gradeable() -> None:
    session = _session(_trial())

    assert session.critical_violations == 0
    assert _direct_release(session) is GateDecision.ACCEPT


def test_direct_release_rejects_final_state_mutation_after_trial_finalization() -> None:
    session = _session(_trial())
    nested = session.trials[0].evidence.final_state["nested"]
    assert isinstance(nested, dict)
    nested["status"] = "mutated-after-finalization"

    with pytest.raises(ValueError, match="evidence root changed after evaluation finalization"):
        _direct_release(session)


def test_direct_release_rejects_event_payload_mutation_after_trial_finalization() -> None:
    session = _session(_trial(with_event=True))
    nested = session.trials[0].evidence.events[0].payload["nested"]
    assert isinstance(nested, dict)
    nested["status"] = "mutated-after-finalization"

    with pytest.raises(ValueError, match="evidence root changed after evaluation finalization"):
        _direct_release(session)


def test_session_criticality_rejects_reliability_that_disagrees_with_trial_verdicts() -> None:
    trial = _trial()
    inconsistent = ReliabilityReport.from_verdicts((TrialVerdict.FAIL,))
    session = _session(trial, reliability=inconsistent)

    with pytest.raises(ValueError, match="session reliability does not recompute from trial verdicts"):
        _ = session.critical_violations


def test_session_criticality_rejects_trial_subject_identity_mismatch() -> None:
    session = _session(_trial(subject_identity="c" * 64))

    with pytest.raises(ValueError, match="trial evidence subject identity does not match session"):
        _ = session.critical_violations


def test_session_criticality_rejects_trial_scenario_identity_mismatch() -> None:
    session = _session(_trial(scenario_identity="d" * 64))

    with pytest.raises(ValueError, match="trial evidence scenario identity does not match session"):
        _ = session.critical_violations


def test_session_criticality_rejects_duplicate_trial_ids() -> None:
    session = _session(_trial(), _trial())

    with pytest.raises(ValueError, match="session contains duplicate trial IDs"):
        _ = session.critical_violations
