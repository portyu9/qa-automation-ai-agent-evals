"""Operator-facing deterministic assurance operations.

This module exposes only evaluator-owned validation, normalized scripted harness execution,
and evidence replay/regrading. It does not turn arbitrary operator/provider assertions into
trusted evidence and does not make telemetry or presentation output grading authority.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - operator explicitly runs fixed repository policy scripts
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_evals._strict_json import strict_json_loads
from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.assurance.report import AssuranceReport
from agent_evals.assurance.report_v7 import AssuranceReportV7
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, TrialEvidence, TrialVerdict
from agent_evals.evidence.store import LocalEvidenceStore
from agent_evals.minimization.delta import ddmin
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.runtime.session import EvaluationSession
from agent_evals.semantic.calibration import (
    SemanticCalibrationObservation,
    SemanticCalibrationPolicy,
    SemanticCalibrationReceipt,
)
from agent_evals.semantic.models import SemanticJudgeProfile
from agent_evals.statistics.comparison import PairedComparison

_OPERATOR_SCRIPTED_ADAPTER = "operator-scripted"
_OPERATOR_SCRIPTED_VERSION = "1"


class NormalizedObservation(BaseModel):
    """Pre-normalized observation for the deterministic scripted operator harness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[EvidenceEvent, ...] = ()
    final_state: dict[str, Any] = Field(default_factory=dict)
    final_output: str | None = None
    elapsed_ms: float = Field(default=0.0, ge=0.0, allow_inf_nan=False, strict=True)
    input_tokens: int = Field(default=0, ge=0, strict=True)
    output_tokens: int = Field(default=0, ge=0, strict=True)
    estimated_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        allow_inf_nan=False,
        strict=True,
    )

    def adapter_result(self) -> AdapterResult:
        return AdapterResult(
            events=self.events,
            final_state=self.final_state,
            final_output=self.final_output,
            elapsed_ms=self.elapsed_ms,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            estimated_cost_usd=self.estimated_cost_usd,
        )


