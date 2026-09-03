# Architecture

## Purpose

The framework evaluates an **agent system**, not a detached model response. The evaluated subject includes the provider/model configuration plus the application revision, instructions, tool schemas, authority policy, memory policy, and adapter version that together determine behavior.

The design starts with identity and evidence, then derives conclusions. It never starts with a score and works backward to justify it.

## Trust model

```text
Trusted evaluation control plane
├── subject/scenario contracts
├── deterministic adversarial scenario derivation
├── controlled attack injector boundary
│   ├── OpenAI USER_INPUT injector
│   ├── OpenAI local FunctionTool TOOL_RESULT injector
│   └── OpenAI local FunctionTool TOOL_METADATA description injector
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
└── provider responses, hosted/external tools, MCP servers, target systems,
    memory stores, resources, user simulators, controlled fault injectors

Persistence substrate
└── filesystem bytes are reverified before becoming evidence again
```

External content may become evidence or adversarial stimulus. It does not become control-plane authority merely because the agent, provider, tool, MCP server, or fixture returned it. Persisted bytes and serialized report fields likewise do not become true merely because they occupy framework-shaped structures.

The trusted evaluation control plane is itself bounded: a delivery receipt is a control-plane observation, not cryptographic proof that an arbitrary external target consumed the stimulus. Stronger injector authentication or target-side attestation is a separate deployment layer.

## Subject identity

`SubjectFingerprint` is content-addressed across provider, model, application revision, instructions, tool schema, authority policy, memory policy, and adapter identity/version. This prevents materially different agent systems from being compared under a misleading model-only label.

## Scenario identity

An `EvaluationScenario` binds stable ID/revision, classification, objective, initial state, authority, required outcomes, forbidden outcomes, and tags. Contradictory outcome requirements are rejected at validation time.

## Deterministic adversarial derivation

`AttackFixture` turns one versioned threat stimulus into content-addressed test input. Applying it to a base scenario preserves the base objective, exact `AuthorityPolicy`, required/forbidden outcomes, and deep-copied base state while adding deterministic attack identity and a reserved attack envelope.

`AdversarialCampaign` binds one exact base scenario to a canonical set of unique attacks and rechecks the captured base identity before derivation so post-construction nested drift fails closed.

The attack envelope is a **delivery contract**, not proof of delivery. A controlled adapter/environment must perform the real injection at the declared user/tool/metadata/memory/resource/handoff/environment boundary. `extract_attack(..., expected_base_scenario=...)` can rederive the complete scenario and detect drift outside the envelope.

`OpenAIAgentsAdapter` currently closes three concrete delivery paths:

- `USER_INPUT`: objective plus exact canonical fixture JSON are supplied as two ordered `Runner.run` user messages;
- local-`FunctionTool` `TOOL_RESULT`: a per-trial copied target tool replaces the first matching invocation result with exact canonical fixture JSON and binds the receipt to the exact SDK call ID;
- local-`FunctionTool` description-level `TOOL_METADATA`: a per-trial copied target has only its `description` replaced with exact canonical fixture JSON before the cloned agent enters `Runner.run`.

Both local tool channels share the same fail-closed target resolver and leave the reusable original agent/tool unchanged. They do not claim hosted-tool, MCP, external registry, or arbitrary external-tool interception.

See [Adversarial Testing](ADVERSARIAL_TESTING.md) and [OpenAI Adapter](OPENAI_ADAPTER.md).

## Attack-delivery verification

`AttackDeliveryReceipt` binds the control plane's successful-delivery observation to exact derived scenario identity, exact attack identity, attack channel, concrete injection point, SHA-256 of the canonical attack payload, and a domain-separated receipt root.

The receipt excludes the raw adversarial payload. `receipt.to_event()` emits normalized `ATTACK_DELIVERY` evidence with an explicit `injector:<identity>` source label.

For an adversarial scenario, `TrialRunner` requires exactly one valid receipt before behavioral oracles execute. Missing, duplicate, malformed, forged, or mismatched delivery evidence causes critical `EVALUATION_ERROR` and `BLOCKED` with no completed subject-oracle results.

```text
unverified attack delivery                → BLOCKED
verified attack + deterministic violation → FAIL
verified attack + deterministic closure   → PASS
```

