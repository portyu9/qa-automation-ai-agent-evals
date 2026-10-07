"""Operational performance guardrails for deterministic assurance kernels.

Timing is diagnostic CI evidence, never grading or release-result authority. Fixed generous
ceilings catch accidental algorithmic regressions without claiming production latency.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.evidence.store import LocalEvidenceStore
from agent_evals.gates.release import ReleasePolicy
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.sampling import (
    RandomnessStatus,
    SamplingPolicy,
    SessionSamplingMetadata,
    StoppingRule,
)
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport
from agent_evals.statistics.streaming import StreamingBinaryAggregator
from agent_evals.statistics.sufficient import BinarySufficientStatistics, PairedSufficientStatistics

SCHEMA_VERSION = "agent-evals/deterministic-performance/v2"
BUDGET_SECONDS = {
    "event_digest_5000": 3.0,
    "binary_sufficient_100k": 1.0,
    "paired_sufficient_100k": 1.5,
    "streaming_binary_100k": 2.0,
    "report_verify_100": 2.0,
    "evidence_root_5000": 3.0,
    "evidence_publication_100": 8.0,
}


def _median_runtime(callable_obj, repeats: int = 5) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        started = perf_counter()
        callable_obj()
        samples.append(perf_counter() - started)
    return statistics.median(samples)


def _report_fixture() -> AssuranceReport:
    scenario = EvaluationScenario(
        scenario_id="performance.report",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Benchmark deterministic report verification",
    )
    evidence = TrialEvidence(
        trial_id="campaign:performance:attempt:0000",
        subject_identity="d" * 64,
        scenario_identity=scenario.identity,
    )
    results = grade_deterministic_evidence(scenario, evidence)
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=results,
        verdict=TrialVerdict.PASS,
    )
    session = EvaluationSessionResult(
        subject_identity=evidence.subject_identity,
        scenario_identity=scenario.identity,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((TrialVerdict.PASS,)),
        campaign_id="performance",
        runtime_adapter_name="performance-runtime",
        subject_adapter="performance-subject",
        subject_adapter_version="1",
        sampling_metadata=SessionSamplingMetadata(
            sampling_policy=SamplingPolicy.PREDECLARED_ALL_ATTEMPTS,
            randomness_status=RandomnessStatus.UNKNOWN,
            stopping_rule=StoppingRule.FIXED_HORIZON,
            planned_trials=1,
        ),
    )
    return AssuranceReport.from_session(
        session,
        scenario=scenario,
        release_policy=ReleasePolicy(
            min_resolved_trials=1,
            min_success_rate=0.0,
            min_wilson_low=0.0,
            max_critical_violations=0,
            max_blocked_trials=0,
            max_inconclusive_trials=0,
        ),
    )


def _measure() -> dict[str, float]:
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.STATE,
        source="performance-gate",
        payload={"items": list(range(128)), "label": "x" * 1024},
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    evidence = TrialEvidence(
        trial_id="performance-evidence",
        subject_identity="a" * 64,
        scenario_identity="b" * 64,
        events=(event,),
        final_state={"items": list(range(64))},
    )
    report = _report_fixture()
    report_json = report.model_dump_json()
    binary = tuple(
        verdict
        for _ in range(25_000)
        for verdict in (
            TrialVerdict.PASS,
            TrialVerdict.FAIL,
            TrialVerdict.BLOCKED,
            TrialVerdict.INCONCLUSIVE,
        )
    )
    baseline = tuple(
        verdict for _ in range(50_000) for verdict in (TrialVerdict.PASS, TrialVerdict.FAIL)
    )
    candidate = tuple(
        verdict for _ in range(50_000) for verdict in (TrialVerdict.FAIL, TrialVerdict.PASS)
    )

    def digest_work() -> None:
        for _ in range(5_000):
            _ = event.digest

    def evidence_root_work() -> None:
        for _ in range(5_000):
            _ = evidence.evidence_root

    def streaming_work() -> None:
        aggregate = StreamingBinaryAggregator()
        for verdict in binary:
            aggregate.update(verdict)
        _ = aggregate.snapshot().statistics_root

    def report_verify_work() -> None:
        for _ in range(100):
            _ = AssuranceReport.model_validate_json(report_json)

    def publication_work() -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalEvidenceStore(Path(directory) / "evidence")
            for index in range(100):
                store.write(
                    TrialEvidence(
                        trial_id=f"publication-{index}",
                        subject_identity="a" * 64,
                        scenario_identity="b" * 64,
                        final_state={"index": index},
                    )
                )

    return {
        "event_digest_5000": _median_runtime(digest_work),
        "binary_sufficient_100k": _median_runtime(
            lambda: BinarySufficientStatistics.from_verdicts(binary)
        ),
        "paired_sufficient_100k": _median_runtime(
            lambda: PairedSufficientStatistics.from_verdicts(baseline, candidate)
        ),
        "streaming_binary_100k": _median_runtime(streaming_work),
        "report_verify_100": _median_runtime(report_verify_work),
        "evidence_root_5000": _median_runtime(evidence_root_work),
        "evidence_publication_100": _median_runtime(publication_work, repeats=3),
    }


def _violations(measured: dict[str, float]) -> list[str]:
    errors: list[str] = []
    if set(measured) != set(BUDGET_SECONDS):
        return ["measurement key set does not match fixed performance-budget key set"]
    for name, budget in BUDGET_SECONDS.items():
        value = measured[name]
        if type(value) is not float or value < 0.0:
            errors.append(f"{name}: runtime must be a non-negative float")
        elif value > budget:
            errors.append(f"{name}: median {value:.6f}s exceeds fixed budget {budget:.6f}s")
    return errors


def _self_test() -> None:
    below = {name: budget * 0.5 for name, budget in BUDGET_SECONDS.items()}
    if _violations(below):
        raise AssertionError("below-budget measurements must pass")
    above = dict(below)
    first = next(iter(BUDGET_SECONDS))
    above[first] = BUDGET_SECONDS[first] * 1.01
    if not _violations(above):
        raise AssertionError("above-budget measurement must fail")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("Deterministic performance budget self-test passed")
        return 0

    measured = _measure()
    result = {
        "schema_version": SCHEMA_VERSION,
        "authority": "operational-diagnostic-only",
        "measurements_seconds": measured,
        "budgets_seconds": BUDGET_SECONDS,
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
            encoding="utf-8",
        )

    errors = _violations(measured)
    for name in BUDGET_SECONDS:
        print(f"{name}: median={measured[name]:.6f}s budget={BUDGET_SECONDS[name]:.6f}s")
    if errors:
        for error in errors:
            print(f"PERFORMANCE REGRESSION: {error}")
        return 1
    print("Deterministic performance budgets passed (operational diagnostic only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
