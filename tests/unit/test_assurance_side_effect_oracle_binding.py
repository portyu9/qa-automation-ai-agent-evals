from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult, OutcomeOracle, PolicyOracle
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.sampling import (
    RandomnessStatus,
    SamplingPolicy,
    SessionSamplingMetadata,
    StoppingRule,
)
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.side_effect.models import SideEffectIdempotencySpec, canonical_json_sha256
from agent_evals.side_effect.oracle import SideEffectIdempotencyOracle
from agent_evals.side_effect.receipt import SideEffectAttemptDigest, SideEffectIdempotencyReceipt
from agent_evals.statistics.reliability import ReliabilityReport

SUBJECT = "1" * 64
_CAMPAIGN_ID = "assurance-side-effect-binding"
_RUNTIME_ADAPTER = "fixture-runtime"
_SUBJECT_ADAPTER = "fixture-subject"
_SUBJECT_ADAPTER_VERSION = "1"


def _trial_id() -> str:
    return f"campaign:{_CAMPAIGN_ID}:attempt:0000"


def _spec() -> SideEffectIdempotencySpec:
    return SideEffectIdempotencySpec(
        tool="apply_change",
        key_argument="operation_id",
        expected_arguments={"operation_id": "op-7", "value": 3},
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="assurance.side-effect-binding",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Apply one logical change safely across a duplicate attempt.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"apply_change"})),
        side_effect_idempotency=_spec(),
    )


def _plain_scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="assurance.core-only",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Return a deterministic result.",
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


def _receipt(*, second_mutates: bool) -> SideEffectIdempotencyReceipt:
    empty = canonical_json_sha256({"effects": []})
    once = canonical_json_sha256({"effects": [{"operation_id": "op-7"}]})
    twice = canonical_json_sha256({"effects": [{"operation_id": "op-7"}, {"operation_id": "op-7"}]})
    return SideEffectIdempotencyReceipt.create(
        scenario_identity=_scenario().identity,
        contract=_spec(),
        attempts=(
            _attempt(1, "call-1", before=empty, after=once),
            _attempt(2, "call-2", before=once, after=twice if second_mutates else once),
        ),
    )


def _side_effect_evidence(*, second_mutates: bool) -> TrialEvidence:
    arguments = json.dumps(_spec().expected_arguments, separators=(",", ":"))
    receipt = _receipt(second_mutates=second_mutates)
    return TrialEvidence(
        trial_id=_trial_id(),
        subject_identity=SUBJECT,
        scenario_identity=_scenario().identity,
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


def _core_results(
    scenario: EvaluationScenario, evidence: TrialEvidence
) -> tuple[OracleResult, ...]:
    return (
        PolicyOracle().grade(scenario, evidence),
        OutcomeOracle().grade(scenario, evidence),
    )


def _runtime_results(evidence: TrialEvidence) -> tuple[OracleResult, ...]:
    scenario = _scenario()
    return (
        PolicyOracle().grade(scenario, evidence),
        SideEffectIdempotencyOracle().grade(scenario, evidence),
        OutcomeOracle().grade(scenario, evidence),
    )


def _session(trial: EvaluatedTrial) -> EvaluationSessionResult:
    return EvaluationSessionResult(
        subject_identity=trial.evidence.subject_identity,
        scenario_identity=trial.evidence.scenario_identity,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((trial.verdict,), k=1),
        campaign_id=_CAMPAIGN_ID,
        runtime_adapter_name=_RUNTIME_ADAPTER,
        subject_adapter=_SUBJECT_ADAPTER,
        subject_adapter_version=_SUBJECT_ADAPTER_VERSION,
        sampling_metadata=SessionSamplingMetadata(
            sampling_policy=SamplingPolicy.PREDECLARED_ALL_ATTEMPTS,
            randomness_status=RandomnessStatus.UNKNOWN,
            stopping_rule=StoppingRule.FIXED_HORIZON,
            planned_trials=1,
        ),
    )


def _release_policy(*, max_blocked_trials: int = 0) -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=max_blocked_trials,
        max_inconclusive_trials=0,
    )


def test_report_rejects_dropped_side_effect_oracle_for_duplicate_mutation_evidence() -> None:
    scenario = _scenario()
    evidence = _side_effect_evidence(second_mutates=True)
    side_effect = SideEffectIdempotencyOracle().grade(scenario, evidence)
    core = _core_results(scenario, evidence)

    assert side_effect.verdict is TrialVerdict.FAIL
    assert side_effect.critical is True
    assert all(result.verdict is TrialVerdict.PASS for result in core)

    forged = EvaluatedTrial(
        evidence=evidence,
        oracle_results=core,
        verdict=TrialVerdict.PASS,
    )
    assert forged.completion_evidence_root == evidence.evidence_root

    with pytest.raises(ValueError, match="side-effect oracle presence does not match"):
        AssuranceReport.from_session(
            _session(forged),
            scenario=scenario,
            release_policy=_release_policy(),
        )


