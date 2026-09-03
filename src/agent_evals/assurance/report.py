"""Self-validating session assurance reports bound to trial evidence and grading facts."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.models import TrialVerdict
from agent_evals.gates.release import GateDecision, GateResult, ReleaseGate, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

_REPORT_SCHEMA: Literal["agent-evals/assurance-report/v1"] = "agent-evals/assurance-report/v1"
_REPORT_DOMAIN = b"agent-evals/assurance-report/v1\0"
_RESOLVED_VERDICTS = frozenset({TrialVerdict.PASS, TrialVerdict.FAIL})


class OracleSnapshot(BaseModel):
    """Serialized deterministic oracle result used to rederive a resolved trial verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    verdict: TrialVerdict
    reasons: tuple[str, ...] = ()
    critical: bool = False

    @classmethod
    def from_oracle(cls, result: OracleResult) -> Self:
        return cls(
            name=result.name,
            verdict=result.verdict,
            reasons=result.reasons,
            critical=result.critical,
        )


class TrialAssuranceRecord(BaseModel):
    """Bound trial facts sufficient to rederive report-level assurance conclusions.

    The evidence root identifies the exact trial evidence. Oracle snapshots preserve the grading
    outputs used by the runtime. This model verifies their internal verdict relationship, but it
    does not rerun an oracle from the evidence root alone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str = Field(min_length=1)
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: TrialVerdict
    oracle_results: tuple[OracleSnapshot, ...] = ()

    @property
    def critical_violations(self) -> int:
        return sum(
            result.critical and result.verdict is TrialVerdict.FAIL
            for result in self.oracle_results
        )

    @model_validator(mode="after")
    def validate_trial_derivation(self) -> Self:
        if self.verdict in _RESOLVED_VERDICTS:
            if not self.oracle_results:
                raise ValueError("resolved assurance trial requires deterministic oracle results")
            if any(result.verdict not in _RESOLVED_VERDICTS for result in self.oracle_results):
                raise ValueError("resolved assurance trial has a non-resolved oracle verdict")
            expected = (
                TrialVerdict.FAIL
                if any(result.verdict is TrialVerdict.FAIL for result in self.oracle_results)
                else TrialVerdict.PASS
            )
            if self.verdict is not expected:
                raise ValueError("assurance trial verdict does not recompute from oracle results")
        elif self.verdict is TrialVerdict.BLOCKED and self.oracle_results:
            raise ValueError("blocked assurance trial cannot contain completed oracle results")
        return self


class ReliabilitySnapshot(BaseModel):
    """Serialized reliability output that must recompute from trial verdicts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trials: int = Field(ge=1)
    resolved_trials: int = Field(ge=0)
    passes: int = Field(ge=0)
    failures: int = Field(ge=0)
    blocked: int = Field(ge=0)
    inconclusive: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    wilson_low: float = Field(ge=0.0, le=1.0)
    wilson_high: float = Field(ge=0.0, le=1.0)
    pass_at_k: float = Field(ge=0.0, le=1.0)
    pass_power_k: float = Field(ge=0.0, le=1.0)
    k: int = Field(ge=1)

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

    Evidence roots, runtime oracle snapshots, and terminal trial verdicts are the bound trial
    facts. Resolved trial verdicts are rederived from their oracle snapshots. Reliability and
    release-gate fields are then recomputed from those validated trial facts and the frozen policy.

    The report root detects unacknowledged content changes. It is not a signature, MAC, trusted
    timestamp, publisher identity, or proof that the referenced evidence was honestly produced.
    Re-running deterministic oracles against the exact evidence requires the evidence/replay path.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/assurance-report/v1"] = _REPORT_SCHEMA
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
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
        release_policy: ReleasePolicy,
    ) -> Self:
        if not session.trials:
            raise ValueError("assurance report requires at least one evaluated trial")

        trial_ids: set[str] = set()
        records: list[TrialAssuranceRecord] = []
        verdicts: list[TrialVerdict] = []
        for trial in session.trials:
            evidence = trial.evidence
            if evidence.subject_identity != session.subject_identity:
                raise ValueError("trial evidence subject identity does not match session")
            if evidence.scenario_identity != session.scenario_identity:
                raise ValueError("trial evidence scenario identity does not match session")
            if evidence.trial_id in trial_ids:
                raise ValueError("session contains duplicate trial IDs")
            trial_ids.add(evidence.trial_id)
            record = TrialAssuranceRecord(
                trial_id=evidence.trial_id,
                evidence_root=evidence.evidence_root,
                verdict=trial.verdict,
                oracle_results=tuple(
                    OracleSnapshot.from_oracle(result) for result in trial.oracle_results
                ),
            )
            records.append(record)
            verdicts.append(record.verdict)

        recomputed_reliability = ReliabilityReport.from_verdicts(
            verdicts,
            k=session.reliability.k,
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
            "subject_identity": session.subject_identity,
            "scenario_identity": session.scenario_identity,
            "trials": [record.model_dump(mode="json") for record in records],
            "release_policy": release_policy.model_dump(mode="json"),
            "reliability": reliability.model_dump(mode="json"),
            "gate": gate.model_dump(mode="json"),
        }
        return cls(
            schema_version=_REPORT_SCHEMA,
            subject_identity=session.subject_identity,
            scenario_identity=session.scenario_identity,
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

        recomputed_reliability = ReliabilityReport.from_verdicts(
            tuple(record.verdict for record in self.trials),
            k=self.reliability.k,
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


def _report_root(value: object) -> str:
    return hashlib.sha256(_REPORT_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
