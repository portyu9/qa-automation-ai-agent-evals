"""Self-validating session assurance reports bound to trial evidence and grading facts."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.models import TrialVerdict
from agent_evals.gates.release import GateDecision, GateResult, ReleaseGate, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.preconditions import (
    EvaluationPreconditionError,
    has_blocking_evidence,
    verify_pregrading_closure,
)
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.semantic.models import SemanticDecision
from agent_evals.semantic.receipt import SemanticJudgmentReceipt
from agent_evals.semantic.verification import SemanticJudgmentError, verify_semantic_judgment
from agent_evals.statistics.reliability import ReliabilityReport

_REPORT_SCHEMA: Literal["agent-evals/assurance-report/v4"] = "agent-evals/assurance-report/v4"
_EVIDENCE_SCHEMA: Literal["agent-evals/trial-evidence/v2"] = "agent-evals/trial-evidence/v2"
_REPORT_DOMAIN = b"agent-evals/assurance-report/v4\0"
_RESOLVED_VERDICTS = frozenset({TrialVerdict.PASS, TrialVerdict.FAIL})
_CORE_ORACLE_NAMES = frozenset({"policy", "outcome"})
_SIDE_EFFECT_ORACLE_NAME = "side-effect-idempotency"
_CRITICAL_ON_FAIL_ORACLE_NAMES = frozenset({"policy", _SIDE_EFFECT_ORACLE_NAME})
_NEVER_CRITICAL_ORACLE_NAMES = frozenset({"outcome"})


class OracleSnapshot(BaseModel):
    """Serialized deterministic oracle result used to rederive one trial verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    verdict: TrialVerdict
    reasons: tuple[str, ...] = ()
    critical: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_runtime_criticality(self) -> Self:
        if self.name in _CRITICAL_ON_FAIL_ORACLE_NAMES:
            expected = self.verdict is TrialVerdict.FAIL
            if self.critical is not expected:
                raise ValueError(
                    f"{self.name} oracle criticality does not match deterministic runtime contract"
                )
        elif self.name in _NEVER_CRITICAL_ORACLE_NAMES and self.critical:
            raise ValueError("outcome oracle cannot claim critical authority")
        return self

    @classmethod
    def from_oracle(cls, result: OracleResult) -> Self:
        return cls(
            name=result.name,
            verdict=result.verdict,
            reasons=result.reasons,
            critical=result.critical,
        )


class ScenarioGradingProfile(BaseModel):
    """Minimal scenario-derived commitments that determine the report-level grading shape.

    The profile intentionally does not serialize objective, state, authority, retrieval material,
    approval intent, or other scenario content. Those remain bound by ``scenario_identity`` and
    require the exact scenario/evidence replay path for historical re-establishment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    semantic_rubric_identity: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    side_effect_idempotency_identity: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @classmethod
    def from_scenario(cls, scenario: EvaluationScenario) -> Self:
        rubric = scenario.semantic_rubric
        side_effect = scenario.side_effect_idempotency
        return cls(
            semantic_rubric_identity=rubric.identity if rubric is not None else None,
            side_effect_idempotency_identity=(
                side_effect.identity if side_effect is not None else None
            ),
        )

    @property
    def requires_semantic_grading(self) -> bool:
        return self.semantic_rubric_identity is not None

    @property
    def requires_side_effect_grading(self) -> bool:
        return self.side_effect_idempotency_identity is not None


class TrialAssuranceRecord(BaseModel):
    """Bound trial facts sufficient to rederive report-level assurance conclusions.

    Deterministic oracle snapshots and semantic judgment are deliberately separate authority
    classes. A semantic result may only exist after all deterministic oracles pass, may never be
    critical, and can only narrow a deterministic PASS into FAIL or INCONCLUSIVE. It cannot rescue
    a deterministic failure.

    The evidence root identifies the exact final trial evidence. A semantic receipt separately
    binds the exact pre-semantic evidence root; reconstructing and verifying that relation requires
    the evidence/replay path because the report does not duplicate the full event stream.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str = Field(min_length=1)
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: TrialVerdict
    oracle_results: tuple[OracleSnapshot, ...] = ()
    semantic_judgment: SemanticJudgmentReceipt | None = None

    @property
    def critical_violations(self) -> int:
        """Critical authority remains deterministic; semantic FAIL is never counted here."""
        return sum(
            result.critical and result.verdict is TrialVerdict.FAIL
            for result in self.oracle_results
        )

    @model_validator(mode="after")
    def validate_trial_derivation(self) -> Self:
        _validate_oracle_snapshot_shape(self.oracle_results, verdict=self.verdict)

        if self.verdict is TrialVerdict.BLOCKED:
            if self.semantic_judgment is not None:
                raise ValueError(
                    "blocked assurance trial cannot contain semantic judgment evidence"
                )
            return self

        deterministic_failed = any(
            result.verdict is TrialVerdict.FAIL for result in self.oracle_results
        )
        semantic = self.semantic_judgment
        if semantic is not None and deterministic_failed:
            raise ValueError("semantic judgment cannot coexist with deterministic oracle failure")

        if semantic is None:
            if self.verdict is TrialVerdict.INCONCLUSIVE:
                raise ValueError(
                    "inconclusive assurance trial requires an abstaining semantic judgment"
                )
            expected = TrialVerdict.FAIL if deterministic_failed else TrialVerdict.PASS
        else:
            if semantic.decision is SemanticDecision.ABSTAIN:
                expected = TrialVerdict.INCONCLUSIVE
            elif semantic.decision is SemanticDecision.FAIL:
                expected = TrialVerdict.FAIL
            else:
                expected = TrialVerdict.PASS

        if self.verdict is not expected:
            raise ValueError(
                "assurance trial verdict does not recompute from oracle results and semantic grading"
            )
        return self


