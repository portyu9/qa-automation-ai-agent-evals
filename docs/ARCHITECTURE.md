# Architecture

## Purpose

The framework evaluates an **agent system**, not a detached model response. The evaluated subject includes the provider/model configuration plus the application revision, instructions, tool schemas, authority policy, memory policy, and adapter version that together determine behavior.

The design therefore starts with identity and evidence, then derives conclusions. It never starts with a score and works backward to justify it.

## Trust model

```text
Trusted evaluation control plane
├── subject/scenario contracts
├── deterministic adversarial scenario derivation
├── controlled attack injector boundary
│   └── OpenAI USER_INPUT injector (implemented)
├── attack-delivery receipt verifier
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

External evidence / attack-delivery sources
└── provider responses, tool results, target systems, MCP servers, user simulators,
    memory stores, controlled fault injectors

Persistence substrate
└── filesystem bytes are reverified before becoming evidence again
```

External content may become evidence or adversarial stimulus. It does not become control-plane authority merely because the agent, provider, tool, MCP server, or attack fixture returned it. Persisted bytes likewise do not become trusted merely because they occupy a framework-shaped filename. Serialized report fields likewise do not become true merely because they carry a percentage, verdict, or release label.

The trusted evaluation control plane is itself bounded: an attack-delivery receipt is accepted as a control-plane observation, not as cryptographic proof that an arbitrary external target consumed the stimulus. Stronger injector authentication or target-side attestation is a separate deployment layer.

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

## Deterministic adversarial derivation

`AttackFixture` turns one versioned threat stimulus into content-addressed test input. It binds a stable attack ID/revision, `ThreatClass`, declared `AttackChannel`, canonical finite JSON payload, and tags.

Applying a fixture to a base `EvaluationScenario` creates a security scenario while preserving the base objective, exact `AuthorityPolicy`, required outcomes, forbidden outcomes, and deep-copied base state. The derived scenario adds only deterministic attack identity/revision/tag material and a reserved attack envelope containing the exact base-scenario identity and attack identity.

`AdversarialCampaign` binds one exact base scenario to a canonical set of unique attacks. It normalizes attack order, binds the base identity at construction, and rechecks that identity before deriving scenarios so nested base-state drift fails closed.

The attack envelope is a **delivery contract**, not proof of delivery. An adapter or controlled environment must inspect the declared channel and actually inject the stimulus at the relevant user/tool/metadata/memory/resource/handoff/environment boundary. When the original base is supplied, `extract_attack(..., expected_base_scenario=...)` rederives the complete scenario and detects drift outside the envelope.

The OpenAI adapter currently closes one concrete path: `USER_INPUT`. It places the scenario objective and exact canonical attack payload into two ordered `Runner.run` user messages and emits the matching delivery receipt. Other channels remain unsupported by that adapter and fail before model execution.

See [Adversarial Testing](ADVERSARIAL_TESTING.md) and [OpenAI Adapter](OPENAI_ADAPTER.md).

## Attack-delivery verification

`AttackDeliveryReceipt` binds the control plane's successful-delivery observation to:

- exact derived scenario identity;
- exact attack identity;
- attack channel;
- concrete injection point;
- SHA-256 of the canonical attack payload;
- a domain-separated receipt root.

The receipt deliberately excludes the raw adversarial payload. `receipt.to_event()` emits normalized `ATTACK_DELIVERY` evidence with an explicit `injector:<identity>` source label.

For an adversarial scenario, `TrialRunner` requires exactly one valid receipt before behavioral oracles execute. `verify_attack_delivery()` recomputes the receipt and requires it to match the exact scenario/attack/channel/payload digest. Missing, duplicate, malformed, or mismatched delivery evidence causes a critical `EVALUATION_ERROR` and `BLOCKED` with no completed policy/outcome oracle results.

This is an **evaluation precondition**, not a subject oracle:

```text
unverified attack delivery → BLOCKED
verified attack + requirement violation → FAIL
verified attack + requirements close → PASS
```

Therefore injector/evaluation failures do not pollute behavioral failure rates or critical subject-violation counts.

The source label and receipt root are integrity/control-plane identities, not digital signatures, MACs, or target-side attestations.

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

Adversarial scenario derivation does not get a special authority path: the base authority contract is copied unchanged into the derived security scenario.

## Evidence model

Every `EvidenceEvent` has an ordered sequence number, event kind, source, payload, timestamp, and critical flag. `TrialEvidence` requires the event stream to be contiguous from sequence zero.

The evidence vocabulary includes subject/runtime observations plus evaluation-control observations such as `ATTACK_DELIVERY` and `EVALUATION_ERROR`. Delivery receipts participate in the same ordered evidence chain; they are not maintained as a disconnected side log.

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

For adversarial scenarios, the adapter/evaluation environment additionally owns the concrete delivery mechanism for the declared attack channel. After successful controlled delivery it can emit an `AttackDeliveryReceipt`; merely seeing an attack envelope does not prove that a malicious tool result, memory record, MCP description, resource, or handoff was actually presented to the subject.

`AdapterPreconditionError` is the explicit boundary for a controlled prerequisite that an adapter cannot satisfy. It carries only a bounded durable code/reason and is intentionally distinct from a provider/runtime exception. `TrialRunner` converts it to `EVALUATION_ERROR / BLOCKED` with no subject oracles. This lets an adapter fail closed for an unsupported attack channel without falsely attributing the problem to the provider or the agent.

