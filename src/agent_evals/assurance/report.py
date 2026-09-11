"""Portable assurance report schema for CI and offline review."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.assurance.session_provenance import SessionProvenanceSnapshot
from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialVerdict
from agent_evals.gates.release import GateDecision, GateResult, ReleaseGate, ReleasePolicy
from agent_evals.oracles.deterministic import grade_deterministic_evidence
from agent_evals.runtime.preconditions import (
    EvaluationPreconditionError,
    has_blocking_evidence,
    verify_pregrading_closure,
)
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.semantic.models import SemanticJudgmentReceipt
from agent_evals.semantic.verification import SemanticJudgmentError, verify_semantic_judgment
from agent_evals.statistics.reliability import ReliabilityReport

_REPORT_SCHEMA = "agent-evals/assurance-report/v6"
_REPORT_DOMAIN = b"agent-evals/assurance-report/v6\0"
_EVIDENCE_SCHEMA = "agent-evals/trial-evidence/v2"
_CORE_ORACLE_NAMES = frozenset({"policy", "outcome"})
_SIDE_EFFECT_ORACLE_NAME = "side-effect-idempotency"
_SEMANTIC_ORACLE_NAME = "semantic"


class OracleSnapshot(BaseModel):
    """Portable deterministic-oracle result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    verdict: TrialVerdict
    reasons: tuple[str, ...] = ()
    critical: bool = False

    @classmethod
    def from_oracle(cls, result: Any) -> OracleSnapshot:
        return cls(
            name=result.name,
            verdict=result.verdict,
            reasons=tuple(result.reasons),
            critical=result.critical,
        )


class BlockedPolicyViolationSnapshot(BaseModel):
    """Durable policy fact retained when a trial is BLOCKED before grading.

    This snapshot never regrades the blocked trial. It preserves an explicit policy-violation event
    so the release gate cannot treat known non-compensatory policy failure as mere evaluator
    uncertainty. ``event_identity`` binds the exact source event into the report root.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any]
    source_critical: bool

    @classmethod
    def from_event(cls, event: EvidenceEvent) -> BlockedPolicyViolationSnapshot:
        if event.kind is not EvidenceKind.POLICY_VIOLATION:
            raise ValueError("blocked policy snapshot requires a policy-violation event")
        return cls(
            event_identity=event.identity,
            source=event.source,
            payload=dict(event.payload),
            source_critical=event.critical,
        )


class TrialAssuranceRecord(BaseModel):
    """Evidence-bound outcome for one evaluated trial."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str = Field(min_length=1, max_length=256)
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: TrialVerdict
    oracle_results: tuple[OracleSnapshot, ...] = ()
    semantic_judgment: SemanticJudgmentReceipt | None = None
    blocked_policy_violations: tuple[BlockedPolicyViolationSnapshot, ...] = ()

    @property
    def critical_violations(self) -> int:
        deterministic_critical = sum(
            1
            for result in self.oracle_results
            if result.verdict is TrialVerdict.FAIL and result.critical
        )
        blocked_policy_critical = int(bool(self.blocked_policy_violations))
        return deterministic_critical + blocked_policy_critical


