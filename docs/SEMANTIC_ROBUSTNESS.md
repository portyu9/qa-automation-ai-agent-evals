# Semantic robustness diagnostics

The semantic robustness surface is deliberately subordinate to deterministic grading and to the
existing calibration authority boundary. It measures instability; it does not create authority.

## What is measured

`SemanticStabilityObservation` records controlled paraphrase, order, and format perturbations for
one exact judge-profile identity. `SemanticDriftObservation` compares one case across two distinct
judge-profile identities. `SemanticAgreementObservation` records canonical pairwise inter-judge
agreement. `SemanticEnsembleObservation` records two or more profile-bound decisions and exposes
only a consistency classification.

`SemanticRobustnessSummary` derives integer sufficient statistics for surveillance: observation
counts, decision changes, disagreements, and abstention-bearing observations. It intentionally does
not derive rates, confidence claims, PASS/FAIL decisions, or acceptance status.

## Authority boundary

These diagnostics cannot replace or mint a `SemanticCalibrationReceipt` or
`StratifiedCalibrationReceipt`. A unanimous or majority-like ensemble shape is not a grading
decision. Stability across perturbations is not proof of correctness. Agreement between judges is
not proof of correctness. Drift absence is not proof that a model or provider is unchanged.

Deterministic failures remain non-compensatory. A semantic robustness result must never rescue a
deterministic FAIL or convert BLOCKED/INCONCLUSIVE behavioral evidence into PASS.

## Intended use

Use the diagnostics to detect regressions after judge model/revision, prompt-template, adapter, or
behavior-configuration changes; compare independent judges; and monitor sensitivity to controlled
input transformations. Release or grading policy may require review when diagnostics degrade, but
that policy must consume these measurements explicitly rather than treating them as semantic
authority.

The versioned observations are small, bounded contracts. Callers should retain the underlying
calibration/evidence bindings separately; the robustness layer does not duplicate or reinterpret
those receipts.
