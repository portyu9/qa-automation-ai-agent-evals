# Evaluation Model

## Vocabulary

The framework uses precise terms because agent evaluation becomes ambiguous when `task`, `run`, `trace`, and `success` are treated as synonyms.

| Term | Meaning |
|---|---|
| **Subject** | exact agent system configuration being evaluated |
| **Scenario** | versioned objective, initial state, authority, and acceptance contract |
| **Trial** | one attempt by one subject against one scenario |
| **Event** | one normalized observable interaction or control-plane observation |
| **Trajectory** | ordered event history for a trial |
| **Outcome** | terminal environment/state condition after the trial |
| **Oracle** | deterministic logic that converts evidence into a bounded conclusion |
| **Reliability report** | aggregate statistics over repeated trial verdicts |
| **Release gate** | deterministic policy that decides whether evidence is sufficient for acceptance |

## Outcome versus output

The most important distinction is between **what the agent said** and **what actually happened**.

For a transactional agent:

```text
Final output: "Your refund was created."
Outcome:      refund row exists in the authorized tenant with expected amount/status
```

Only the second fact can close a required state outcome.

The same principle applies to coding agents (tests/build state), research agents (source/evidence requirements), and operational agents (external system state).

## Deterministic oracle precedence

The current runtime has two deterministic oracles:

1. policy oracle;
2. outcome oracle.

If either fails, the trial is `FAIL`. No aggregate quality score can override that trial-level deterministic failure.

Provider/runtime failure is instead `BLOCKED`, because the framework lacks sufficient execution evidence to decide the scenario itself.

## Partial quality versus terminal correctness

Future graders may produce partial-credit dimensions such as helpfulness, completeness, tone, groundedness, or efficiency. Those metrics are useful for optimization, but they answer different questions from deterministic state and safety gates.

A system can therefore be semantically excellent and still release-ineligible because of one unauthorized side effect.

## Capability and regression use

`ScenarioKind` distinguishes several intent classes:

- `CAPABILITY`: explores what a subject can do;
- `REGRESSION`: protects behavior that should remain stable;
- `SECURITY`: attempts to violate authority or confidentiality boundaries;
- `RESILIENCE`: exercises failure, latency, malformed input, retry, or dependency behavior;
- `METAMORPHIC`: evaluates behavioral relations across controlled perturbations.

The enum is implemented now. Full scenario packs for each class are not yet part of the repository.

## Evidence ordering

Event sequences must be contiguous from zero. This prevents a normalized trace from silently presenting reordered causal history as if it were original execution order.

For policy assertions such as approval-before-mutation, event ordering is part of correctness and is evaluated directly.

## Criticality

Criticality is not a weighting trick. A critical oracle failure is a qualitative release condition.

Examples that should normally be modeled as critical include:

- cross-tenant access;
- secret exfiltration;
- approval bypass;
- forbidden privileged mutation;
- sandbox escape;
- authorization-policy violation.

The current `PolicyOracle` marks policy failure critical. More specialized critical oracles can extend the same release semantics later.
