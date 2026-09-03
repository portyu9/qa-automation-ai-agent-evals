# Architecture

## Purpose

The framework evaluates an **agent system**, not a detached model response. The evaluated subject includes the provider/model configuration plus the application revision, instructions, tool schemas, authority policy, memory policy, and adapter version that together determine behavior.

The design therefore starts with identity and evidence, then derives conclusions. It never starts with a score and work backward to justify it.

## Trust model

```text
Trusted evaluation control plane
├── subject/scenario contracts
├── evidence normalization contract
├── deterministic policy oracle
├── deterministic outcome oracle
├── statistical calculations
└── release gate

Untrusted / evaluated subject
└── agent runtime + model + orchestration + tools + memory behavior

External evidence sources
└── provider responses, tool results, target systems, MCP servers, user simulators
```

External content may become evidence. It does not become control-plane authority merely because the agent or provider returned it.

## Subject identity

`SubjectFingerprint` is content-addressed across the behavior-bearing configuration currently available to the harness:

- provider;
- model;
- application revision;
- instructions hash;
- tool-schema hash;
- authority-policy hash;
- memory-policy hash;
- adapter identity and version.

The fingerprint prevents a common eval failure: comparing results produced by materially different agent systems while labeling the comparison only by model name.

## Scenario identity

An `EvaluationScenario` binds:

- stable scenario ID;
- scenario revision;
- capability/regression/security/resilience/metamorphic classification;
- objective;
- initial state;
- authority boundary;
- required outcomes;
- forbidden outcomes;
- tags.

Contradictory outcome requirements are rejected at model validation time.

## Authority is fail-closed

`AuthorityPolicy` has explicit allowed and forbidden tools, approval-required tools, resource prefixes, and tool/handoff budgets. An unknown tool is not implicitly permitted. A resource outside all authorized prefixes is rejected. Approval-required tools must also be present in the allowlist.

The current policy oracle evaluates observable events and detects:

- unauthorized tool requests;
- privileged tool use before approval;
- out-of-scope resources;
- explicit policy-violation events;
- tool-call budget excess;
- handoff budget excess.

Policy failure is marked critical.

## Evidence model

Every `EvidenceEvent` has an ordered sequence number, event kind, source, payload, timestamp, and critical flag. `TrialEvidence` requires the event stream to be contiguous from sequence zero.

The trial computes an `evidence_root` by hash-chaining event digests in order and then binding the terminal state, final output, timing, token usage, and cost metadata into the final digest.

This is an integrity mechanism, not a digital signature. It detects accidental or unacknowledged content/order change; it does not establish publisher identity.

## Adapter boundary

`AgentAdapter` has one job: execute the subject for a scenario and normalize what happened into an `AdapterResult`.

The adapter does **not**:

- decide PASS/FAIL;
- weaken scenario authority;
- reinterpret a provider error as success;
- grant release authority;
- substitute final prose for state.

The deterministic `ScriptedAdapter` exists to test the harness itself without provider credentials.

## Trial derivation

`TrialRunner` performs the following sequence:

1. execute the adapter against one exact subject/scenario pair;
2. convert provider/runtime exceptions into critical `RUNTIME_ERROR` evidence and `BLOCKED`;
3. construct immutable `TrialEvidence`;
4. run deterministic policy and outcome oracles;
5. derive `FAIL` if any deterministic oracle fails, otherwise `PASS`.

A future semantic/model grader may enrich quality measurement but will remain subordinate to deterministic safety and state authority.

## Repeated trials

`EvaluationSession` repeats isolated trials and builds a `ReliabilityReport`. Trial IDs bind scenario ID, revision, and an attempt index. Repeated execution is required because an agent's observed behavior is stochastic even when its configuration is fixed.

## Release authority

`ReleaseGate` consumes statistical evidence plus critical-violation counts.

Its safety rule is deliberately non-compensatory: if critical violations exceed the policy maximum, the decision is `REJECT` regardless of aggregate success rate.

Insufficient trials, weak confidence bounds, or excess inconclusive evidence produce `INCONCLUSIVE` rather than acceptance.

## Why exact trajectories are not the default oracle

A trajectory is evidence, but not every trajectory difference is a defect. Capable agents may discover multiple legitimate routes to the same outcome.

Trajectory assertions are appropriate when the path itself is part of correctness—for example approval-before-mutation, a forbidden tool, a protocol transition, or a required handoff boundary. Otherwise outcome/state verification should dominate.

## Current boundary

The core currently provides deterministic contracts, evidence, execution, state/policy oracles, statistics, release gating, and minimization. Live-provider adapters, persistent evidence storage, MCP simulators, semantic graders, and metamorphic execution are future implementation layers and are not represented as complete in this document.
