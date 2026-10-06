"""Evaluator-owned derivation of release criticality from finalized session records."""

from __future__ import annotations

from agent_evals.gates.release import _reliability_report_sha256
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.verification import (
    VerifiedCriticalityRecord,
    _issue_verified_criticality_record,
)


def verify_session_release_criticality(
    session: EvaluationSessionResult,
) -> VerifiedCriticalityRecord:
    """Derive non-compensatory release criticality from one exact finalized session.

    The session revalidates evidence-root finalization, verdict-derived reliability, and repeated
    trial provenance before any count is issued. The returned record is bound to the exact
    ReliabilityReport scalars used by the release gate.
    """

    if type(session) is not EvaluationSessionResult:
        raise ValueError("release criticality requires an exact EvaluationSessionResult")
    session.validate()
    roots = tuple(trial.completion_evidence_root for trial in session.trials)
    return _issue_verified_criticality_record(
        subject_identity=session.subject_identity,
        scenario_identity=session.scenario_identity,
        trial_evidence_roots=roots,
        reliability_sha256=_reliability_report_sha256(session.reliability),
        critical_violations=session.critical_violations,
    )
