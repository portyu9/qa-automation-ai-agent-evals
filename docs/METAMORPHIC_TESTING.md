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

It detects expansion through more than the obvious root tool allowlist. A transformed policy violates monotonicity when it:

- grants a new effective root tool;
- removes an approval requirement from a retained root tool;
- introduces root resource authority where none existed;
- widens a root resource prefix outside the baseline scope;
- increases root turn, tool-call, or handoff budgets;
- removes an existing delegated-handoff attenuation boundary and falls back to the less constrained legacy single-authority mode;
- changes the root-agent identity of an existing delegated graph;
- introduces a directed handoff transition that the baseline did not authorize;
- widens a retained grant's delegated tools or resource prefixes;
- removes a retained grant's additional approval requirement from a still-delegated tool;
- increases a retained grant's delegated tool-call or handoff budget.

When both policies use delegated handoff authority, every transformed transition must already exist in the baseline and each retained grant must be structurally no broader than its baseline counterpart. Removing a transition is a restriction. Narrowing delegated tools/resources/budgets is a restriction. A baseline additional approval requirement may disappear only when the transformed grant no longer delegates the affected tool.

Adding a validated handoff graph to a legacy single-authority policy is also treated as attenuation when the root policy itself does not expand: legacy mode applies root authority across handoff-shaped behavior, whereas the graph activates explicit transition checks and path-local authority subsets.

This matters because permission can be laundered across dimensions and across agents. Removing one root tool while broadening resource scope, budgets, or a downstream grant is not a monotonic reduction in executable authority.

Resource containment follows the framework's documented lexical-prefix authority semantics; this helper does not reinterpret prefixes as filesystem paths or URLs.

## Current non-claim

The repository now implements relation primitives, not automatic perturbation generation. Scenario transformations such as paraphrase generation, irrelevant-context injection, tenant substitution, retry perturbation, and memory mutation will be added only with deterministic provenance and replay semantics.