Injector/evaluation failures therefore do not pollute behavioral failure rates or critical subject-violation counts. Receipt roots/source labels are integrity/control-plane identities, not signatures, MACs, or target-side attestations.

## Authority is fail-closed

`AuthorityPolicy` has explicit allowed/forbidden tools, approval-required tools, resource prefixes, and tool/handoff budgets. Unknown tools are not implicitly permitted. Resource scope and approval requirements fail closed.

The policy oracle detects unauthorized tool requests, privileged use before approval, out-of-scope resources, explicit policy violations, tool-call budget excess, and handoff budget excess. Policy failure is critical.

Adversarial scenario derivation never gets a special authority path: the base authority contract remains unchanged.

## Evidence model

Every `EvidenceEvent` has ordered sequence, kind, source, payload, timestamp, and critical flag. `TrialEvidence` requires a contiguous stream from sequence zero.

The vocabulary includes subject/runtime observations and evaluation-control observations such as `ATTACK_DELIVERY` and `EVALUATION_ERROR`. Delivery events participate in the same evidence chain rather than a disconnected side log.

The domain-separated `evidence_root` binds trial, subject, scenario, ordered event digests, terminal state/output, timing, token usage, and cost. It is an integrity mechanism, not publisher authentication.

For local tool-result injection, chronology is explicit:

```text
TOOL_REQUEST
ATTACK_DELIVERY
TOOL_RESULT
```

The receipt injection point includes the exact SDK tool call ID, and the normalized `TOOL_RESULT` contains the same canonical fixture JSON returned to the model loop.

For local tool-metadata injection, the receipt is emitted before subject execution because the copied `FunctionTool.description` already equals the complete canonical fixture JSON before `Runner.run`. The independent SDK test then observes that exact description in the model-call tool snapshot.

## Persistence boundary

`LocalEvidenceStore` persists canonical payload bytes plus a strict manifest binding record key, evaluation identities, byte length, payload SHA-256, and semantic evidence root.

Reads revalidate file type, symlink constraints, size ceilings, manifest schema, record-key derivation, payload hash, evidence schema, evaluation identity, and evidence root. Writes use same-record locking, no-clobber publication, and manifest-last commit semantics.

This mechanism does not authenticate a writer who can coherently replace both payload and manifest. See [Evidence Persistence and Replay](EVIDENCE_AND_REPLAY.md).

## Adapter boundary

`AgentAdapter` executes one exact subject/scenario pair and normalizes observations into `AdapterResult`. It does not grade itself, weaken authority, reinterpret provider errors as success, grant release authority, or substitute prose for state.

For adversarial scenarios, the adapter/environment owns concrete delivery. `AdapterPreconditionError` is the explicit boundary for a controlled prerequisite it cannot satisfy. `TrialRunner` converts it to `EVALUATION_ERROR / BLOCKED` with no subject oracles; provider/runtime exceptions remain separately classified as `RUNTIME_ERROR / BLOCKED`.

### Shared OpenAI local-tool isolation

For local `FunctionTool` `TOOL_RESULT` and `TOOL_METADATA` attacks, `OpenAIAgentsAdapter` uses one target-resolution policy:

1. validate the channel-specific identity-bearing payload contract;
2. require an OpenAI SDK `Agent`;
3. resolve exactly one local tool by fixture-bound name;
4. require an SDK `FunctionTool`;
5. copy the target;
6. clone the agent with a fresh tools list;
7. mutate only the per-trial copy for the requested attack boundary.

The reusable original agent/tool remain untouched.

### Tool-result specialization

The copied invocation callback replaces the first matching call with exact canonical attack JSON and records a call-ID-bound receipt. The original function does not execute on that injected call; later matching calls use copied original behavior.

If the target never runs, no receipt exists and delivery verification blocks the trial. If the call identity cannot be bound safely, the adapter precondition-blocks.

This is controlled result replacement and does not preserve original side effects on the injected call.

### Tool-metadata specialization

The copied target's `description` becomes exact canonical attack JSON before execution. Tool name, parameter schema, invocation callback, approval semantics, and routing identity remain unchanged.

The injection point is:

```text
openai-agents:FunctionTool:<tool>:description
```

A receipt can be emitted immediately because the controlled copied metadata boundary has already been established. `ScriptedModel` observes the exact poisoned description, and a later ordinary run observes the original description.

