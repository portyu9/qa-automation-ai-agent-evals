# Metamorphic Mutation Generation and Effectiveness

The existing metamorphic relation layer verifies declared behavioral relations. This module adds deterministic evaluator-authored mutation recipes and per-parent mutant-kill effectiveness metrics.

## Mutation generation

`MetamorphicMutationSpec` declares a controlled transformation: a new scenario id/revision plus optional objective suffix, top-level initial-state overlay/removal, and added tags. `generate_metamorphic_mutant()` revalidates the parent, applies only that declared transform, creates a METAMORPHIC scenario, and returns a `MetamorphicMutationRecord` binding parent identity, mutant identity, relation id, and mutation-spec identity.

The framework does not infer that a recipe is semantics-preserving. The evaluator owns the relation hypothesis and must choose transformations appropriate to the scenario.

## Effectiveness

`MetamorphicEffectivenessReport` records KILLED, SURVIVED, and BLOCKED outcomes for unique mutants of exactly one parent scenario. BLOCKED is never flattened into SURVIVED or KILLED and is excluded from the evaluable denominator.

Acceptance uses integer sufficient statistics and cross-multiplication against an integer kill-ratio policy, avoiding floating-point rounding as authority.

A high kill rate means the configured mutations were effective against the tested scenario/relation set. It is not a universal measure of benchmark quality or model safety.
