from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.contracts.scenario_registry import (
    BenchmarkExposure,
    BenchmarkLeakageMetadata,
    LeakageRisk,
    RegistryFindingCode,
    RegistryFindingSeverity,
    ScenarioDifficulty,
    ScenarioLifecycle,
    ScenarioOrigin,
    ScenarioProvenance,
    ScenarioRegistry,
    ScenarioRegistryEntry,
    lint_scenario_registry,
    require_scenario_registry_quality,
    scenario_registry_json_schema,
)


def _scenario(
    scenario_id: str,
    *,
    revision: str = "1",
    objective: str = "Exercise one deterministic registry behavior.",
    tags: frozenset[str] = frozenset({"risk.security"}),
) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id=scenario_id,
        revision=revision,
        kind=ScenarioKind.REGRESSION,
        objective=objective,
        required_outcomes={"state.ok": True},
        tags=tags,
    )


def _benchmark(
    *,
    exposure: BenchmarkExposure = BenchmarkExposure.PRIVATE_HOLDOUT,
    contamination_risk: LeakageRisk = LeakageRisk.LOW,
    memorization_risk: LeakageRisk = LeakageRisk.LOW,
    rotation_id: str | None = None,
) -> BenchmarkLeakageMetadata:
    return BenchmarkLeakageMetadata(
        exposure=exposure,
        partition_id="registry-holdout",
        rotation_id=rotation_id,
        contamination_risk=contamination_risk,
        memorization_risk=memorization_risk,
        review_revision="review-1",
    )


def _entry(
    scenario: EvaluationScenario,
    *,
    benchmark: BenchmarkLeakageMetadata | None = None,
    prerequisites: tuple[str, ...] = (),
    provenance: ScenarioProvenance | None = None,
    lifecycle: ScenarioLifecycle = ScenarioLifecycle.ACTIVE,
    deprecation_reason: str | None = None,
    superseded_by_scenario_identity: str | None = None,
    duplicate_waiver_reason: str | None = None,
) -> ScenarioRegistryEntry:
    return ScenarioRegistryEntry.create(
        scenario,
        owner="evaluation-platform",
        taxonomy=("agent-assurance", "regression"),
        population_scope="Synthetic deterministic agent subjects.",
        rationale="Retain a versioned regression contract with explicit benchmark metadata.",
        difficulty=ScenarioDifficulty.STANDARD,
        benchmark=benchmark or _benchmark(),
        prerequisites=prerequisites,
        provenance=provenance,
        lifecycle=lifecycle,
        deprecation_reason=deprecation_reason,
        superseded_by_scenario_identity=superseded_by_scenario_identity,
        duplicate_waiver_reason=duplicate_waiver_reason,
    )


def test_registry_entry_binds_scenario_without_embedding_raw_body() -> None:
    scenario = _scenario(
        "registry.binding",
        objective="private-objective-that-must-not-be-embedded",
    )
    entry = _entry(scenario)

    entry.verify_scenario(scenario)
    serialized = entry.model_dump_json()
    assert "private-objective-that-must-not-be-embedded" not in serialized
    assert "required_outcomes" not in serialized

    drifted = scenario.model_copy(update={"objective": "drifted objective"})
    with pytest.raises(ValueError, match=r"identity|fingerprint"):
        entry.verify_scenario(drifted)


def test_registry_is_canonical_and_requires_exact_scenario_corpus() -> None:
    first = _scenario("registry.first")
    second = _scenario("registry.second", objective="Second distinct behavior.")
    registry = ScenarioRegistry.create(
        registry_id="assurance-registry",
        revision="1",
        entries=(_entry(second), _entry(first)),
    )

    assert [entry.scenario_id for entry in registry.entries] == [
        "registry.first",
        "registry.second",
    ]
    registry.verify_scenarios((second, first))

    with pytest.raises(ValueError, match="exactly match"):
        registry.verify_scenarios((first,))


def test_exact_structural_duplicate_requires_bilateral_waiver() -> None:
    first = _scenario("registry.duplicate-a", tags=frozenset({"tag-a"}))
    second = _scenario(
        "registry.duplicate-b",
        revision="2",
        tags=frozenset({"tag-b"}),
    )
    registry = ScenarioRegistry.create(
        registry_id="duplicate-registry",
        revision="1",
        entries=(_entry(first), _entry(second)),
    )

    findings = lint_scenario_registry(registry)
    duplicate = [
        finding
        for finding in findings
        if finding.code is RegistryFindingCode.EXACT_BEHAVIOR_DUPLICATE
    ]
    assert len(duplicate) == 1
    assert duplicate[0].severity is RegistryFindingSeverity.ERROR
    with pytest.raises(ValueError, match="exact_behavior_duplicate"):
        require_scenario_registry_quality(registry)

    waived = ScenarioRegistry.create(
        registry_id="duplicate-registry",
        revision="2",
        entries=(
            _entry(first, duplicate_waiver_reason="Intentional alias for migration coverage."),
            _entry(second, duplicate_waiver_reason="Intentional alias for migration coverage."),
        ),
    )
    assert not any(
        finding.code is RegistryFindingCode.EXACT_BEHAVIOR_DUPLICATE
        for finding in lint_scenario_registry(waived)
    )


def test_structural_fingerprint_is_not_semantic_equivalence_claim() -> None:
    first = _scenario("registry.semantic-a", objective="Behavior A.")
    second = _scenario("registry.semantic-b", objective="Behavior B.")
    registry = ScenarioRegistry.create(
        registry_id="semantic-distinction",
        revision="1",
        entries=(_entry(first), _entry(second)),
    )

    assert registry.entries[0].behavioral_fingerprint != registry.entries[1].behavioral_fingerprint
    require_scenario_registry_quality(registry)


