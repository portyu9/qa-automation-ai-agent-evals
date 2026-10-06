from __future__ import annotations

import hashlib

import pytest

from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.contracts.scenario_quality import (
    RegressionPromotionProposal,
    ScenarioCoverageReport,
    ScenarioQualityCode,
    ScenarioQualitySeverity,
    ScenarioSemanticDuplicateDeclaration,
    SemanticDuplicateRelation,
    lint_scenario_contracts,
    lint_semantic_duplicate_declarations,
    require_no_semantic_duplicates,
)
from agent_evals.contracts.scenario_registry import (
    BenchmarkExposure,
    BenchmarkLeakageMetadata,
    LeakageRisk,
    ScenarioDifficulty,
    ScenarioLifecycle,
    ScenarioOrigin,
    ScenarioProvenance,
    ScenarioRegistry,
    ScenarioRegistryEntry,
)


def _scenario(
    scenario_id: str,
    *,
    kind: ScenarioKind = ScenarioKind.REGRESSION,
    oracle: bool = True,
    authority: AuthorityPolicy | None = None,
) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id=scenario_id,
        revision="1",
        kind=kind,
        objective=f"Exercise {scenario_id}.",
        authority=authority or AuthorityPolicy(),
        required_outcomes={"ok": True} if oracle else {},
        tags=frozenset({"quality"}),
    )


def _benchmark() -> BenchmarkLeakageMetadata:
    return BenchmarkLeakageMetadata(
        exposure=BenchmarkExposure.PRIVATE_HOLDOUT,
        partition_id="quality-holdout",
        contamination_risk=LeakageRisk.LOW,
        memorization_risk=LeakageRisk.LOW,
        review_revision="1",
    )


def _entry(
    scenario: EvaluationScenario,
    *,
    provenance: ScenarioProvenance | None = None,
    lifecycle: ScenarioLifecycle = ScenarioLifecycle.ACTIVE,
    deprecation_reason: str | None = None,
) -> ScenarioRegistryEntry:
    return ScenarioRegistryEntry.create(
        scenario,
        owner="evaluation-platform",
        taxonomy=("assurance", scenario.kind.value),
        population_scope="Synthetic deterministic scenarios.",
        rationale="Exercise scenario quality contracts.",
        difficulty=ScenarioDifficulty.STANDARD,
        benchmark=_benchmark(),
        provenance=provenance,
        lifecycle=lifecycle,
        deprecation_reason=deprecation_reason,
    )


def test_coverage_requires_capability_security_resilience_and_metamorphic() -> None:
    entries = tuple(
        _entry(_scenario(f"coverage.{kind.value}", kind=kind))
        for kind in (
            ScenarioKind.CAPABILITY,
            ScenarioKind.SECURITY,
            ScenarioKind.RESILIENCE,
            ScenarioKind.METAMORPHIC,
        )
    )
    registry = ScenarioRegistry.create(
        registry_id="coverage-registry",
        revision="1",
        entries=entries,
    )

    report = ScenarioCoverageReport.create(registry)
    assert report.accepted is True
    assert {item.kind for item in report.counts} == {
        ScenarioKind.CAPABILITY,
        ScenarioKind.SECURITY,
        ScenarioKind.RESILIENCE,
        ScenarioKind.METAMORPHIC,
    }

    deprecated = entries[-1]
    deprecated_scenario = _scenario("coverage.deprecated", kind=ScenarioKind.METAMORPHIC)
    deprecated_entry = _entry(
        deprecated_scenario,
        lifecycle=ScenarioLifecycle.DEPRECATED,
        deprecation_reason="rotated out",
    )
    missing_active = ScenarioRegistry.create(
        registry_id="coverage-registry",
        revision="2",
        entries=entries[:-1] + (deprecated_entry,),
    )
    assert ScenarioCoverageReport.create(missing_active).accepted is False


def test_scenario_quality_lint_detects_trivial_and_unreachable_authority() -> None:
    trivial = _scenario("quality.trivial", oracle=False)
    impossible = _scenario(
        "quality.zero-budget",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"mutate"}),
            max_tool_calls=0,
        ),
    )

    findings = lint_scenario_contracts((trivial, impossible))
    codes = {item.code for item in findings}

    assert ScenarioQualityCode.TRIVIAL_NO_ORACLE in codes
    assert ScenarioQualityCode.TOOL_AUTHORITY_WITH_ZERO_BUDGET in codes
    assert all(item.severity is ScenarioQualitySeverity.ERROR for item in findings)


def test_semantic_duplicate_review_is_explicit_and_non_hash_based() -> None:
    first = _scenario("semantic.first")
    second = _scenario("semantic.second")
    registry = ScenarioRegistry.create(
        registry_id="semantic-dedup",
        revision="1",
        entries=(_entry(first), _entry(second)),
    )
    left, right = sorted((first.identity, second.identity))
    equivalent = ScenarioSemanticDuplicateDeclaration(
        left_scenario_identity=left,
        right_scenario_identity=right,
        relation=SemanticDuplicateRelation.EQUIVALENT,
        reviewer="benchmark-review",
        review_revision="review-1",
        rationale_sha256=hashlib.sha256(b"same behavioral task").hexdigest(),
    )

    findings = lint_semantic_duplicate_declarations(registry, (equivalent,))
    assert len(findings) == 1
    assert findings[0].severity is ScenarioQualitySeverity.ERROR
    with pytest.raises(ValueError, match="semantic duplicates"):
        require_no_semantic_duplicates(registry, (equivalent,))

    distinct = equivalent.model_copy(
        update={"relation": SemanticDuplicateRelation.DISTINCT_AFTER_REVIEW}
    )
    assert lint_semantic_duplicate_declarations(registry, (distinct,)) == ()


def test_regression_promotion_binds_minimized_failure_to_source_evidence() -> None:
    parent = _scenario("promotion.parent", kind=ScenarioKind.SECURITY)
    child = _scenario("promotion.regression", kind=ScenarioKind.REGRESSION)
    evidence_root = "b" * 64
    provenance = ScenarioProvenance(
        origin=ScenarioOrigin.MINIMIZED_FAILURE,
        parent_scenario_identity=parent.identity,
        source_trial_id="campaign/session/trial-7",
        source_evidence_root=evidence_root,
    )
    registry = ScenarioRegistry.create(
        registry_id="promotion-registry",
        revision="1",
        entries=(_entry(parent), _entry(child, provenance=provenance)),
    )

    proposal = RegressionPromotionProposal.from_registry(
        registry,
        promoted_scenario_identity=child.identity,
    )
    assert proposal.promoted_scenario_identity == child.identity
    assert proposal.parent_scenario_identity == parent.identity
    assert proposal.source_evidence_root == evidence_root

    with pytest.raises(ValueError, match="regression scenario"):
        RegressionPromotionProposal.from_registry(
            registry,
            promoted_scenario_identity=parent.identity,
        )
