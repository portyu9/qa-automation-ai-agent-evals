"""Operational performance guardrails for deterministic assurance kernels.

Timing is diagnostic CI evidence, never grading or release-result authority. The fixed generous
ceilings catch accidental algorithmic regressions while avoiding claims about production latency.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialVerdict
from agent_evals.statistics.sufficient import BinarySufficientStatistics, PairedSufficientStatistics

SCHEMA_VERSION = "agent-evals/deterministic-performance/v1"
BUDGET_SECONDS = {
    "event_digest_5000": 3.0,
    "binary_sufficient_100k": 1.0,
    "paired_sufficient_100k": 1.5,
}


def _median_runtime(callable_obj, repeats: int = 5) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        started = perf_counter()
        callable_obj()
        samples.append(perf_counter() - started)
    return statistics.median(samples)


def _measure() -> dict[str, float]:
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.STATE,
        source="performance-gate",
        payload={"items": list(range(128)), "label": "x" * 1024},
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
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

    return {
        "event_digest_5000": _median_runtime(digest_work),
        "binary_sufficient_100k": _median_runtime(
            lambda: BinarySufficientStatistics.from_verdicts(binary)
        ),
        "paired_sufficient_100k": _median_runtime(
            lambda: PairedSufficientStatistics.from_verdicts(baseline, candidate)
        ),
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
