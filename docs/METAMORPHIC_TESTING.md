# Metamorphic Testing

## Why agent assurance needs relations, not only expected answers

Many agent behaviors admit multiple valid outputs and trajectories. A brittle golden response can therefore reject legitimate capability while missing a deeper invariant violation.

Metamorphic testing evaluates a **relation** between controlled executions instead. The question becomes:

> When this input, state, or authority boundary changes in a controlled way, which observable properties must remain invariant, narrow, or change predictably?

The current implementation is deterministic and contains no model grader.

## State-projection invariance

`StateProjectionInvariant` compares explicitly selected terminal-state paths between a baseline and transformed trial. Paths are typed tuples such as:

```python
(("account", "status"), ("items", 0, "id"))
```

Tuple paths are intentionally unambiguous: dictionary keys can contain dots and list indexes are explicit.

The relation:

- requires both trials to evaluate the same subject identity;
- returns `INCONCLUSIVE` when either behavioral trial is unresolved;
- returns `INCONCLUSIVE` when a protected state path cannot be observed in both trials;
- returns `VIOLATED` when a protected value changes;
- ignores unconstrained output prose, event count, and unrelated state.

This makes it suitable for properties such as paraphrase invariance or irrelevant-context invariance once paired scenario perturbations are implemented.

## Authority monotonicity

`authority_does_not_expand()` compares a baseline authority contract with a supposedly more restrictive transformation.

It detects expansion through more than the obvious tool allowlist. A transformed policy violates monotonicity when it:

- grants a new effective tool;
- removes an approval requirement from a retained tool;
- introduces resource authority where none existed;
- widens a resource prefix outside the baseline scope;
- increases turn, tool-call, or handoff budgets.

This matters because permission can be laundered across dimensions. Removing one tool while broadening resource scope or budgets is not necessarily a reduction in authority.

## Current non-claim

The repository now implements relation primitives, not automatic perturbation generation. Scenario transformations such as paraphrase generation, irrelevant-context injection, tenant substitution, retry perturbation, and memory mutation will be added only with deterministic provenance and replay semantics.