`OpenAIAgentsAdapter` currently implements `USER_INPUT` delivery. Its other adversarial channels precondition-block before `Runner.run` is invoked.

The deterministic `ScriptedAdapter` exists to test the harness itself without provider credentials.

## Trial derivation

`TrialRunner` performs the following sequence:

1. execute the adapter against one exact subject/scenario pair;
2. convert an `AdapterPreconditionError` into critical `EVALUATION_ERROR` evidence and `BLOCKED` with no subject oracles;
3. convert provider/runtime exceptions into critical `RUNTIME_ERROR` evidence and `BLOCKED` without retaining raw exception detail;
4. construct immutable `TrialEvidence` when adapter execution returns normally;
5. for adversarial scenarios, verify exactly one matching attack-delivery receipt;
6. if delivery verification fails, append critical `EVALUATION_ERROR`, return `BLOCKED`, and run no subject oracles;
7. run deterministic policy and outcome oracles;
8. derive `FAIL` if any deterministic oracle fails, otherwise `PASS`.

An adversarial scenario otherwise enters the same subject-grading path as every other scenario. There is no model-authored red-team score and no special rule that treats the absence of suspicious prose as safety evidence.

A future semantic/model grader may enrich quality measurement but will remain subordinate to deterministic safety and state authority.

## Exact-identity replay

`EvidenceReplayAdapter` is an adapter boundary for **historical regrading**, not agent re-execution. It refuses replay when the requested trial ID, subject identity, or scenario identity differs from the recorded evidence.

A valid replay emits the historical observations unchanged. For an adversarial trial, this includes the recorded `ATTACK_DELIVERY` event, which `TrialRunner` revalidates before it reapplies deterministic policy/outcome grading. For the same evidence model, exact-identity replay reproduces the original evidence root.

Replay does not call the injector again. It therefore cannot establish current provider liveness, current external state, fresh side effects, fresh attack delivery, or publisher/injector identity.

## Repeated trials

`EvaluationSession` repeats isolated trials and builds a `ReliabilityReport`. Trial IDs bind scenario ID, revision, and an attempt index. Repeated execution is required because an agent's observed behavior is stochastic even when its configuration is fixed.

A delivery-caused `BLOCKED` result remains blocked at the session layer. It is not silently converted to `FAIL`, so evaluator/injector reliability remains distinct from subject behavioral reliability.

## Session assurance artifacts

`AssuranceReport` binds one exact session to its trial IDs, evidence roots, deterministic oracle snapshots, trial verdicts, reliability outputs, frozen release policy, release-gate result, and a domain-separated report root.

The report is self-validating at the **session derivation** layer. On construction and load it verifies unique trial identities, resolved verdict/oracle consistency, blocked-trial semantics, reliability recomputation, critical-violation recomputation, release-gate recomputation, and report-root integrity.

Delivery-caused `BLOCKED` trials contain no completed deterministic oracle snapshots. They remain blocked in the reliability snapshot, do not contribute behavioral failures or critical oracle-violation counts, and may cause the release decision to remain `INCONCLUSIVE` when evidence requirements are not met.

The report does not contain the entire underlying `TrialEvidence`, so it does not claim to rerun delivery verification or policy/outcome oracles from an evidence hash alone. Full per-trial historical regrading still flows through integrity-verified evidence retrieval and `EvidenceReplayAdapter`.

This separation prevents a stored success percentage or release label from becoming authority merely because it was serialized. See [Session Assurance Reports](ASSURANCE_REPORTS.md).

## Release authority

`ReleaseGate` consumes statistical evidence plus critical-violation counts.

Its safety rule is deliberately non-compensatory: if critical violations exceed the policy maximum, the decision is `REJECT` regardless of aggregate success rate.

Insufficient trials, weak confidence bounds, or excess blocked/inconclusive evidence produce `INCONCLUSIVE` rather than acceptance.

## Why exact trajectories are not the default oracle

A trajectory is evidence, but not every trajectory difference is a defect. Capable agents may discover multiple legitimate routes to the same outcome.

Trajectory assertions are appropriate when the path itself is part of correctness—for example approval-before-mutation, a forbidden tool, a protocol transition, or a required handoff boundary. Otherwise outcome/state verification should dominate.

## Current boundary

The core currently provides deterministic contracts, identity-bound adversarial fixtures/campaigns and scenario derivation, evidence-bound attack-delivery verification, one concrete OpenAI `USER_INPUT` injection path, identity-bound trial evidence, local integrity-verified evidence persistence, exact-identity historical replay, execution, state/policy oracles, metamorphic relations, repeated-trial statistics, self-validating session assurance reports, release gating, failure minimization, and a deterministic OpenAI Agents SDK integration tier.

Credentialed live-provider assurance, concrete injectors for tool-result/tool-metadata/memory/resource/handoff/environment channels, cryptographically authenticated injector identity, target-side delivery attestation, automatic/adaptive adversarial generation, hostile-writer authenticated evidence/report signing, remote attestation, immutable remote retention, MCP fault servers, calibrated semantic graders, and automatic perturbation generation remain separate implementation layers and are not represented as complete in this document.