Keeping name/schema fixed isolates description poisoning from schema drift, routing manipulation, or discovery poisoning. Those require separate explicit contracts.

`memory`, `resource`, `handoff`, and `environment` remain unsupported by the OpenAI adapter. Hosted/MCP/external result and metadata manipulation remain outside the local-tool boundary.

The deterministic `ScriptedAdapter` exists to test the harness itself without provider credentials.

## Trial derivation

`TrialRunner` performs this sequence:

1. execute the adapter against one exact subject/scenario pair;
2. convert `AdapterPreconditionError` to critical `EVALUATION_ERROR / BLOCKED` with no subject oracles;
3. convert provider/runtime exceptions to critical `RUNTIME_ERROR / BLOCKED` without retaining raw detail;
4. construct immutable `TrialEvidence` when execution returns normally;
5. for adversarial scenarios, require exactly one matching delivery receipt;
6. block with critical `EVALUATION_ERROR` if delivery verification fails;
7. run deterministic policy and outcome oracles;
8. derive `FAIL` if any deterministic oracle fails, otherwise `PASS`.

There is no model-authored red-team score and no rule that treats absence of suspicious prose as safety evidence.

## Exact-identity replay

`EvidenceReplayAdapter` performs historical regrading, not agent re-execution. It refuses replay when trial, subject, or scenario identity differs.

For adversarial evidence, the recorded delivery receipt is replayed and revalidated before deterministic subject grading. Replay does not run the injector again and cannot establish fresh provider liveness, external state, side effects, delivery, or publisher/injector identity.

## Repeated trials

`EvaluationSession` repeats isolated trials and builds a `ReliabilityReport`. Delivery-caused `BLOCKED` remains blocked rather than becoming `FAIL`, keeping evaluator/injector reliability distinct from subject behavioral reliability.

## Session assurance artifacts

`AssuranceReport` binds trial IDs, evidence roots, deterministic oracle snapshots, trial verdicts, reliability outputs, frozen release policy, release-gate result, and a domain-separated report root.

On load it revalidates unique trial identities, resolved verdict/oracle consistency, blocked-trial semantics, reliability, critical-violation counts, release-gate output, and report-root integrity.

Delivery-caused `BLOCKED` trials have no completed deterministic oracle snapshots, do not contribute behavioral failures or critical subject-oracle counts, and may keep release `INCONCLUSIVE` when evidence requirements are unmet.

Full per-trial delivery/policy/outcome regrading still requires underlying evidence and the replay path. See [Session Assurance Reports](ASSURANCE_REPORTS.md).

## Release authority

`ReleaseGate` consumes statistical evidence plus critical-violation counts. Critical safety evidence is non-compensatory. Insufficient trials, weak confidence bounds, or excess blocked/inconclusive evidence produce `INCONCLUSIVE` rather than acceptance.

## Why exact trajectories are not the default oracle

A trajectory is evidence, but not every trajectory difference is a defect. Exact path assertions are appropriate when the path itself is contractual or safety-critical; otherwise independently observed outcome/state should dominate.

## Current boundary

The core currently provides deterministic contracts, adversarial fixtures/campaigns, evidence-bound attack-delivery verification, concrete OpenAI `USER_INPUT`, local-`FunctionTool` `TOOL_RESULT`, and local-`FunctionTool` description-level `TOOL_METADATA` injection, identity-bound evidence, local integrity-verified persistence, exact-identity historical replay, deterministic state/policy oracles, metamorphic relations, repeated-trial statistics, assurance reports, release gating, failure minimization, and a deterministic OpenAI Agents SDK integration tier.

The current source checkpoint is **155 passed, 6 deselected, 93.67% branch coverage**, strict mypy clean across **34 source files**, with **6/6** deterministic OpenAI SDK tests green.

Credentialed live-provider assurance, memory/resource/handoff/environment injectors, tool-name/parameter-schema poisoning, hosted/MCP result or metadata interception, cryptographically authenticated injector identity, target-side delivery attestation, automatic/adaptive adversarial generation, hostile-writer authenticated evidence/report signing, remote attestation, immutable remote retention, MCP fault servers, calibrated semantic graders, and automatic perturbation generation remain separate implementation layers and are not represented as complete.