def test_registry_rejects_missing_and_cyclic_prerequisites() -> None:
    root = _scenario("registry.prereq-root")
    child = _scenario("registry.prereq-child", objective="Child behavior.")

    child_entry = _entry(child, prerequisites=(root.identity,))
    with pytest.raises(ValidationError, match="prerequisite is absent"):
        ScenarioRegistry.create(
            registry_id="missing-prerequisite",
            revision="1",
            entries=(child_entry,),
        )

    root_entry = _entry(root, prerequisites=(child.identity,))
    with pytest.raises(ValidationError, match="contains a cycle"):
        ScenarioRegistry.create(
            registry_id="cyclic-prerequisite",
            revision="1",
            entries=(root_entry, child_entry),
        )


def test_active_dependency_on_deprecated_scenario_is_linted() -> None:
    root = _scenario("registry.deprecated-root")
    child = _scenario("registry.active-child", objective="Active child behavior.")
    registry = ScenarioRegistry.create(
        registry_id="deprecated-prerequisite",
        revision="1",
        entries=(
            _entry(
                root,
                lifecycle=ScenarioLifecycle.DEPRECATED,
                deprecation_reason="Superseded by a later benchmark design.",
            ),
            _entry(child, prerequisites=(root.identity,)),
        ),
    )

    finding = next(
        item
        for item in lint_scenario_registry(registry)
        if item.code is RegistryFindingCode.ACTIVE_DEPENDS_ON_DEPRECATED
    )
    assert finding.severity is RegistryFindingSeverity.WARNING
    assert finding.scenario_identity == child.identity


def test_leakage_metadata_enforces_rotation_shape_and_surfaces_risk() -> None:
    with pytest.raises(ValidationError, match="requires rotation_id"):
        _benchmark(exposure=BenchmarkExposure.ROTATING_PRIVATE)

    with pytest.raises(ValidationError, match="cannot claim a rotation_id"):
        _benchmark(
            exposure=BenchmarkExposure.STABLE_PUBLIC,
            rotation_id="rotation-1",
        )

    scenario = _scenario("registry.public-risk")
    entry = _entry(
        scenario,
        benchmark=_benchmark(
            exposure=BenchmarkExposure.STABLE_PUBLIC,
            contamination_risk=LeakageRisk.UNKNOWN,
            memorization_risk=LeakageRisk.HIGH,
        ),
    )
    registry = ScenarioRegistry.create(
        registry_id="public-risk",
        revision="1",
        entries=(entry,),
    )
    findings = lint_scenario_registry(registry)
    codes = {finding.code for finding in findings}
    assert RegistryFindingCode.UNKNOWN_LEAKAGE_RISK in codes
    assert RegistryFindingCode.PUBLIC_HIGH_MEMORIZATION_RISK in codes
    unknown = next(
        finding for finding in findings if finding.code is RegistryFindingCode.UNKNOWN_LEAKAGE_RISK
    )
    assert unknown.severity is RegistryFindingSeverity.ERROR
    with pytest.raises(ValueError, match="unknown_leakage_risk"):
        require_scenario_registry_quality(registry)


def test_counterexample_promotion_binds_parent_trial_and_evidence() -> None:
    parent = _scenario("registry.parent")
    child = _scenario("registry.counterexample", objective="Promoted counterexample behavior.")

    with pytest.raises(ValidationError, match="source trial and evidence root"):
        ScenarioProvenance(
            origin=ScenarioOrigin.COUNTEREXAMPLE,
            parent_scenario_identity=parent.identity,
        )

    provenance = ScenarioProvenance(
        origin=ScenarioOrigin.COUNTEREXAMPLE,
        parent_scenario_identity=parent.identity,
        source_trial_id="trial-counterexample-1",
        source_evidence_root="a" * 64,
    )
    child_entry = _entry(child, provenance=provenance)

    with pytest.raises(ValidationError, match="provenance parent is absent"):
        ScenarioRegistry.create(
            registry_id="orphan-counterexample",
            revision="1",
            entries=(child_entry,),
        )

    registry = ScenarioRegistry.create(
        registry_id="counterexample-registry",
        revision="1",
        entries=(_entry(parent), child_entry),
    )
    promoted = next(
        entry for entry in registry.entries if entry.scenario_identity == child.identity
    )
    assert promoted.provenance.source_trial_id == "trial-counterexample-1"
    assert promoted.provenance.source_evidence_root == "a" * 64


def test_registry_revalidates_copied_entries_and_roots() -> None:
    scenario = _scenario("registry.revalidation")
    entry = _entry(scenario)
    forged_entry = entry.model_copy(update={"entry_root": "0" * 64})

    with pytest.raises(ValidationError, match="entry root mismatch"):
        ScenarioRegistry.create(
            registry_id="revalidation-registry",
            revision="1",
            entries=(forged_entry,),
        )

    registry = ScenarioRegistry.create(
        registry_id="revalidation-registry",
        revision="1",
        entries=(entry,),
    )
    payload = json.loads(registry.model_dump_json())
    payload["registry_root"] = "0" * 64
    with pytest.raises(ValidationError, match="registry root mismatch"):
        ScenarioRegistry.model_validate(payload)


def test_registry_json_schema_exports_versioned_tooling_contract() -> None:
    schema = scenario_registry_json_schema()

    assert schema["properties"]["schema_version"]["const"] == "agent-evals/scenario-registry/v1"
    assert "ScenarioRegistryEntry" in schema["$defs"]
    assert "BenchmarkLeakageMetadata" in schema["$defs"]
