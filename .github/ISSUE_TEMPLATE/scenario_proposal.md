---
name: Scenario proposal
about: Propose a versioned evaluation scenario or regression fixture
title: "scenario: "
labels: ""
assignees: ""
---

## Objective and population

What agent behavior is this scenario intended to evaluate, and for which subject/system population is the result meaningful?

## Scenario kind and risk tags

Choose capability, regression, security, resilience, or metamorphic; propose stable tags and a difficulty/risk rationale.

## Registry metadata

Name the owning team/role, taxonomy path, intended population scope, difficulty, prerequisite scenario identities, and lifecycle/deprecation status. If this is an intentional exact structural alias, explain the duplicate waiver.

## Benchmark exposure and leakage

Classify the benchmark material as stable-public, rotating-private, or private-holdout. For rotating-private material, identify the rotation epoch/ID. Record contamination and memorization risk plus the review revision. A private label is not secrecy if raw material is committed to a public repository.

## Promotion provenance

If the scenario was promoted from a counterexample or minimized failure, identify the exact parent scenario identity, source trial ID, and source evidence root. For a metamorphic mutant, identify the parent scenario and any source trial/evidence pair.

## Initial state and outcomes

Define the synthetic starting state, required outcomes, forbidden outcomes, and independent state observation method.

## Authority

Specify allowed/forbidden tools, resource scope, approval requirements, budgets and handoff grants. Explain why the authority is minimal for the objective.

## Evidence / preconditions

What delivery, retrieval, MCP, approval, side-effect, or semantic precondition must close before behavioral grading is valid?

## Expected failure classes

Describe at least one valid PASS path, one deterministic FAIL path, and any condition that must remain `BLOCKED` or `INCONCLUSIVE`.

## Non-claims and leakage

State what the scenario does not establish and any benchmark leakage/contamination risk.

Use synthetic data only. Do not include credentials, private production payloads, or sensitive customer data.
