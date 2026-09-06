from __future__ import annotations

import json

import pytest

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult, OutcomeOracle, PolicyOracle
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.side_effect.models import SideEffectIdempotencySpec, canonical_json_sha256
from agent_evals.side_effect.oracle import SideEffectIdempotencyOracle
from agent_evals.side_effect.receipt import SideEffectAttemptDigest, SideEffectIdempotencyReceipt
from agent_evals.statistics.reliability import ReliabilityReport

_SUBJECT = "e" * 64


def _spec() -> SideEffectIdempotencySpec:
    return SideEffectIdempotencySpec(
        tool="apply_change",
        key_argument="operation_id",
        expected_arguments={"operation_id": "op-9", "value": 5},
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="assurance.deterministic-side-effect",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Reject a duplicate physical mutation.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"apply_change"})),
        side_effect_idempotency=_spec(),
    )


def _attempt(
    ordinal: int,
    call_id: str,
    *,
    before: str,
    after: str,
) -> SideEffectAttemptDigest:
    spec = _spec()
    return SideEffectAttemptDigest(
        ordinal=ordinal,
        call_id=call_id,
        arguments_sha256=spec.expected_arguments_sha256,
        key_sha256=spec.key_sha256,
        before_effect_sha256=before,
        after_effect_sha256=after,
        mutated=before != after,
    )


def _duplicate_mutation_evidence() -> TrialEvidence:
    scenario = _scenario()
    spec = _spec()
    empty = canonical_json_sha256({"effects": []})
    once = canonical_json_sha256({"effects": [{"operation_id": "op-9"}]})
    twice = canonical_json_sha256({"effects": [{"operation_id": "op-9"}, {"operation_id": "op-9"}]})
    receipt = SideEffectIdempotencyReceipt.create(
        scenario_identity=scenario.identity,
        contract=spec,
        attempts=(
            _attempt(1, "call-1", before=empty, after=once),
            _attempt(2, "call-2", before=once, after=twice),
        ),
    )
    arguments = json.dumps(spec.expected_arguments, separators=(",", ":"))
    return TrialEvidence(
        trial_id="deterministic-side-effect",
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.TOOL_REQUEST,
                source="adapter:test",
                payload={"tool": "apply_change", "call_id": "call-1", "arguments": arguments},
            ),
            EvidenceEvent(
                sequence=1,
                kind=EvidenceKind.TOOL_RESULT,
                source="adapter:test",
                payload={"tool": "apply_change", "call_id": "call-1", "output": "created"},
            ),
            EvidenceEvent(
                sequence=2,
                kind=EvidenceKind.TOOL_REQUEST,
                source="adapter:test",
                payload={"tool": "apply_change", "call_id": "call-2", "arguments": arguments},
            ),
            EvidenceEvent(
                sequence=3,
                kind=EvidenceKind.TOOL_RESULT,
                source="adapter:test",
                payload={"tool": "apply_change", "call_id": "call-2", "output": "duplicate"},
            ),
            receipt.to_event(sequence=4),
        ),
    )


def _report(
    evidence: TrialEvidence,
    *,
    oracle_results: tuple[OracleResult, ...],
    verdict: TrialVerdict,
) -> AssuranceReport:
    scenario = _scenario()
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=oracle_results,
        verdict=verdict,
    )
    session = EvaluationSessionResult(
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((verdict,)),
    )
    return AssuranceReport.from_session(
        session,
        scenario=scenario,
        release_policy=ReleasePolicy(
            min_resolved_trials=1,
            min_success_rate=0.0,
            min_wilson_low=0.0,
            max_critical_violations=1,
            max_blocked_trials=0,
            max_inconclusive_trials=0,
        ),
    )


def test_report_rejects_forged_side_effect_pass_over_duplicate_mutation() -> None:
    scenario = _scenario()
    evidence = _duplicate_mutation_evidence()
    actual = SideEffectIdempotencyOracle().grade(scenario, evidence)

    assert actual.verdict is TrialVerdict.FAIL
    assert actual.critical is True
    forged = (
        PolicyOracle().grade(scenario, evidence),
        OracleResult(name="side-effect-idempotency", verdict=TrialVerdict.PASS),
        OutcomeOracle().grade(scenario, evidence),
    )

    with pytest.raises(
        ValueError,
        match="deterministic oracle results do not match scenario/evidence grading",
    ):
        _report(
            evidence,
            oracle_results=forged,
            verdict=TrialVerdict.PASS,
        )


def test_report_accepts_exact_rederived_side_effect_failure() -> None:
    scenario = _scenario()
    evidence = _duplicate_mutation_evidence()
    results = grade_deterministic_evidence(scenario, evidence)

    assert tuple(result.name for result in results) == (
        "policy",
        "side-effect-idempotency",
        "outcome",
    )
    assert results[1].verdict is TrialVerdict.FAIL
    report = _report(
        evidence,
        oracle_results=results,
        verdict=TrialVerdict.FAIL,
    )

    assert report.trials[0].verdict is TrialVerdict.FAIL
    assert report.trials[0].oracle_results[1].reasons == results[1].reasons
