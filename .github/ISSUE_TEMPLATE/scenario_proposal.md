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
