from __future__ import annotations

from pathlib import Path

import pytest

from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.evidence.store import LocalEvidenceStore
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.runtime.evaluator import TrialRunner
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="replay-policy-test",
        model="recorded",
        application_revision="1",
        instructions="Return the expected state.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "none"},
        adapter="recorded",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="replay.blocked-policy-criticality",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Preserve known blocked policy facts across replay and assurance.",
        required_outcomes={"status": "ok"},
    )


def _policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=1,
        max_inconclusive_trials=0,
    )


@pytest.mark.asyncio
async def test_persisted_blocked_policy_fact_survives_replay_session_and_assurance(
    tmp_path: Path,
) -> None:
    subject = _subject()
    scenario = _scenario()
    original = TrialEvidence(
        trial_id="replay-blocked-policy",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.POLICY_VIOLATION,
                source="openai-agents:runner",
                payload={"reason": "turn budget exceeded", "max_turns": 2},
                critical=False,
            ),
            EvidenceEvent(
                sequence=1,
                kind=EvidenceKind.EVALUATION_ERROR,
                source="evaluator:approval-intent",
                payload={
                    "code": "approval_intent_unverified",
                    "reason": "approval continuation relation could not be reconstructed",
                },
                critical=True,
            ),
        ),
        final_state={"status": "ok"},
    )
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(original)

    replayed = await TrialRunner().run(
        EvidenceReplayAdapter.from_store(store, manifest.record_key),
        subject=subject,
        scenario=scenario,
        trial_id=original.trial_id,
    )

    assert replayed.verdict is TrialVerdict.BLOCKED
    assert replayed.oracle_results == ()
    assert replayed.evidence == original
    assert replayed.critical_violations == 1

    reliability = ReliabilityReport.from_verdicts((replayed.verdict,))
    session = EvaluationSessionResult(
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        trials=(replayed,),
        reliability=reliability,
    )
    policy = _policy()

    assert session.critical_violations == 1
    assert (
        ReleaseGate(policy).decide(
            session.reliability,
            critical_violations=session.critical_violations,
        ).decision
        is GateDecision.REJECT
    )

    report = AssuranceReport.from_session(
        session,
        scenario=scenario,
        release_policy=policy,
    )
    assert report.schema_version == "agent-evals/assurance-report/v5"
    assert report.critical_violations == session.critical_violations == 1
    assert report.trials[0].blocked_policy_violations[0].event_digest == original.events[0].digest
    assert report.gate.decision is GateDecision.REJECT