class ReliabilitySnapshot(BaseModel):
    """Serialized reliability output that must recompute from trial verdicts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trials: int = Field(ge=1, strict=True)
    resolved_trials: int = Field(ge=0, strict=True)
    passes: int = Field(ge=0, strict=True)
    failures: int = Field(ge=0, strict=True)
    blocked: int = Field(ge=0, strict=True)
    inconclusive: int = Field(ge=0, strict=True)
    success_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    wilson_low: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    wilson_high: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    pass_at_k: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    pass_power_k: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    k: int = Field(ge=1, strict=True)
    confidence_z: float = Field(gt=0.0, allow_inf_nan=False, strict=True)

    @classmethod
    def from_reliability(cls, report: ReliabilityReport) -> Self:
        return cls(
            trials=report.trials,
            resolved_trials=report.resolved_trials,
            passes=report.passes,
            failures=report.failures,
            blocked=report.blocked,
            inconclusive=report.inconclusive,
            success_rate=report.success_rate,
            wilson_low=report.wilson_low,
            wilson_high=report.wilson_high,
            pass_at_k=report.pass_at_k,
            pass_power_k=report.pass_power_k,
            k=report.k,
            confidence_z=report.confidence_z,
        )


class GateSnapshot(BaseModel):
    """Serialized release-gate output that must recompute from bound report inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: GateDecision
    reasons: tuple[str, ...] = ()

    @classmethod
    def from_gate(cls, result: GateResult) -> Self:
        return cls(decision=result.decision, reasons=result.reasons)


