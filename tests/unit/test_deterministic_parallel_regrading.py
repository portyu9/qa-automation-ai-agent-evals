from __future__ import annotations

import pytest

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.runtime.regrading import deterministic_regrade_batch

SUBJECT = "a" * 64


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="runtime.parallel-regrade",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Pure deterministic regrading",
        required_outcomes={"ok": True},
    )


def _evidence(scenario: EvaluationScenario, index: int, *, ok: bool) -> TrialEvidence:
    return TrialEvidence(
        trial_id=f"trial-{index}",
        subject_identity=SUBJECT,
        scenario_identity=scenario.identity,
        final_state={"ok": ok},
    )


def test_parallel_deterministic_regrade_matches_serial_and_preserves_order() -> None:
    scenario = _scenario()
    evidence = tuple(_evidence(scenario, index, ok=index % 3 != 0) for index in range(64))

    serial = deterministic_regrade_batch(scenario, evidence, workers=1)
    parallel = deterministic_regrade_batch(scenario, evidence, workers=8)

    assert parallel == serial
    assert tuple(result.index for result in parallel) == tuple(range(64))
    assert tuple(result.trial_id for result in parallel) == tuple(
        item.trial_id for item in evidence
    )
    assert sum(result.verdict is TrialVerdict.FAIL for result in parallel) == 22
    assert all(result.oracle_results for result in parallel)


def test_parallel_deterministic_regrade_preserves_blocked_as_blocked() -> None:
    scenario = _scenario()
    blocked = TrialEvidence(
        trial_id="blocked",
        subject_identity=SUBJECT,
        scenario_identity=scenario.identity,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.EVALUATION_ERROR,
                source="evaluator:test",
                payload={"code": "fixture", "reason": "fixture"},
            ),
        ),
        final_state={"ok": True},
    )

    result = deterministic_regrade_batch(scenario, (blocked,), workers=4)[0]

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()


def test_parallel_regrade_rejects_cross_scenario_evidence() -> None:
    scenario = _scenario()
    other = EvaluationScenario(
        scenario_id="runtime.other",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="other",
    )
    evidence = TrialEvidence(
        trial_id="wrong-scenario",
        subject_identity=SUBJECT,
        scenario_identity=other.identity,
    )

    with pytest.raises(ValueError, match="scenario identity"):
        deterministic_regrade_batch(scenario, (evidence,), workers=2)


@pytest.mark.parametrize("workers", [0, 65, True])
def test_parallel_regrade_bounds_worker_count(workers: int) -> None:
    with pytest.raises(ValueError, match="workers"):
        deterministic_regrade_batch(_scenario(), (), workers=workers)
