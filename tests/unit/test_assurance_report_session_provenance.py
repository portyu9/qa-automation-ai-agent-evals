from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.gates.release import ReleasePolicy
from agent_evals.runtime.reset_isolation import ResetIsolationContext, ResetIsolationObservation
from agent_evals.runtime.sampling import (
    RandomnessControlContext,
    RandomnessControlObservation,
    RandomnessStatus,
)
from agent_evals.runtime.session import EvaluationSession, IndependenceStatus


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="report-session-provenance-v1",
        instructions="Return the expected state.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="report-subject",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="assurance.report-session-provenance",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Exercise durable repeated-trial provenance.",
        required_outcomes={"status": "ok"},
    )


def _adapter() -> ScriptedAdapter:
    return ScriptedAdapter(
        lambda _subject_value, _scenario_value, _trial_id: AdapterResult(
            final_state={"status": "ok"}
        ),
        name="report-runtime",
    )


def _policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=0,
        max_inconclusive_trials=0,
    )


class _ResetControl:
    strategy_name = "test-reset"
    strategy_version = "1"

    async def reset(self, *, context: ResetIsolationContext) -> ResetIsolationObservation:
        return ResetIsolationObservation(
            control_evidence_identity=_sha(
                f"reset:{context.campaign_id}:{context.attempt_index}:"
                f"{context.previous_trial_id}:{context.next_trial_id}"
            )
        )


class _RandomnessControl:
    strategy_name = "test-randomness"
    strategy_version = "1"

    async def prepare(
        self,
        *,
        context: RandomnessControlContext,
    ) -> RandomnessControlObservation:
        return RandomnessControlObservation(
            seed_identity=_sha(f"seed:{context.campaign_id}:{context.attempt_index}"),
            control_evidence_identity=_sha(
                f"randomness:{context.campaign_id}:{context.attempt_index}:{context.trial_id}"
            ),
        )


async def _operator_report() -> AssuranceReport:
    scenario = _scenario()
    session = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=scenario,
        trials=2,
        campaign_id="report-operator",
        independence_status=IndependenceStatus.OPERATOR_ASSERTED,
        independence_basis="Operator asserts the environment is independently reset outside the evaluator.",
        randomness_status=RandomnessStatus.UNKNOWN,
    )
    return AssuranceReport.from_session(session, scenario=scenario, release_policy=_policy())


async def _verified_report() -> AssuranceReport:
    scenario = _scenario()
    session = await EvaluationSession().run(
        _adapter(),
        subject=_subject(),
        scenario=scenario,
        trials=3,
        campaign_id="report-verified",
        independence_status=IndependenceStatus.VERIFIED,
        reset_control=_ResetControl(),
        randomness_status=RandomnessStatus.EVALUATOR_CONTROLLED,
        randomness_control=_RandomnessControl(),
    )
    return AssuranceReport.from_session(session, scenario=scenario, release_policy=_policy())


@pytest.mark.asyncio
async def test_operator_assertion_is_persisted_without_verification_upgrade() -> None:
    report = await _operator_report()

    assert report.schema_version == "agent-evals/assurance-report/v6"
    assert report.session_provenance.independence_status is IndependenceStatus.OPERATOR_ASSERTED
    assert report.session_provenance.independence_basis is not None
    assert report.session_provenance.reset_strategy_name is None
    assert report.session_provenance.reset_isolation_receipts == ()
    assert report.session_provenance.sampling_metadata.schema_version == (
        "agent-evals/session-sampling/v1"
    )

    loaded = AssuranceReport.model_validate_json(report.model_dump_json())
    assert loaded == report


@pytest.mark.asyncio
async def test_verified_report_persists_and_rederives_reset_and_randomness_receipts() -> None:
    report = await _verified_report()
    provenance = report.session_provenance

    assert provenance.independence_status is IndependenceStatus.VERIFIED
    assert provenance.independence_basis is None
    assert provenance.reset_strategy_name == "test-reset"
    assert provenance.reset_strategy_version == "1"
    assert len(provenance.reset_isolation_receipts) == 2
    assert len(provenance.reset_receipt_roots) == 2
    assert provenance.sampling_metadata.randomness_status is RandomnessStatus.EVALUATOR_CONTROLLED
    assert provenance.sampling_metadata.randomness_strategy_name == "test-randomness"
    assert len(provenance.randomness_receipt_roots) == 3

    loaded = AssuranceReport.model_validate_json(report.model_dump_json())
    assert loaded == report


@pytest.mark.asyncio
async def test_operator_assertion_basis_is_report_root_bound() -> None:
    report = await _operator_report()
    payload = report.model_dump(mode="json")
    payload["session_provenance"]["independence_basis"] = "Different operator assertion."

    with pytest.raises(ValidationError, match="report root does not match"):
        AssuranceReport.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing", "reordered", "duplicate"])
async def test_verified_reset_provenance_rejects_missing_reordered_or_duplicate_receipts(
    mutation: str,
) -> None:
    report = await _verified_report()
    payload = deepcopy(report.model_dump(mode="json"))
    receipts = payload["session_provenance"]["reset_isolation_receipts"]
    assert len(receipts) == 2
    if mutation == "missing":
        del receipts[0]
    elif mutation == "reordered":
        receipts.reverse()
    else:
        receipts[1] = deepcopy(receipts[0])

    with pytest.raises(ValidationError, match="reset/isolation provenance is invalid"):
        AssuranceReport.model_validate(payload)


@pytest.mark.asyncio
async def test_report_rejects_cross_campaign_provenance_replay() -> None:
    report = await _verified_report()
    payload = report.model_dump(mode="json")
    payload["session_provenance"]["campaign_id"] = "foreign-campaign"

    with pytest.raises(ValidationError, match="trial order does not match"):
        AssuranceReport.model_validate(payload)


@pytest.mark.asyncio
async def test_report_rejects_cross_subject_provenance_replay() -> None:
    report = await _verified_report()
    payload = report.model_dump(mode="json")
    payload["subject_identity"] = "f" * 64

    with pytest.raises(ValidationError, match="reset/isolation provenance is invalid"):
        AssuranceReport.model_validate(payload)


@pytest.mark.asyncio
async def test_report_rejects_reordered_randomness_receipts() -> None:
    report = await _verified_report()
    payload = report.model_dump(mode="json")
    receipts = payload["session_provenance"]["sampling_metadata"][
        "randomness_control_receipts"
    ]
    receipts[0], receipts[1] = receipts[1], receipts[0]

    with pytest.raises(ValidationError, match="sampling provenance is invalid"):
        AssuranceReport.model_validate(payload)


@pytest.mark.asyncio
async def test_report_rejects_mutated_reset_receipt_even_with_cached_gate_present() -> None:
    report = await _verified_report()
    payload = report.model_dump(mode="json")
    payload["session_provenance"]["reset_isolation_receipts"][0][
        "control_evidence_identity"
    ] = "0" * 64

    with pytest.raises(ValidationError, match="receipt root mismatch"):
        AssuranceReport.model_validate(payload)