class OperatorRunRequest(BaseModel):
    """Versioned deterministic harness request restricted to one non-provider adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/operator-run-request/v1"] = (
        "agent-evals/operator-run-request/v1"
    )
    subject: SubjectFingerprint
    scenario: EvaluationScenario
    observations: tuple[NormalizedObservation, ...] = Field(min_length=1, max_length=10_000)
    campaign_id: str | None = None
    k: int = Field(default=1, ge=1, strict=True)

    def validate_operator_adapter(self) -> None:
        if (
            self.subject.adapter != _OPERATOR_SCRIPTED_ADAPTER
            or self.subject.adapter_version != _OPERATOR_SCRIPTED_VERSION
        ):
            raise ValueError(
                "operator run requests require subject adapter='operator-scripted' "
                "and adapter_version='1'; live/provider adapter identities cannot be impersonated"
            )


class CalibrationRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/calibration-run-request/v1"] = (
        "agent-evals/calibration-run-request/v1"
    )
    judge_profile: SemanticJudgeProfile
    policy: SemanticCalibrationPolicy
    observations: tuple[SemanticCalibrationObservation, ...] = Field(min_length=1)


def load_json(path: Path, *, label: str, require_object: bool = True) -> Any:
    return strict_json_loads(path.read_bytes(), label=label, require_object=require_object)


def validate_scenario(path: Path) -> dict[str, Any]:
    scenario = EvaluationScenario.model_validate(load_json(path, label="scenario"))
    return {
        "status": "valid",
        "schema": "agent-evals/evaluation-scenario",
        "scenario_id": scenario.scenario_id,
        "revision": scenario.revision,
        "kind": scenario.kind.value,
        "scenario_identity": scenario.identity,
        "_proof": [
            "strict JSON decoding accepted the input",
            "EvaluationScenario schema and cross-field validators accepted the contract",
            "scenario_identity was derived from the validated immutable contract",
        ],
    }


async def run_request(path: Path, *, single: bool) -> dict[str, Any]:
    request = OperatorRunRequest.model_validate(load_json(path, label="operator run request"))
    request.validate_operator_adapter()
    if single and len(request.observations) != 1:
        raise ValueError(
            "run requires exactly one normalized observation; use 'session run' for many"
        )

    cursor = 0

    def script(
        _subject: SubjectFingerprint,
        _scenario: EvaluationScenario,
        _trial_id: str,
    ) -> AdapterResult:
        nonlocal cursor
        if cursor >= len(request.observations):
            raise RuntimeError("operator scripted observation sequence was exhausted")
        observation = request.observations[cursor]
        cursor += 1
        return observation.adapter_result()

    evaluated = await EvaluationSession().run(
        ScriptedAdapter(script, name=_OPERATOR_SCRIPTED_ADAPTER),
        subject=request.subject,
        scenario=request.scenario,
        trials=len(request.observations),
        k=request.k,
        campaign_id=request.campaign_id,
    )
    return {
        "status": "evaluated",
        "execution_boundary": "normalized-operator-scripted",
        "campaign_id": evaluated.campaign_id,
        "subject_identity": evaluated.subject_identity,
        "scenario_identity": evaluated.scenario_identity,
        "reliability": asdict(evaluated.reliability),
        "trials": [_trial_payload(trial, include_evidence=True) for trial in evaluated.trials],
        "_proof": [
            "the request was restricted to the non-provider operator-scripted adapter identity",
            "EvaluationSession minted/validated trial identities and finalized evidence",
            "deterministic grading and reliability were derived by evaluator-owned runtime code",
        ],
    }


async def replay_or_regrade(
    *,
    evidence_path: Path,
    scenario_path: Path,
    subject_path: Path,
    include_evidence: bool,
) -> dict[str, Any]:
    evidence = TrialEvidence.model_validate(load_json(evidence_path, label="trial evidence"))
    scenario = EvaluationScenario.model_validate(load_json(scenario_path, label="scenario"))
    subject = SubjectFingerprint.model_validate(
        load_json(subject_path, label="subject fingerprint")
    )
    if evidence.subject_identity != subject.identity:
        raise ValueError("evidence subject identity does not match supplied subject fingerprint")
    if evidence.scenario_identity != scenario.identity:
        raise ValueError("evidence scenario identity does not match supplied scenario contract")

    evaluated = await TrialRunner().run(
        EvidenceReplayAdapter(evidence),
        subject=subject,
        scenario=scenario,
        trial_id=evidence.trial_id,
    )
    payload = _trial_payload(evaluated, include_evidence=include_evidence)
    payload.update(
        {
            "status": "replayed" if include_evidence else "regraded",
            "execution_boundary": "evidence-replay-no-live-execution",
            "_proof": [
                "trial/subject/scenario identities were matched before replay",
                "EvidenceReplayAdapter supplied only the recorded normalized evidence",
                "TrialRunner re-executed deterministic preconditions/oracles without live execution",
            ],
        }
    )
    return payload


def verify_evidence(path: Path) -> dict[str, Any]:
    evidence = TrialEvidence.model_validate(load_json(path, label="trial evidence"))
    return {
        "status": "valid",
        "trial_id": evidence.trial_id,
        "subject_identity": evidence.subject_identity,
        "scenario_identity": evidence.scenario_identity,
        "evidence_root": evidence.evidence_root,
        "events": len(evidence.events),
        "_proof": [
            "strict JSON decoding accepted the input",
            "TrialEvidence schema, event ordering, timestamps and resource constraints were revalidated",
            "evidence_root was independently rederived from accepted content",
        ],
    }


def inspect_evidence(path: Path, *, include_payloads: bool) -> dict[str, Any]:
    evidence = TrialEvidence.model_validate(load_json(path, label="trial evidence"))
    events: list[dict[str, Any]] = []
    for event in evidence.events:
        item: dict[str, Any] = {
            "sequence": event.sequence,
            "kind": event.kind.value,
            "source": event.source,
            "critical": event.critical,
            "observed_at": event.observed_at.isoformat(),
            "digest": event.digest,
        }
        if include_payloads:
            item["payload"] = event.payload
        events.append(item)
    return {
        "status": "valid",
        "trial_id": evidence.trial_id,
        "evidence_root": evidence.evidence_root,
        "final_state": evidence.final_state,
        "final_output": evidence.final_output,
        "events": events,
        "payloads_included": include_payloads,
        "_proof": [
            "the complete evidence envelope was validated before inspection",
            "event digests are shown from normalized validated events",
            "event payloads remain omitted unless explicitly requested",
        ],
    }


def inspect_store_lock(root: Path, record_key: str) -> dict[str, Any]:
    """Inspect one exact lock without inferring staleness or writer identity."""

    store = LocalEvidenceStore(root)
    observation = inspect_record_lock(store, record_key)
    return {
        "status": "observed",
        "record_key": observation.record_key,
        "device": observation.device,
        "inode": observation.inode,
        "size_bytes": observation.size_bytes,
        "mtime_ns": observation.mtime_ns,
        "observation_root": observation.observation_root,
        "stale": None,
        "_proof": [
            "the lock was opened without following symlinks and revalidated against its path identity",
            "device/inode/size/mtime are filesystem observations, not authenticated writer identity",
            "no staleness decision or cleanup was performed",
        ],
    }


def quarantine_store_lock(
    root: Path,
    record_key: str,
    *,
    confirm_observation_root: str,
) -> dict[str, Any]:
    """Quarantine only the exact lock identity explicitly confirmed by the operator."""

    store = LocalEvidenceStore(root)
    observation = inspect_record_lock(store, record_key)
    receipt = quarantine_record_lock(
        store,
        observation,
        confirm_observation_root=confirm_observation_root,
    )
    return {
        "status": "quarantined",
        "record_key": receipt.record_key,
        "observation_root": receipt.observation_root,
        "quarantine_name": receipt.quarantine_name,
        "receipt_root": receipt.receipt_root,
        "_proof": [
            "the active lock was re-observed immediately before recovery",
            "the caller confirmed the exact observation root rather than an age/PID heuristic",
            "a no-clobber audit copy was materialized before the active lock path was removed",
            "the quarantine receipt is an integrity record, not writer authentication",
        ],
    }


def verify_store(root: Path) -> dict[str, Any]:
    store = LocalEvidenceStore(root)
    records_root = store.root / "records"
    manifests: set[str] = set()
    payloads: set[str] = set()
    locks: set[str] = set()
    problems: list[str] = []

    for bucket in sorted(records_root.iterdir()):
        if bucket.is_symlink() or not bucket.is_dir():
            problems.append(f"invalid record bucket: {bucket.name}")
            continue
        for path in sorted(bucket.iterdir()):
            if path.is_symlink() or not path.is_file():
                problems.append(f"invalid record entry: {path.relative_to(store.root)}")
                continue
            name = path.name
            if name.endswith(".manifest.json"):
                manifests.add(name.removesuffix(".manifest.json"))
            elif name.endswith(".evidence.json"):
                payloads.add(name.removesuffix(".evidence.json"))
            elif name.endswith(".lock"):
                locks.add(name.removesuffix(".lock"))
            else:
                problems.append(f"unexpected record entry: {path.relative_to(store.root)}")

    keys = sorted(manifests | payloads | locks)
    verified = 0
    for key in keys:
        if key in locks:
            problems.append(f"{key}: active/stale lock requires operator review")
            continue
        if key not in manifests or key not in payloads:
            problems.append(f"{key}: partial publication")
            continue
        try:
            store.read(key)
        except Exception as exc:
            problems.append(f"{key}: {type(exc).__name__}: {exc}")
        else:
            verified += 1

    return {
        "status": "valid" if not problems else "invalid",
        "root": str(store.root),
        "records_seen": len(keys),
        "records_verified": verified,
        "problems": problems,
        "_exit_code": 0 if not problems else 4,
        "_proof": [
            "record buckets were enumerated without following symlinks",
            "partial publications and lock files were treated as explicit problems",
            "every complete record was re-read through LocalEvidenceStore integrity verification",
        ],
    }


def verify_report(path: Path) -> dict[str, Any]:
    raw = load_json(path, label="assurance report")
    schema = raw.get("schema_version") if isinstance(raw, dict) else None
    if schema == "agent-evals/assurance-report/v7":
        report = AssuranceReportV7.model_validate(raw)
        predecessor = report.predecessor_report
        report_root = report.report_root
    elif schema == "agent-evals/assurance-report/v6":
        predecessor = AssuranceReport.model_validate(raw)
        report_root = predecessor.report_root
    else:
        raise ValueError(f"unsupported assurance report schema: {schema!r}")
    return {
        "status": "valid",
        "schema_version": schema,
        "report_root": report_root,
        "subject_identity": predecessor.subject_identity,
        "scenario_identity": predecessor.scenario_identity,
        "trial_count": len(predecessor.trials),
        "gate_decision": predecessor.gate.decision.value,
        "_proof": [
            "the versioned assurance report schema was selected explicitly",
            "model validation rederived report roots and all bound derived claims",
            "gate/reliability fields were recomputed from the report's verified trial facts",
        ],
    }


def compare_verdicts(baseline_path: Path, candidate_path: Path, *, alpha: float) -> dict[str, Any]:
    baseline = _load_verdict_vector(baseline_path, label="baseline")
    candidate = _load_verdict_vector(candidate_path, label="candidate")
    comparison = PairedComparison.compare(baseline, candidate, alpha=alpha)
    result = asdict(comparison)
    result["decision"] = comparison.decision.value
    return {
        "status": "compared",
        **result,
        "_proof": [
            "baseline and candidate vectors were parsed as exact TrialVerdict values",
            "BLOCKED/INCONCLUSIVE observations are rejected by paired behavioral comparison",
            "PairedComparison derived exact paired uncertainty and decision",
        ],
    }


async def minimize_evidence(
    *,
    evidence_path: Path,
    scenario_path: Path,
    subject_path: Path,
    max_evaluations: int,
) -> dict[str, Any]:
    evidence = TrialEvidence.model_validate(load_json(evidence_path, label="trial evidence"))
    scenario = EvaluationScenario.model_validate(load_json(scenario_path, label="scenario"))
    subject = SubjectFingerprint.model_validate(
        load_json(subject_path, label="subject fingerprint")
    )
    if (
        evidence.subject_identity != subject.identity
        or evidence.scenario_identity != scenario.identity
    ):
        raise ValueError("evidence identity does not match supplied subject/scenario")

    original = await TrialRunner().run(
        EvidenceReplayAdapter(evidence),
        subject=subject,
        scenario=scenario,
        trial_id=evidence.trial_id,
    )
    if original.verdict is TrialVerdict.PASS:
        raise ValueError("minimize requires a non-PASS source trial")

    async def reproduces(events: tuple[EvidenceEvent, ...]) -> bool:
        candidate = _with_events(evidence, events)
        evaluated = await TrialRunner().run(
            EvidenceReplayAdapter(candidate),
            subject=subject,
            scenario=scenario,
            trial_id=candidate.trial_id,
        )
        return evaluated.verdict is original.verdict

    minimized = await ddmin(
        evidence.events,
        reproduces,
        max_evaluations=max_evaluations,
    )
    minimized_evidence = _with_events(evidence, minimized.minimized)
    return {
        "status": "minimized",
        "target_verdict": original.verdict.value,
        "original_events": minimized.original_size,
        "minimized_events": len(minimized.minimized),
        "evaluations": minimized.evaluations,
        "budget_exhausted": minimized.exhausted,
        "evidence": minimized_evidence.model_dump(mode="json"),
        "evidence_root": minimized_evidence.evidence_root,
        "_proof": [
            "the original evidence was deterministically regraded before minimization",
            "each accepted reduction re-executed the evaluator replay path",
            "the minimized trace preserves the exact original terminal verdict",
        ],
    }


def calibration_run(path: Path) -> dict[str, Any]:
    request = CalibrationRunRequest.model_validate(load_json(path, label="calibration run request"))
    receipt = SemanticCalibrationReceipt.create(
        judge_profile=request.judge_profile,
        policy=request.policy,
        observations=request.observations,
    )
    return {
        "status": "calibrated",
        "accepted": receipt.accepted,
        "receipt_root": receipt.receipt_root,
        "receipt": receipt.model_dump(mode="json"),
        "_proof": [
            "judge profile, policy and observations were schema validated",
            "calibration metrics were derived from evaluator-owned case commitments",
            "the returned receipt root binds the exact observations and policy",
        ],
    }


def calibration_verify(path: Path) -> dict[str, Any]:
    receipt = SemanticCalibrationReceipt.model_validate(
        load_json(path, label="semantic calibration receipt")
    )
    return {
        "status": "valid",
        "accepted": receipt.accepted,
        "receipt_root": receipt.receipt_root,
        "total_cases": receipt.total_cases,
        "false_passes": receipt.false_passes,
        "accuracy": receipt.accuracy,
        "_proof": [
            "receipt schema was revalidated",
            "all calibration metrics were recomputed from bound observations",
            "the receipt root was independently rederived",
        ],
    }


def check_repository_policy(root: Path) -> dict[str, Any]:
    scripts = (
        ".github/scripts/validate_runtime_policy.py",
        ".github/scripts/validate_security_stack.py",
        ".github/scripts/validate_workflow_graph.py",
    )
    results: list[dict[str, Any]] = []
    failed = False
    for relative in scripts:
        script = root / relative
        if not script.is_file():
            results.append({"script": relative, "status": "missing"})
            failed = True
            continue
        completed = subprocess.run(  # nosec B603 - fixed argv, no shell invocation
            [sys.executable, str(script)],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        ok = completed.returncode == 0
        failed = failed or not ok
        results.append(
            {
                "script": relative,
                "status": "pass" if ok else "fail",
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-2000:],
                "stderr_tail": completed.stderr[-2000:],
            }
        )
    return {
        "status": "pass" if not failed else "fail",
        "checks": results,
        "_exit_code": 0 if not failed else 5,
        "_proof": [
            "repository policy scripts were executed from the requested repository root",
            "each policy process had a bounded execution timeout",
            "any missing or failing policy validator fails this command closed",
        ],
    }


def deep_doctor(*, configured_store_root: Path | None) -> dict[str, Any]:
    python_supported = (3, 11) <= sys.version_info[:2] < (3, 15)
    checks: dict[str, Any] = {
        "python": {
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "supported": python_supported,
        },
        "optional_modules": {
            "openai_agents": find_spec("agents") is not None,
            "mcp": find_spec("mcp") is not None,
        },
        "platform": {"os_name": os.name, "platform": sys.platform},
    }
    with tempfile.TemporaryDirectory(prefix="agent-evals-doctor-") as directory:
        probe = Path(directory) / "probe"
        probe.write_text("ok", encoding="utf-8")
        filesystem_ok = probe.read_text(encoding="utf-8") == "ok"
        checks["filesystem"] = {"temp_write_read": filesystem_ok}

    if configured_store_root is not None:
        store_check: dict[str, Any] = {"path": str(configured_store_root)}
        if configured_store_root.is_symlink():
            store_check.update({"usable": False, "reason": "store root is a symlink"})
        else:
            try:
                store = LocalEvidenceStore(configured_store_root)
                lock_count = sum(1 for _ in (store.root / "records").glob("*/*.lock"))
                store_check.update({"usable": True, "lock_files": lock_count})
            except Exception as exc:
                store_check.update({"usable": False, "reason": f"{type(exc).__name__}: {exc}"})
        checks["evidence_store"] = store_check

    ok = python_supported and filesystem_ok
    return {
        "status": "pass" if ok else "fail",
        "checks": checks,
        "_exit_code": 0 if ok else 5,
        "_proof": [
            "deep doctor checks only local runtime/filesystem/tool availability",
            "optional SDK absence is diagnostic and does not weaken core deterministic authority",
            "configured evidence-store locks are reported rather than auto-recovered",
        ],
    }


def _trial_payload(trial: EvaluatedTrial, *, include_evidence: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "trial_id": trial.evidence.trial_id,
        "verdict": trial.verdict.value,
        "evidence_root": trial.evidence.evidence_root,
        "oracle_results": [
            {
                "name": result.name,
                "verdict": result.verdict.value,
                "critical": result.critical,
                "reasons": list(result.reasons),
                "failure_codes": [code.value for code in result.failure_codes],
            }
            for result in trial.oracle_results
        ],
        "semantic_judgment": (
            trial.semantic_judgment.model_dump(mode="json")
            if trial.semantic_judgment is not None
            else None
        ),
    }
    if include_evidence:
        payload["evidence"] = trial.evidence.model_dump(mode="json")
    return payload


def _with_events(evidence: TrialEvidence, events: Sequence[EvidenceEvent]) -> TrialEvidence:
    normalized = tuple(
        event.model_copy(update={"sequence": index}) for index, event in enumerate(events)
    )
    return TrialEvidence(
        trial_id=evidence.trial_id,
        subject_identity=evidence.subject_identity,
        scenario_identity=evidence.scenario_identity,
        events=normalized,
        final_state=evidence.final_state,
        final_output=evidence.final_output,
        elapsed_ms=evidence.elapsed_ms,
        input_tokens=evidence.input_tokens,
        output_tokens=evidence.output_tokens,
        estimated_cost_usd=evidence.estimated_cost_usd,
    )


def _load_verdict_vector(path: Path, *, label: str) -> tuple[TrialVerdict, ...]:
    raw = load_json(path, label=label, require_object=False)
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, dict) and isinstance(raw.get("verdicts"), list):
        values = raw["verdicts"]
    elif isinstance(raw, dict) and raw.get("schema_version") == "agent-evals/assurance-report/v7":
        values = [
            record.verdict.value
            for record in AssuranceReportV7.model_validate(raw).predecessor_report.trials
        ]
    elif isinstance(raw, dict) and raw.get("schema_version") == "agent-evals/assurance-report/v6":
        values = [record.verdict.value for record in AssuranceReport.model_validate(raw).trials]
    else:
        raise ValueError(
            f"{label} must be a JSON verdict array, an object with verdicts, or a v6/v7 report"
        )
    try:
        return tuple(TrialVerdict(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} contains an invalid trial verdict") from exc
