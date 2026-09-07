from __future__ import annotations

import pytest

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import ReleasePolicy
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

_SUBJECT = "a" * 64
_POLICY = ReleasePolicy(
    min_resolved_trials=0,
    min_success_rate=0.0,
    min_wilson_low=0.0,
    max_critical_violations=0,
    max_blocked_trials=1,
    max_inconclusive_trials=0,
)


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="assurance.blocked-evidence-binding",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Bind blocked assurance history to durable evaluator/runtime blocking evidence.",
    )


def _session(*, events: tuple[EvidenceEvent, ...]) -> EvaluationSessionResult:
    scenario = _scenario()
    evidence = TrialEvidence(
        trial_id="blocked-evidence-binding",
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        events=events,
        final_state={"protected": "safe"},
    )
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=(),
        verdict=TrialVerdict.BLOCKED,
    )
    return EvaluationSessionResult(
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((TrialVerdict.BLOCKED,)),
    )


def _report(*, events: tuple[EvidenceEvent, ...]) -> AssuranceReport:
    return AssuranceReport.from_session(
        _session(events=events),
        scenario=_scenario(),
        release_policy=_POLICY,
    )


def test_blocked_assurance_trial_rejects_clean_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="blocked assurance trial contains no evaluator/runtime blocking evidence",
    ):
        _report(events=())


@pytest.mark.parametrize(
    "kind,payload",
    [
        (
            EvidenceKind.EVALUATION_ERROR,
            {
                "code": "controlled_precondition_failure",
                "reason": "controlled evaluation precondition did not close",
            },
        ),
        (
            EvidenceKind.RUNTIME_ERROR,
            {"exception_type": "RuntimeError", "detail_retained": False},
        ),
    ],
)
def test_blocked_assurance_trial_accepts_durable_blocking_history(
    kind: EvidenceKind,
    payload: dict[str, object],
) -> None:
    event = EvidenceEvent(
        sequence=0,
        kind=kind,
        source="fixture:blocked-evidence-binding",
        payload=payload,
        critical=True,
    )

    report = _report(events=(event,))

    assert report.trials[0].verdict is TrialVerdict.BLOCKED
    assert report.trials[0].oracle_results == ()
    assert report.reliability.blocked == 1
