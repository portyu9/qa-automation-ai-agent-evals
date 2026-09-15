from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_evals.contracts import models as contract_models
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.comparison import PairedComparison, _exact_mcnemar_p_value
from agent_evals.statistics.limits import MAX_PASS_K, MAX_STATISTICAL_TRIALS
from agent_evals.statistics.reliability import ReliabilityReport

P = TrialVerdict.PASS
F = TrialVerdict.FAIL


def _fingerprint(**overrides: Any) -> SubjectFingerprint:
    material: dict[str, Any] = {
        "provider": "example",
        "model": "model-a",
        "application_revision": "abc123",
        "instructions": "Be useful.",
        "tool_schema": {"tools": [{"name": "lookup"}]},
        "policy": {"allowed": ["lookup"]},
        "memory_policy": {"retention": "trial"},
        "adapter": "scripted",
        "adapter_version": "1",
    }
    material.update(overrides)
    return SubjectFingerprint.from_material(**material)


def test_contract_guard_preserves_existing_subject_identity_bytes() -> None:
    assert _fingerprint().identity == (
        "d80e8b01f2f3618af58a13dfaa44d761646735a28186a25993d35174c607c38d"
    )


def test_contract_depth_guard_runs_before_recursive_json_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material: object = "leaf"
    for _ in range(contract_models._MAX_CANONICAL_DEPTH + 1):
        material = {"next": material}

    def fail_json_dump(*args: object, **kwargs: object) -> str:
        raise AssertionError("json.dumps must not run for over-depth contract material")

    monkeypatch.setattr(contract_models.json, "dumps", fail_json_dump)
    with pytest.raises(ValueError, match="nesting depth ceiling"):
        _fingerprint(tool_schema=material)


def test_contract_guard_rejects_reference_cycles_without_recursion_failure() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(ValueError, match="reference cycles"):
        _fingerprint(policy=cyclic)


def test_contract_guard_rejects_overwide_material_before_canonical_sorting() -> None:
    too_wide = list(range(contract_models._MAX_CANONICAL_COLLECTION_ITEMS + 1))

    with pytest.raises(ValueError, match="collection-size ceiling"):
        _fingerprint(memory_policy={"values": too_wide})


def test_scenario_state_uses_same_pre_serialization_complexity_guard() -> None:
    material: object = "leaf"
    for _ in range(contract_models._MAX_CANONICAL_DEPTH + 1):
        material = {"next": material}

    with pytest.raises(ValidationError, match="nesting depth ceiling"):
        EvaluationScenario(
            scenario_id="complexity.state",
            revision="1",
            kind=ScenarioKind.SECURITY,
            objective="Reject over-deep state before JSON serialization.",
            initial_state={"root": material},
        )


@pytest.mark.parametrize(
    ("baseline_only", "candidate_only", "expected"),
    [
        (0, 0, 1.0),
        (2, 0, 0.5),
        (1, 3, 0.625),
        (12, 0, 0.00048828125),
    ],
)
def test_stable_mcnemar_recurrence_preserves_exact_small_vector_results(
    baseline_only: int,
    candidate_only: int,
    expected: float,
) -> None:
    assert _exact_mcnemar_p_value(baseline_only, candidate_only) == pytest.approx(
        expected, rel=1e-12, abs=1e-15
    )


def test_mcnemar_handles_balanced_maximum_supported_work_without_big_integer_material() -> None:
    half = MAX_STATISTICAL_TRIALS // 2
    result = PairedComparison.compare([P] * half + [F] * half, [F] * half + [P] * half)

    assert result.baseline_only_pass == half
    assert result.candidate_only_pass == half
    assert result.exact_p_value == 1.0


def test_statistics_reject_oversized_vectors_before_scanning_members() -> None:
    oversized = [object()] * (MAX_STATISTICAL_TRIALS + 1)

    with pytest.raises(ValueError, match="at most .* trial pairs"):
        PairedComparison.compare(oversized, oversized)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at most .* trials"):
        ReliabilityReport.from_verdicts(oversized)  # type: ignore[arg-type]


def test_reliability_bounds_repeat_exponent_contract() -> None:
    with pytest.raises(ValueError, match="between 1 and"):
        ReliabilityReport.from_verdicts([P, F], k=MAX_PASS_K + 1)
