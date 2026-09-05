# Evaluation Model

## Vocabulary

The framework uses precise terms because agent evaluation becomes ambiguous when `task`, `run`, `trace`, `score`, and `success` are treated as synonyms.

| Term | Meaning |
|---|---|
| **Subject** | exact agent system configuration being evaluated |
| **Scenario** | versioned objective, initial state, authority, acceptance contract, and optional semantic rubric |
| **Trial** | one attempt by one subject against one scenario |
| **Event** | one normalized observable interaction or control-plane observation |
| **Trajectory** | ordered event history for a trial |
| **Outcome** | terminal environment/state condition after the trial |
| **Deterministic oracle** | evaluator logic that converts state/policy evidence into a bounded conclusion without model judgment |
| **Semantic rubric** | scenario-owned, content-addressed criteria and score thresholds for meaning-level output evaluation |
| **Semantic judge** | subordinate evaluator whose profile and calibration must be accepted before it may grade |
| **Semantic receipt** | integrity-bound record tying one semantic decision to the exact scenario, subject, rubric, calibrated judge profile, structured response, and pre-semantic evidence root |
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

The same principle applies to coding agents (tests/build state), research agents (source/evidence requirements), and operational agents (external system state). Semantic judging may evaluate whether final prose satisfies a scenario-owned meaning-level rubric, but it does not turn prose into evidence of an external side effect.

## Grading precedence

The runtime has two deterministic oracles:

1. policy oracle;
2. outcome oracle.

When a scenario has no semantic rubric, those oracles preserve the existing deterministic-only behavior: any oracle failure yields `FAIL`; otherwise the trial yields `PASS`.

When `EvaluationScenario.semantic_rubric` is configured, semantic grading is subordinate to those deterministic results:

```text
adapter evidence
    ↓
verified delivery / approval / protocol preconditions
    ↓
PolicyOracle + OutcomeOracle
    ├─ any deterministic FAIL ───────────────→ FAIL
    │                                         semantic judge is not called
    └─ deterministic PASS
             ↓
       exact accepted judge calibration
             ↓
       bounded semantic judgment
             ├─ PASS ───────────────────────→ PASS
             ├─ FAIL ───────────────────────→ FAIL (non-critical)
             └─ ABSTAIN ────────────────────→ INCONCLUSIVE
```

A semantic result cannot rescue a deterministic failure. The runtime intentionally short-circuits semantic invocation when policy or outcome grading has already failed. This is stronger than merely choosing the deterministic result after both graders run: the subordinate judge receives no subject output for a deterministically failed trial.

Provider/runtime failure, unverifiable evaluation preconditions, malformed semantic evidence, missing semantic-judge authority, or judge execution failure instead become `BLOCKED`, because the framework lacks sufficient trusted evidence to decide the configured evaluation contract.

## Semantic rubric identity

`SemanticRubricSpec` is part of `EvaluationScenario.identity`. Its behavior-bearing fields include:

- rubric ID and revision;
- ordered criterion IDs;
- criterion descriptions;
- integer score thresholds.

Changing a criterion, threshold, or rubric revision therefore changes scenario identity. Recorded semantic evidence cannot silently replay under a materially different meaning-level contract.

Criterion order is deliberate. `SemanticJudgeResponse` must contain exactly the same criterion identities in the same order. Each resolved criterion carries an integer score from 0 through 4; the evaluator independently rederives PASS/FAIL from the criterion threshold. `ABSTAIN` carries no score. The overall semantic decision is also rederived from the criterion results rather than trusted as an independent model claim.

## Semantic judge authority and calibration

A configured `SemanticJudge` has no authority merely because it can return structured JSON. Before invocation the runtime revalidates:

- exact content-addressed `SemanticJudgeProfile`;
- exact `SemanticCalibrationReceipt`;
- calibration acceptance under its frozen policy;
- equality between the live judge profile and the calibrated profile.

The calibration model tracks more than aggregate accuracy. It separately binds PASS/FAIL class support, false-PASS count and rate, abstentions, judge/malformed-response failures, and required adversarial coverage tags. The default policy requires explicit `judge-prompt-injection` coverage and zero false PASS, abstention, or judge-failure tolerance unless the policy is intentionally changed.