class ScenarioGradingProfile(BaseModel):
    """Report-bound grading shape needed to validate serialized trial records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requires_side_effect_grading: bool
    requires_semantic_grading: bool
    semantic_rubric_identity: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @classmethod
    def from_scenario(cls, scenario: EvaluationScenario) -> ScenarioGradingProfile:
        semantic = scenario.semantic_rubric
        return cls(
            requires_side_effect_grading=scenario.side_effect_contract is not None,
            requires_semantic_grading=semantic is not None,
            semantic_rubric_identity=semantic.identity if semantic is not None else None,
        )

    @model_validator(mode="after")
    def validate_semantic_shape(self) -> Self:
        if self.requires_semantic_grading:
            if self.semantic_rubric_identity is None:
                raise ValueError("semantic grading profile requires a rubric identity")
        elif self.semantic_rubric_identity is not None:
            raise ValueError("non-semantic grading profile cannot carry a rubric identity")
        return self


class ReliabilitySnapshot(BaseModel):
    """JSON-safe reliability arithmetic copied from a validated runtime report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    blocked: int = Field(ge=0)
    inconclusive: int = Field(ge=0)
    resolved: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    wilson_low: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    wilson_high: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    k: int = Field(ge=1)
    confidence_z: float = Field(gt=0.0, allow_inf_nan=False)
    pass_at_k: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    pass_power_k: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @classmethod
    def from_reliability(cls, report: ReliabilityReport) -> ReliabilitySnapshot:
        report.validate()
        return cls(
            total=report.total,
            passed=report.passed,
            failed=report.failed,
            blocked=report.blocked,
            inconclusive=report.inconclusive,
            resolved=report.resolved,
            success_rate=report.success_rate,
            wilson_low=report.wilson_low,
            wilson_high=report.wilson_high,
            k=report.k,
            confidence_z=report.confidence_z,
            pass_at_k=report.pass_at_k,
            pass_power_k=report.pass_power_k,
        )

    @field_validator(
        "success_rate",
        "wilson_low",
        "wilson_high",
        "confidence_z",
        "pass_at_k",
        "pass_power_k",
        mode="before",
    )
    @classmethod
    def require_json_number(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("reliability floating-point fields require JSON numbers")
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.passed + self.failed + self.blocked + self.inconclusive != self.total:
            raise ValueError("reliability counts must sum to total")
        if self.passed + self.failed != self.resolved:
            raise ValueError("resolved must equal passed plus failed")
        return self


class GateSnapshot(BaseModel):
    """Portable release decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: GateDecision
    reasons: tuple[str, ...] = ()

    @classmethod
    def from_gate(cls, result: GateResult) -> GateSnapshot:
        return cls(decision=result.decision, reasons=result.reasons)


class AssuranceReport(BaseModel):
    """Replayable evidence-bound release report.

    ``report_root`` is a SHA-256 integrity commitment over the canonical JSON of every report field
    except ``report_root`` itself. It is not a signature, MAC, authenticated identity, trusted
    timestamp, attestation, or proof of statistical independence. V6 additionally binds and
    revalidates repeated-trial campaign, reset/isolation, sampling, randomness, and stopping
    provenance without upgrading those relations beyond their explicit evaluator-owned semantics.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/assurance-report/v6"] = _REPORT_SCHEMA
    evidence_schema: Literal["agent-evals/trial-evidence/v2"] = _EVIDENCE_SCHEMA
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_provenance: SessionProvenanceSnapshot
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
            blocked_policy_violations: tuple[BlockedPolicyViolationSnapshot, ...] = ()
            blocking_evidence = has_blocking_evidence(evidence)

            if trial.verdict is TrialVerdict.BLOCKED:
                if not blocking_evidence:
                    raise ValueError(
                        "blocked assurance trial contains no evaluator/runtime blocking evidence"
                    )
                blocked_policy_violations = tuple(
                    BlockedPolicyViolationSnapshot.from_event(event)
                    for event in evidence.events
                    if event.kind is EvidenceKind.POLICY_VIOLATION
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
                blocked_policy_violations=blocked_policy_violations,
            )
            records.append(record)
            verdicts.append(record.verdict)

        session_provenance = SessionProvenanceSnapshot.from_session(session)
        ordered_trial_ids = tuple(record.trial_id for record in records)
        ordered_evidence_roots = tuple(record.evidence_root for record in records)
        session_provenance.validate_against_report(
            subject_identity=session.subject_identity,
            scenario_identity=session.scenario_identity,
            trial_ids=ordered_trial_ids,
            evidence_roots=ordered_evidence_roots,
        )

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
            "session_provenance": session_provenance.model_dump(mode="json"),
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
            session_provenance=session_provenance,
            grading_profile=grading_profile,
            trials=tuple(records),
            release_policy=release_policy,
            reliability=reliability,
            gate=gate,
            report_root=_report_root(unsigned),
        )

    @model_validator(mode="after")
    def validate_derived_claims(self) -> Self:
        trial_ids = tuple(record.trial_id for record in self.trials)
        if len(set(trial_ids)) != len(trial_ids):
            raise ValueError("assurance report trial IDs must be unique")
        evidence_roots = tuple(record.evidence_root for record in self.trials)

        self.session_provenance.validate_against_report(
            subject_identity=self.subject_identity,
            scenario_identity=self.scenario_identity,
            trial_ids=trial_ids,
            evidence_roots=evidence_roots,
        )

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

        semantic_results = tuple(
            result for result in record.oracle_results if result.name == _SEMANTIC_ORACLE_NAME
        )
        if self.grading_profile.requires_semantic_grading:
            deterministic_failed = any(
                result.verdict is TrialVerdict.FAIL
                for result in record.oracle_results
                if result.name != _SEMANTIC_ORACLE_NAME
            )
            if deterministic_failed:
                if record.semantic_judgment is not None or semantic_results:
                    raise ValueError(
                        "semantic judgment cannot coexist with deterministic oracle failure"
                    )
            else:
                if record.semantic_judgment is None:
                    raise ValueError("missing semantic judgment required by grading profile")
                if len(semantic_results) != 1:
                    raise ValueError("semantic grading profile requires exactly one semantic oracle")
                expected_semantic = OracleSnapshot(
                    name=_SEMANTIC_ORACLE_NAME,
                    verdict=_semantic_verdict(record.semantic_judgment.decision),
                    reasons=(record.semantic_judgment.reason,),
                    critical=False,
                )
                if semantic_results[0] != expected_semantic:
                    raise ValueError(
                        "semantic oracle does not match the bound semantic judgment receipt"
                    )
        elif record.semantic_judgment is not None or semantic_results:
            raise ValueError("non-semantic grading profile cannot carry semantic judgment material")

        deterministic = tuple(
            result for result in record.oracle_results if result.name != _SEMANTIC_ORACLE_NAME
        )
        _validate_oracle_snapshot_shape(deterministic, verdict=record.verdict)


def _validate_oracle_snapshot_shape(
    oracle_results: tuple[OracleSnapshot, ...],
    *,
    verdict: TrialVerdict,
) -> None:
    if verdict in {TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE}:
        return
    names = tuple(result.name for result in oracle_results)
    if len(set(names)) != len(names):
        raise ValueError("resolved assurance trial contains duplicate oracle names")
    missing = _CORE_ORACLE_NAMES.difference(names)
    if missing:
        raise ValueError(f"resolved assurance trial missing core oracle results: {', '.join(sorted(missing))}")
    policy = next(result for result in oracle_results if result.name == "policy")
    if policy.verdict is TrialVerdict.FAIL and not policy.critical:
        raise ValueError("policy oracle failure criticality does not match deterministic runtime")


def _semantic_verdict(decision: Any) -> TrialVerdict:
    value = getattr(decision, "value", decision)
    if value == "pass":
        return TrialVerdict.PASS
    if value == "fail":
        return TrialVerdict.FAIL
    if value == "abstain":
        return TrialVerdict.INCONCLUSIVE
    raise ValueError("unsupported semantic decision")


def _report_root(unsigned: dict[str, Any]) -> str:
    payload = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_REPORT_DOMAIN + payload).hexdigest()
