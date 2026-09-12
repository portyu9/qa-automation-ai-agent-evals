from __future__ import annotations

import pytest

from agent_evals.adversarial import AttackChannel, AttackFixture
from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import (
    ApprovalDecision,
    ApprovalIntentSpec,
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.retrieval.models import (
    RetrievalChunkSpec,
    RetrievalContractSpec,
    RetrievalCorpusSpec,
    RetrievalQuerySpec,
)
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.sampling import (
    RandomnessStatus,
    SamplingPolicy,
    SessionSamplingMetadata,
    StoppingRule,
)
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.security.taxonomy import ThreatClass
from agent_evals.statistics.reliability import ReliabilityReport

_SUBJECT = "a" * 64
_CAMPAIGN_ID = "assurance-pregrading"
_RUNTIME_ADAPTER = "fixture-runtime"
_SUBJECT_ADAPTER = "fixture-subject"
_SUBJECT_ADAPTER_VERSION = "1"
_PASS_ORACLES = (
    OracleResult(name="policy", verdict=TrialVerdict.PASS),
    OracleResult(name="outcome", verdict=TrialVerdict.PASS),
)
_POLICY = ReleasePolicy(
    min_resolved_trials=1,
    min_success_rate=0.0,
    min_wilson_low=0.0,
    max_critical_violations=0,
    max_blocked_trials=1,
    max_inconclusive_trials=0,
)


def _scenario(**overrides: object) -> EvaluationScenario:
    data: dict[str, object] = {
        "scenario_id": "assurance.pregrading",
        "revision": "1",
        "kind": ScenarioKind.REGRESSION,
        "objective": "Reject assurance claims that bypass runtime pre-grading closure.",
    }
    data.update(overrides)
    return EvaluationScenario.model_validate(data)


def _session(
    scenario: EvaluationScenario,
    *,
    events: tuple[EvidenceEvent, ...] = (),
    verdict: TrialVerdict = TrialVerdict.PASS,
) -> EvaluationSessionResult:
    evidence = TrialEvidence(
        trial_id=f"campaign:{_CAMPAIGN_ID}:attempt:0000",
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        events=events,
        final_state={"ok": True},
    )
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=_PASS_ORACLES if verdict is TrialVerdict.PASS else (),
        verdict=verdict,
    )
    return EvaluationSessionResult(
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((verdict,)),
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


def _report(
    scenario: EvaluationScenario,
    *,
    events: tuple[EvidenceEvent, ...] = (),
    verdict: TrialVerdict = TrialVerdict.PASS,
) -> AssuranceReport:
    return AssuranceReport.from_session(
        _session(scenario, events=events, verdict=verdict),
        scenario=scenario,
        release_policy=_POLICY,
    )


@pytest.mark.parametrize(
    "kind,payload",
    [
        (
            EvidenceKind.EVALUATION_ERROR,
            {"code": "fixture_failure", "reason": "evaluation precondition did not close"},
        ),
        (
            EvidenceKind.RUNTIME_ERROR,
            {"exception_type": "RuntimeError", "detail_retained": False},
        ),
    ],
)
def test_resolved_assurance_trial_rejects_existing_blocking_evidence(
    kind: EvidenceKind,
    payload: dict[str, object],
) -> None:
    scenario = _scenario()
    event = EvidenceEvent(
        sequence=0,
        kind=kind,
        source="fixture:pregrading-closure",
        payload=payload,
        critical=True,
    )

    with pytest.raises(
        ValueError,
        match="non-blocked assurance trial contains evaluator/runtime blocking evidence",
    ):
        _report(scenario, events=(event,))


def test_resolved_assurance_trial_rejects_missing_attack_delivery() -> None:
    base = _scenario()
    attack = AttackFixture.from_payload(
        attack_id="assurance-pregrading-attack",
        revision="1",
        threat=ThreatClass.DIRECT_PROMPT_INJECTION,
        channel=AttackChannel.USER_INPUT,
        payload={"message": "Controlled adversarial input."},
    )
    scenario = attack.apply(base)

    with pytest.raises(ValueError, match="attack_delivery_unverified"):
        _report(scenario)


def test_resolved_assurance_trial_rejects_missing_retrieval_delivery() -> None:
    corpus = RetrievalCorpusSpec(
        corpus_id="assurance-pregrading-corpus",
        revision="1",
        chunks=(
            RetrievalChunkSpec(
                chunk_id="chunk-1",
                document_id="document-1",
                source="fixture://assurance-pregrading",
                content="Bound retrieval context.",
            ),
        ),
    )
    scenario = _scenario(
        retrieval=RetrievalContractSpec(
            corpus=corpus,
            query=RetrievalQuerySpec(query="Bound retrieval context.", top_k=1),
        )
    )

    with pytest.raises(ValueError, match="retrieval_delivery_unverified"):
        _report(scenario)


def test_resolved_assurance_trial_rejects_missing_approval_intent_decision() -> None:
    scenario = _scenario(
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"refund"}),
            approval_required_tools=frozenset({"refund"}),
        ),
        approval_intent=ApprovalIntentSpec(
            agent="approval-agent",
            tool="refund",
            decision=ApprovalDecision.APPROVE,
        ),
    )

    with pytest.raises(ValueError, match="approval_intent_unverified"):
        _report(scenario)


def test_resolved_assurance_trial_rejects_malformed_present_protocol_delivery() -> None:
    scenario = _scenario()
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.PROTOCOL_DELIVERY,
        source="bridge:mcp-agent:unsupported",
        payload={},
    )

    with pytest.raises(ValueError, match="protocol_delivery_unverified"):
        _report(scenario, events=(event,))


def test_ordinary_resolved_pass_remains_valid() -> None:
    report = _report(_scenario())

    assert report.trials[0].verdict is TrialVerdict.PASS
    assert tuple(result.name for result in report.trials[0].oracle_results) == (
        "policy",
        "outcome",
    )


def test_blocked_history_remains_valid_without_reclosing_failed_precondition() -> None:
    scenario = _scenario()
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.EVALUATION_ERROR,
        source="evaluator:attack-delivery",
        payload={
            "code": "attack_delivery_unverified",
            "reason": "controlled delivery could not be proven",
        },
        critical=True,
    )

    report = _report(scenario, events=(event,), verdict=TrialVerdict.BLOCKED)

    assert report.trials[0].verdict is TrialVerdict.BLOCKED
    assert report.trials[0].oracle_results == ()