Calibration is still empirical evidence about a fixed judge configuration, not proof that a model is universally correct. Changing prompt material, behavior configuration, model name/revision, adapter identity, or response schema changes the judge profile identity and invalidates calibration reuse.

## Bounded semantic input

The default `SemanticJudgeInput` intentionally contains only:

- scenario objective;
- exact semantic rubric;
- candidate final output.

It does not expose arbitrary tool payloads, credentials, approval material, environment state, or the full evidence stream. Candidate output is data to grade, not an evaluator instruction surface.

The optional OpenAI Agents SDK implementation serializes this object as canonical JSON and uses a fixed evaluator-owned prompt that explicitly treats `candidate_output` as untrusted data. The deterministic SDK test lane verifies that prompt-injection-like candidate text remains inside the JSON data boundary. This is a narrow evaluator-hardening property, not a claim that prompt injection is solved in general.

## Semantic evidence binding

A semantic judgment is persisted as one terminal, non-critical `SEMANTIC_JUDGMENT` event. Its receipt binds the exact evidence root that existed **before** the semantic event was appended. That avoids a circular hash while preserving a checkable causal relation:

```text
subject evidence root
        ↓ exact digest bound into receipt
SemanticJudgmentReceipt
        ↓ terminal non-critical event
final TrialEvidence root
```

The receipt binds scenario identity, subject identity, rubric identity, judge profile, accepted calibration identity, bounded judge-input digest, structured-response digest, derived decision, criterion results, and an outer domain-separated root.

Semantic evidence is invalid if it is duplicated, non-terminal, marked critical, emitted from an unknown evaluator source, bound to the wrong scenario/subject/rubric, or tied to a different pre-semantic evidence root.

## Replay semantics

Replay is historical verification, not fresh semantic inference. When valid semantic evidence is already present, `EvidenceReplayAdapter` re-emits it and `TrialRunner` reconstructs the pre-semantic envelope, revalidates the receipt, reruns deterministic oracles, and rederives precedence without calling a semantic model.

A replayed semantic receipt therefore says, "this exact historical judgment remains internally valid for this exact recorded evidence and scenario identity." It does not say the judge would return the same answer today, and replay does not establish current provider availability or liveness.

## Partial quality versus terminal correctness

Meaning-level dimensions such as groundedness, completeness, or answer quality are useful, but they answer different questions from deterministic state and safety gates.

A system can therefore receive a semantic PASS and still be release-ineligible because of an unauthorized side effect. Conversely, a semantically poor answer can yield a non-critical semantic FAIL even when all state and policy checks passed. These conclusions are intentionally separate in `AssuranceReport` v2.

## Capability and regression use

`ScenarioKind` distinguishes several intent classes:

- `CAPABILITY`: explores what a subject can do;
- `REGRESSION`: protects behavior that should remain stable;
- `SECURITY`: attempts to violate authority or confidentiality boundaries;
- `RESILIENCE`: exercises failure, latency, malformed input, retry, or dependency behavior;
- `METAMORPHIC`: evaluates behavioral relations across controlled perturbations.

The enum is implemented now. Full scenario packs for every class are not claimed by the repository.

## Evidence ordering

Event sequences must be contiguous from zero. This prevents a normalized trace from silently presenting reordered causal history as if it were original execution order.

For policy assertions such as approval-before-mutation, and for semantic receipt binding to pre-semantic evidence, event ordering is part of correctness and is evaluated directly.

## Criticality

Criticality is not a weighting trick. A critical oracle failure is a qualitative release condition. Semantic judgment is deliberately non-critical in the current design; it may narrow deterministic PASS to FAIL or INCONCLUSIVE, but it never contributes to the deterministic critical-violation count.

Examples that should normally be modeled as critical include:

- cross-tenant access;
- secret exfiltration;
- approval bypass;
- forbidden privileged mutation;
- sandbox escape;
- authorization-policy violation.

The current `PolicyOracle` marks policy failure critical. More specialized deterministic critical oracles can extend the same release semantics without granting semantic models critical release authority.

See [Semantic Judging](SEMANTIC_JUDGING.md), [Evidence Persistence and Replay](EVIDENCE_AND_REPLAY.md), and [Session Assurance Reports](ASSURANCE_REPORTS.md) for the corresponding trust boundaries.
