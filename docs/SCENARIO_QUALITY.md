# Scenario Quality and Benchmark Coverage

The scenario registry binds metadata to immutable scenario identities. This companion layer adds coverage accounting, raw-contract quality linting, explicit semantic duplicate review, and regression-promotion proposals without changing `EvaluationScenario.identity`.

## Coverage

`ScenarioCoverageReport` tracks active scenario counts against integer minima. The default high-assurance categories are capability, security, resilience, and metamorphic. Deprecated scenarios do not satisfy active coverage.

Coverage counts measure corpus composition. They do not establish that the scenarios are representative of every deployment population.

## Raw-contract quality linting

`lint_scenario_contracts()` revalidates exact `EvaluationScenario` objects and surfaces deterministic findings for:
- scenarios with no deterministic or explicitly subordinate oracle;
- granted tool authority with a zero tool-call budget;
- handoff grants with a zero handoff budget;
- resource scopes with no root tools able to consume them;
- approval intent that cannot execute under a zero tool-call budget.

The linter complements model validators. It does not infer hidden semantics or claim that every non-trivial scenario is useful.

## Semantic duplicate review

Exact structural deduplication remains in `scenario_registry.py`. `ScenarioSemanticDuplicateDeclaration` adds an evaluator-reviewed semantic relation for scenario pairs: equivalent, near duplicate, or distinct after review. `require_no_semantic_duplicates()` rejects reviewer-confirmed equivalent pairs.

Semantic duplicate declarations are review evidence, not hash-derived semantics and not model self-certification.

## Regression promotion

`RegressionPromotionProposal.from_registry()` accepts only a registered REGRESSION scenario whose provenance is a counterexample or minimized failure with an exact parent scenario, source trial, and source evidence root. Its proposal root binds that lineage.

This creates an explicit bridge from failure minimization/counterexample harvesting into a proposed regression fixture while preserving the source evidence boundary.