class AssuranceReport(BaseModel):
    """Reproducible session report whose derived claims are verified on every load.

    Evidence roots, deterministic oracle snapshots, optional semantic judgment receipts, the
    scenario-derived grading profile, and terminal trial verdicts are the bound trial facts. Trial
    verdicts are rederived with strict deterministic-over-semantic precedence. Reliability and
    release-gate fields are then recomputed from those validated trial facts and the frozen release
    policy.

    The report root detects unacknowledged content changes. It is not a signature, MAC, trusted
    timestamp, publisher identity, or proof that the referenced evidence was honestly produced.
    Re-running deterministic oracles and reconstructing event-level scenario relations requires
    the exact scenario/evidence replay path.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/assurance-report/v4"] = _REPORT_SCHEMA
    evidence_schema: Literal["agent-evals/trial-evidence/v2"] = _EVIDENCE_SCHEMA
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    grading_profile: ScenarioGradingProfile
    trials: tuple[TrialAssuranceRecord, ...] = Field(min_length=1)
    release_policy: ReleasePolicy
    reliability: ReliabilitySnapshot
    gate: GateSnapshot
    report_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def critical_violations(self) -> int:
        return sum(record.critical_violations for record in self.trials)

    @classmethod
    def from_session(
        cls,
        session: EvaluationSessionResult,
        *,
        scenario: EvaluationScenario,
        release_policy: ReleasePolicy,
    ) -> Self:
        if not session.trials:
            raise ValueError("assurance report requires at least one evaluated trial")

        scenario = scenario.snapshot()
        if not hmac.compare_digest(scenario.identity, session.scenario_identity):
            raise ValueError("assurance report scenario contract does not match session identity")
        grading_profile = ScenarioGradingProfile.from_scenario(scenario)

        trial_ids: set[str] = set()
        records: list[TrialAssuranceRecord] = []
        verdicts: list[TrialVerdict] = []
        for trial in session.trials:
            evidence = trial.evidence
            if not hmac.compare_digest(
                evidence.evidence_root,
                trial.completion_evidence_root,
            ):
                raise ValueError("trial evidence root changed after evaluation finalization")
            if evidence.subject_identity != session.subject_identity:
                raise ValueError("trial evidence subject identity does not match session")
            if evidence.scenario_identity != session.scenario_identity:
                raise ValueError("trial evidence scenario identity does not match session")
            if evidence.trial_id in trial_ids:
                raise ValueError("session contains duplicate trial IDs")
            trial_ids.add(evidence.trial_id)
            semantic = (
                SemanticJudgmentReceipt.model_validate(
                    trial.semantic_judgment.model_dump(mode="json")
                )
                if trial.semantic_judgment is not None
                else None
            )
            verified_oracle_results = tuple(trial.oracle_results)
            blocking_evidence = has_blocking_evidence(evidence)
            if trial.verdict is TrialVerdict.BLOCKED:
                if not blocking_evidence:
                    raise ValueError(
                        "blocked assurance trial contains no evaluator/runtime blocking evidence"
                    )
            else:
                supplied_snapshots = tuple(
                    OracleSnapshot.from_oracle(result) for result in verified_oracle_results
                )
                _validate_oracle_snapshot_shape(supplied_snapshots, verdict=trial.verdict)
                deterministic_failed = any(
                    result.verdict is TrialVerdict.FAIL for result in supplied_snapshots
                )
                if semantic is not None and deterministic_failed:
                    raise ValueError(
                        "semantic judgment cannot coexist with deterministic oracle failure"
                    )

                if blocking_evidence:
                    raise ValueError(
                        "non-blocked assurance trial contains evaluator/runtime blocking evidence"
                    )
                try:
                    verify_pregrading_closure(scenario, evidence)
                except EvaluationPreconditionError as exc:
                    if exc.code == "side_effect_observation_unverified":
                        raise ValueError(
                            f"trial side-effect observation evidence is invalid: {exc.reason}"
                        ) from exc
                    raise ValueError(
                        f"trial pre-grading evidence is invalid ({exc.code}): {exc.reason}"
                    ) from exc

                has_side_effect_oracle = any(
                    result.name == _SIDE_EFFECT_ORACLE_NAME for result in supplied_snapshots
                )
                if has_side_effect_oracle is not grading_profile.requires_side_effect_grading:
                    raise ValueError(
                        "trial side-effect oracle presence does not match scenario grading profile"
                    )

                expected_oracle_results = grade_deterministic_evidence(scenario, evidence)
                if verified_oracle_results != expected_oracle_results:
                    raise ValueError(
                        "trial deterministic oracle results do not match scenario/evidence grading"
                    )
                verified_oracle_results = expected_oracle_results

                try:
                    evidence_semantic = verify_semantic_judgment(scenario, evidence)
                except SemanticJudgmentError as exc:
                    raise ValueError(f"trial semantic judgment evidence is invalid: {exc}") from exc

                if semantic is None and evidence_semantic is not None:
                    raise ValueError(
                        "trial semantic judgment field is absent but final evidence commits a judgment"
                    )
                if semantic is not None and evidence_semantic is None:
                    raise ValueError(
                        "trial semantic judgment is not committed by the final evidence envelope"
                    )
                if semantic is not None and evidence_semantic != semantic:
                    raise ValueError(
                        "trial semantic judgment does not match the receipt committed by final evidence"
                    )
            record = TrialAssuranceRecord(
                trial_id=evidence.trial_id,
                evidence_root=evidence.evidence_root,
                verdict=trial.verdict,
                oracle_results=tuple(
                    OracleSnapshot.from_oracle(result) for result in verified_oracle_results
                ),
                semantic_judgment=semantic,
            )
            records.append(record)
            verdicts.append(record.verdict)

        recomputed_reliability = ReliabilityReport.from_verdicts(
            verdicts,
            k=session.reliability.k,
            confidence_z=session.reliability.confidence_z,
        )
        if recomputed_reliability != session.reliability:
            raise ValueError("session reliability does not recompute from its trial verdicts")

        reliability = ReliabilitySnapshot.from_reliability(recomputed_reliability)
        critical_violations = sum(record.critical_violations for record in records)
        gate = GateSnapshot.from_gate(
            ReleaseGate(release_policy).decide(
                recomputed_reliability,
                critical_violations=critical_violations,
            )
        )
        unsigned = {
            "schema_version": _REPORT_SCHEMA,
            "evidence_schema": _EVIDENCE_SCHEMA,
            "subject_identity": session.subject_identity,
            "scenario_identity": session.scenario_identity,
            "grading_profile": grading_profile.model_dump(mode="json"),
            "trials": [record.model_dump(mode="json") for record in records],
            "release_policy": release_policy.model_dump(mode="json"),
            "reliability": reliability.model_dump(mode="json"),
            "gate": gate.model_dump(mode="json"),
        }
        return cls(
            schema_version=_REPORT_SCHEMA,
            evidence_schema=_EVIDENCE_SCHEMA,
            subject_identity=session.subject_identity,
            scenario_identity=session.scenario_identity,
            grading_profile=grading_profile,
            trials=tuple(records),
            release_policy=release_policy,
            reliability=reliability,
            gate=gate,
            report_root=_report_root(unsigned),
        )

    @model_validator(mode="after")
    def validate_derived_claims(self) -> Self:
        trial_ids = [record.trial_id for record in self.trials]
        if len(set(trial_ids)) != len(trial_ids):
            raise ValueError("assurance report trial IDs must be unique")

        for record in self.trials:
            self._validate_record_grading_shape(record)
            semantic = record.semantic_judgment
            if semantic is None:
                continue
            if semantic.subject_identity != self.subject_identity:
                raise ValueError("semantic judgment subject identity does not match report")
            if semantic.scenario_identity != self.scenario_identity:
                raise ValueError("semantic judgment scenario identity does not match report")

        recomputed_reliability = ReliabilityReport.from_verdicts(
            tuple(record.verdict for record in self.trials),
            k=self.reliability.k,
            confidence_z=self.reliability.confidence_z,
        )
        if ReliabilitySnapshot.from_reliability(recomputed_reliability) != self.reliability:
            raise ValueError("assurance report reliability does not recompute from trial verdicts")

        recomputed_gate = ReleaseGate(self.release_policy).decide(
            recomputed_reliability,
            critical_violations=self.critical_violations,
        )
        if GateSnapshot.from_gate(recomputed_gate) != self.gate:
            raise ValueError("assurance report gate does not recompute from bound inputs")

        expected_root = _report_root(self.model_dump(mode="json", exclude={"report_root"}))
        if not hmac.compare_digest(expected_root, self.report_root):
            raise ValueError("assurance report root does not match report content")
        return self

    def _validate_record_grading_shape(self, record: TrialAssuranceRecord) -> None:
        if record.verdict is TrialVerdict.BLOCKED:
            return

        has_side_effect_oracle = any(
            result.name == _SIDE_EFFECT_ORACLE_NAME for result in record.oracle_results
        )
        if has_side_effect_oracle is not self.grading_profile.requires_side_effect_grading:
            raise ValueError(
                "assurance trial side-effect oracle presence does not match grading profile"
            )

        deterministic_failed = any(
            result.verdict is TrialVerdict.FAIL for result in record.oracle_results
        )
        semantic = record.semantic_judgment
        semantic_required = (
            self.grading_profile.requires_semantic_grading and not deterministic_failed
        )
        if semantic_required and semantic is None:
            raise ValueError(
                "assurance trial is missing semantic judgment required by grading profile"
            )
        if semantic is None:
            return

        rubric_identity = self.grading_profile.semantic_rubric_identity
        if rubric_identity is None:
            raise ValueError(
                "assurance trial contains semantic judgment without a configured rubric"
            )
        if semantic.rubric_identity != rubric_identity:
            raise ValueError(
                "semantic judgment rubric identity does not match assurance grading profile"
            )


def _validate_oracle_snapshot_shape(
    oracle_results: tuple[OracleSnapshot, ...],
    *,
    verdict: TrialVerdict,
) -> None:
    oracle_names = [result.name for result in oracle_results]
    if len(set(oracle_names)) != len(oracle_names):
        raise ValueError("assurance trial oracle names must be unique")

    if verdict is TrialVerdict.BLOCKED:
        if oracle_results:
            raise ValueError("blocked assurance trial cannot contain completed oracle results")
        return

    if not oracle_results:
        raise ValueError("non-blocked assurance trial requires deterministic oracle results")
    missing_core = _CORE_ORACLE_NAMES.difference(oracle_names)
    if missing_core:
        missing = ", ".join(sorted(missing_core))
        raise ValueError(f"non-blocked assurance trial is missing core oracle results: {missing}")
    if any(result.verdict not in _RESOLVED_VERDICTS for result in oracle_results):
        raise ValueError("non-blocked assurance trial has a non-resolved oracle verdict")


def _report_root(value: object) -> str:
    return hashlib.sha256(_REPORT_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
