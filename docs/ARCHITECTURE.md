# Architecture

## Purpose

The framework evaluates an **agent system**, not a detached model response. The evaluated subject includes the provider/model configuration plus the application revision, instructions, tool schemas, authority policy, memory policy, and adapter version that together determine behavior.

The design therefore starts with identity and evidence, then derives conclusions. It never starts with a score and works backward to justify it.

## Trust model

```text
Trusted evaluation control plane
├── subject/scenario contracts
├── evidence normalization contract
├── local evidence-store verifier
├── exact-identity replay boundary
├── deterministic policy oracle
├── deterministic outcome oracle
├── statistical calculations
├── session assurance-report verifier
└── release gate

Untrusted / evaluated subject
└── agent runtime + model + orchestration + tools + memory behavior

External evidence sources
└── provider responses, tool results, target systems, MCP servers, user simulators

Persistence substrate
└── filesystem bytes are reverified before becoming evidence again
```

External content may become evidence. It does not become control-plane authority merely because the agent or provider returned it. Persisted bytes likewise do not become trusted merely because they occupy a framework-shaped filename. Serialized report fields likewise do not become true merely because they carry a percentage, verdict, or release label.

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

The trial computes a domain-separated `evidence_root` that first binds `trial_id`, `subject_identity`, and `scenario_identity`, then hash-chains event digests in order, then binds terminal state, final output, timing, token usage, and cost metadata into the final digest.

This is an integrity mechanism, not a digital signature. It detects content/order/identity change relative to a trusted root; it does not establish publisher identity.

## Persistence boundary

`LocalEvidenceStore` persists one `TrialEvidence` as canonical payload bytes plus a strict manifest. The manifest binds the record key, exact trial/subject/scenario identity, payload byte length, payload SHA-256, and semantic `evidence_root`.

The local filesystem is treated as a persistence substrate, not as an oracle. Reads revalidate file type, symlink constraints, size ceilings, manifest schema, record-key derivation, payload hash, evidence schema, evaluation identity, and evidence root before returning trusted evidence.

Writes are immutable per record identity. A same-record writer lock prevents cooperative duplicate writers; no-clobber hard-link publication prevents a destination that appears during final publication from being silently overwritten. The payload is materialized before the manifest, making the manifest the commit marker. Partial records and stale locks fail closed and require explicit operator review.

This mechanism does not authenticate a writer who can coherently replace both payload and manifest. See [Evidence Persistence and Replay](EVIDENCE_AND_REPLAY.md).

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
2. convert provider/runtime exceptions into critical `RUNTIME_ERROR` evidence and `BLOCKED` without retaining raw exception detail;
3. construct immutable `TrialEvidence`;
4. run deterministic policy and outcome oracles;
5. derive `FAIL` if any deterministic oracle fails, otherwise `PASS`.

A future semantic/model grader may enrich quality measurement but will remain subordinate to deterministic safety and state authority.

## Exact-identity replay

`EvidenceReplayAdapter` is an adapter boundary for **historical regrading**, not agent re-execution. It refuses replay when the requested trial ID, subject identity, or scenario identity differs from the recorded evidence.

A valid replay emits the historical observations unchanged so `TrialRunner` can apply the deterministic policy and outcome oracles again. For the same evidence model, exact-identity replay reproduces the original evidence root.

Replay cannot establish current provider liveness, current external state, fresh side effects, or publisher identity.

## Repeated trials

`EvaluationSession` repeats isolated trials and builds a `ReliabilityReport`. Trial IDs bind scenario ID, revision, and an attempt index. Repeated execution is required because an agent's observed behavior is stochastic even when its configuration is fixed.

## Session assurance artifacts

`AssuranceReport` binds one exact session to its trial IDs, evidence roots, deterministic oracle snapshots, trial verdicts, reliability outputs, frozen release policy, release-gate result, and a domain-separated report root.

The report is self-validating at the **session derivation** layer. On construction and load it verifies unique trial identities, resolved verdict/oracle consistency, blocked-trial semantics, reliability recomputation, critical-violation recomputation, release-gate recomputation, and report-root integrity.

The report does not contain the entire underlying `TrialEvidence`, so it does not claim to rerun policy/outcome oracles from an evidence hash alone. Full per-trial historical regrading still flows through integrity-verified evidence retrieval and `EvidenceReplayAdapter`.

This separation prevents a stored success percentage or release label from becoming authority merely because it was serialized. See [Session Assurance Reports](ASSURANCE_REPORTS.md).

## Release authority

`ReleaseGate` consumes statistical evidence plus critical-violation counts.

Its safety rule is deliberately non-compensatory: if critical violations exceed the policy maximum, the decision is `REJECT` regardless of aggregate success rate.

Insufficient trials, weak confidence bounds, or excess inconclusive evidence produce `INCONCLUSIVE` rather than acceptance.

## Why exact trajectories are not the default oracle

A trajectory is evidence, but not every trajectory difference is a defect. Capable agents may discover multiple legitimate routes to the same outcome.

Trajectory assertions are appropriate when the path itself is part of correctness—for example approval-before-mutation, a forbidden tool, a protocol transition, or a required handoff boundary. Otherwise outcome/state verification should dominate.

## Current boundary

The core currently provides deterministic contracts, identity-bound evidence, local integrity-verified evidence persistence, exact-identity replay, execution, state/policy oracles, metamorphic relations, repeated-trial statistics, self-validating session assurance reports, release gating, failure minimization, and a deterministic OpenAI Agents SDK integration tier.

Credentialed live-provider assurance, hostile-writer authenticated evidence/report signing, remote attestation, immutable remote retention, MCP fault servers, calibrated semantic graders, and automatic perturbation generation remain separate implementation layers and are not represented as complete in this document.