def test_report_rejects_side_effect_contract_when_observation_and_oracle_are_both_omitted() -> None:
    scenario = _scenario()
    evidence = TrialEvidence(
        trial_id=_trial_id(),
        subject_identity=SUBJECT,
        scenario_identity=scenario.identity,
    )
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=_core_results(scenario, evidence),
        verdict=TrialVerdict.PASS,
    )

    with pytest.raises(ValueError, match="side-effect observation evidence is invalid"):
        AssuranceReport.from_session(
            _session(trial),
            scenario=scenario,
            release_policy=_release_policy(),
        )


def test_report_rejects_side_effect_oracle_without_observation_evidence() -> None:
    scenario = _scenario()
    evidence = TrialEvidence(
        trial_id=_trial_id(),
        subject_identity=SUBJECT,
        scenario_identity=scenario.identity,
    )
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=(
            OracleResult(name="policy", verdict=TrialVerdict.PASS),
            OracleResult(name="side-effect-idempotency", verdict=TrialVerdict.PASS),
            OracleResult(name="outcome", verdict=TrialVerdict.PASS),
        ),
        verdict=TrialVerdict.PASS,
    )

    with pytest.raises(ValueError, match="side-effect observation evidence is invalid"):
        AssuranceReport.from_session(
            _session(trial),
            scenario=scenario,
            release_policy=_release_policy(),
        )


def test_report_accepts_valid_side_effect_pass_triplet() -> None:
    scenario = _scenario()
    evidence = _side_effect_evidence(second_mutates=False)
    results = _runtime_results(evidence)
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=results,
        verdict=TrialVerdict.PASS,
    )

    report = AssuranceReport.from_session(
        _session(trial),
        scenario=scenario,
        release_policy=_release_policy(),
    )

    assert tuple(result.name for result in report.trials[0].oracle_results) == (
        "policy",
        "side-effect-idempotency",
        "outcome",
    )
    assert report.grading_profile.side_effect_idempotency_identity == _spec().identity
    assert report.critical_violations == 0
    assert report.gate.decision is GateDecision.ACCEPT


def test_report_accepts_valid_side_effect_critical_fail_triplet() -> None:
    scenario = _scenario()
    evidence = _side_effect_evidence(second_mutates=True)
    results = _runtime_results(evidence)
    assert results[1].verdict is TrialVerdict.FAIL
    assert results[1].critical is True
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=results,
        verdict=TrialVerdict.FAIL,
    )

    report = AssuranceReport.from_session(
        _session(trial),
        scenario=scenario,
        release_policy=_release_policy(),
    )

    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT


def test_report_preserves_core_only_trial_without_side_effect_observation() -> None:
    scenario = _plain_scenario()
    evidence = TrialEvidence(
        trial_id=_trial_id(),
        subject_identity=SUBJECT,
        scenario_identity=scenario.identity,
    )
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=_core_results(scenario, evidence),
        verdict=TrialVerdict.PASS,
    )

    report = AssuranceReport.from_session(
        _session(trial),
        scenario=scenario,
        release_policy=_release_policy(),
    )

    assert report.grading_profile.side_effect_idempotency_identity is None
    assert report.trials[0].verdict is TrialVerdict.PASS
    assert report.gate.decision is GateDecision.ACCEPT


def test_report_json_reload_requires_profile_bound_side_effect_oracle() -> None:
    scenario = _scenario()
    evidence = _side_effect_evidence(second_mutates=False)
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=_runtime_results(evidence),
        verdict=TrialVerdict.PASS,
    )
    report = AssuranceReport.from_session(
        _session(trial),
        scenario=scenario,
        release_policy=_release_policy(),
    )
    payload = report.model_dump(mode="json")
    payload["trials"][0]["oracle_results"] = [
        result
        for result in payload["trials"][0]["oracle_results"]
        if result["name"] != "side-effect-idempotency"
    ]

    with pytest.raises(ValidationError, match="side-effect oracle presence does not match"):
        AssuranceReport.model_validate(payload)


def test_blocked_trial_may_retain_side_effect_observation_without_oracle_results() -> None:
    scenario = _scenario()
    observed = _side_effect_evidence(second_mutates=False)
    error = EvidenceEvent(
        sequence=len(observed.events),
        kind=EvidenceKind.EVALUATION_ERROR,
        source="evaluator:later-verifier",
        payload={"code": "later_verifier_failed", "reason": "historical evaluator uncertainty"},
        critical=True,
    )
    evidence = TrialEvidence(
        trial_id=observed.trial_id,
        subject_identity=observed.subject_identity,
        scenario_identity=observed.scenario_identity,
        events=(*observed.events, error),
    )
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=(),
        verdict=TrialVerdict.BLOCKED,
    )

    report = AssuranceReport.from_session(
        _session(trial),
        scenario=scenario,
        release_policy=_release_policy(max_blocked_trials=1),
    )

    assert report.trials[0].verdict is TrialVerdict.BLOCKED
    assert report.trials[0].oracle_results == ()
