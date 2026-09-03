# Architecture

## Purpose

The framework evaluates an **agent system**, not a detached model response. The evaluated subject includes provider/model configuration plus application revision, instructions, tool schemas, authority policy, memory policy, adapter identity, and adapter version.

The design starts with identity and evidence, then derives conclusions. It never starts with a score and works backward to justify it.

## Trust model

```text
Trusted evaluation control plane
├── subject/scenario contracts
├── deterministic adversarial scenario derivation
├── controlled attack injector boundary
│   ├── OpenAI USER_INPUT injector
│   ├── OpenAI local FunctionTool TOOL_RESULT injector
│   ├── OpenAI local FunctionTool TOOL_METADATA description injector
│   ├── OpenAI per-trial Session-history MEMORY injector
│   ├── OpenAI structured inline-file RESOURCE injector
│   └── OpenAI first-native-handoff context injector
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
└── agent runtime + model + orchestration + tools + memory + resources + handoff behavior

External evidence / attack-delivery sources
└── provider responses, hosted/external tools, MCP servers, target systems,
    application memory stores, retrieval systems, resources, user simulators,
    controlled fault injectors

Persistence substrate
└── filesystem bytes are reverified before becoming evidence again
```

External content may become evidence or adversarial stimulus. It does not become control-plane authority merely because the agent, provider, tool, MCP server, session, resource, handoff, or fixture returned it.

The trusted control plane is itself bounded: a delivery receipt is a control-plane observation, not cryptographic proof that an arbitrary external target consumed the stimulus. Stronger injector authentication or target-side attestation is a separate deployment layer.

## Identity contracts

`SubjectFingerprint` is content-addressed across provider, model, application revision, instructions, tool schema, authority policy, memory policy, and adapter identity/version. An `EvaluationScenario` binds stable ID/revision, classification, objective, initial state, authority, required/forbidden outcomes, and tags.

This prevents materially different systems or objectives from being compared under misleading labels.

## Deterministic adversarial derivation

`AttackFixture` turns one versioned threat stimulus into content-addressed test input. Applying it to a base scenario preserves the base objective, exact `AuthorityPolicy`, required/forbidden outcomes, and deep-copied base state while adding deterministic attack identity and a reserved envelope.

`AdversarialCampaign` binds one exact base scenario to a canonical unique attack set and rechecks captured base identity before derivation so post-construction drift fails closed.

The attack envelope is a **delivery contract**, not proof of delivery. A controlled adapter/environment must perform real injection at the declared channel boundary.

## OpenAI delivery boundaries

`OpenAIAgentsAdapter` currently closes six concrete delivery paths:

- `USER_INPUT`: objective plus exact canonical fixture JSON are supplied as two ordered `Runner.run` user messages;
- local-`FunctionTool` `TOOL_RESULT`: a per-trial copied target replaces the first matching invocation result with exact canonical fixture JSON and binds delivery to exact SDK call ID;
- local-`FunctionTool` description-level `TOOL_METADATA`: a copied target has only its `description` replaced with exact canonical fixture JSON before the cloned agent enters `Runner.run`;
- SDK session-history `MEMORY`: a fresh per-trial `Session` returns exact canonical fixture JSON as one prior user item and the SDK runner prepends it before current input;
- structured inline-file `RESOURCE`: one `Runner.run` user input contains a structured `input_file` whose `file_data` is exact canonical fixture JSON and whose evaluator-owned filename is `agent-evals-resource.json`;
- native SDK `HANDOFF`: the run-level `handoff_input_filter` injects exact canonical fixture JSON into the **first actual handoff context** while preserving the SDK-selected destination.

Only generic `ENVIRONMENT` remains unsupported by this adapter.

The local tool channels share one fail-closed resolver and leave reusable original agent/tool objects unchanged. Memory uses a fresh session. Resource is an input structure created only for that trial. Handoff uses a fresh one-shot recorder/filter.

These paths do not claim hosted-tool/MCP interception, production memory stores, vector/RAG retrieval, hosted File Search, URL retrieval, arbitrary production document repositories, distributed agent-fabric interception, or external environment fault control.

See [Adversarial Testing](ADVERSARIAL_TESTING.md) and [OpenAI Adapter](OPENAI_ADAPTER.md).

## Attack-delivery verification

`AttackDeliveryReceipt` binds trusted successful-delivery observation to exact derived scenario identity, attack identity, channel, concrete injection point, SHA-256 of canonical attack payload, and a domain-separated receipt root.

The receipt excludes raw adversarial payload. For an adversarial scenario, `TrialRunner` requires exactly one valid receipt before behavioral oracles execute. Missing, duplicate, malformed, forged, or mismatched delivery evidence causes critical `EVALUATION_ERROR` and `BLOCKED` with no completed subject oracles.

```text
unverified attack delivery                → BLOCKED
verified attack + deterministic violation → FAIL
verified attack + deterministic closure   → PASS
```

## Authority is fail-closed

`AuthorityPolicy` has explicit allowed/forbidden tools, approval-required tools, resource prefixes, and tool/handoff budgets. Unknown tools are not implicitly permitted. Resource scope and approvals fail closed.

The policy oracle detects unauthorized tool requests, privileged use before approval, out-of-scope resources, explicit policy violations, tool-call budget excess, and handoff budget excess. Policy failure is critical.

Adversarial scenario derivation never receives a special authority path.

## Evidence model

Every `EvidenceEvent` has ordered sequence, kind, source, payload, timestamp, and critical flag. `TrialEvidence` requires a contiguous stream from sequence zero.

The domain-separated `evidence_root` binds trial, subject, scenario, ordered event digests, terminal state/output, timing, token usage, and cost. It is an integrity mechanism, not publisher authentication.

Important channel chronology/boundaries include:

```text
TOOL_RESULT: TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
HANDOFF:     HANDOFF → ATTACK_DELIVERY
```

`TOOL_METADATA`, `MEMORY`, `RESOURCE`, and `USER_INPUT` can establish their controlled injection structures before subject execution; their independent SDK tests then prove the exact prepared content is visible at the actual model-call boundary.

For `RESOURCE`, the receipt points specifically to:

```text
openai-agents:Runner.run.input[1].content[0]:input_file.file_data
```

and `ScriptedModel` must observe exact canonical fixture JSON in that structured file item.

## Persistence boundary

`LocalEvidenceStore` persists canonical payload bytes plus a strict manifest binding record key, evaluation identities, byte length, payload SHA-256, and semantic evidence root.

Reads revalidate file type, symlink constraints, size ceilings, manifest schema, record-key derivation, payload hash, evidence schema, evaluation identity, and evidence root. Writes use same-record locking, no-clobber publication, and manifest-last commit semantics.

This mechanism does not authenticate a writer who can coherently replace both payload and manifest. See [Evidence Persistence and Replay](EVIDENCE_AND_REPLAY.md).

## Adapter boundary

`AgentAdapter` executes one exact subject/scenario pair and normalizes observations into `AdapterResult`. It does not grade itself, weaken authority, reinterpret provider errors as success, grant release authority, or substitute prose for state.

For adversarial scenarios, the adapter/environment owns concrete delivery. `AdapterPreconditionError` is the explicit boundary for a controlled prerequisite it cannot satisfy. `TrialRunner` converts it to `EVALUATION_ERROR / BLOCKED`; provider/runtime exceptions remain `RUNTIME_ERROR / BLOCKED`.

### Local tool specialization

For local `FunctionTool` result/metadata attacks the adapter validates the identity-bearing payload, requires an SDK `Agent`, resolves one exact local `FunctionTool`, copies it, clones the agent, and mutates only the per-trial copy.

The result injector replaces the first matching call and binds receipt to call ID. The metadata injector changes only copied description. Neither claims hosted/MCP interception.

### Session-history memory specialization

For `MEMORY`, a fresh in-memory SDK `Session` is seeded with exact canonical attack JSON as one prior user item. The SDK itself retrieves and combines history with current input. A later ordinary run proves no inherited poison.

### Structured inline-resource specialization

For `RESOURCE`, `ResourceAttackPayload` requires a `resource` field. The adapter builds:

```text
input[0] = objective user message
input[1] = user message containing one input_file
           ├── file_data = exact canonical AttackFixture.payload_json
           └── filename  = agent-evals-resource.json
```

The independent SDK test asserts this exact structure and a subsequent ordinary run asserts the file input is absent.

This is **inline model file input**, not File Search, vector-store/RAG, `file_id`, `file_url`, external-page, database, MCP-resource, or production document-store injection.

The adapter's `resource_resolver` callback is separate: it normalizes tool-call resource identity for policy evaluation and is not the adversarial resource injector.

### Native handoff specialization

For `HANDOFF`, a fresh run-level `handoff_input_filter` modifies only the first actual transfer that invokes it, clones the SDK handoff data, preserves destination/routing identity, and records delivery only after the clone succeeds.

If no handoff occurs or the run-level filter is not invoked, no receipt exists and delivery verification blocks the trial.

## Trial derivation

`TrialRunner` executes the adapter, converts controlled precondition failures and runtime failures to distinct blocked evidence, constructs immutable `TrialEvidence`, verifies adversarial delivery, then runs deterministic policy/outcome oracles. Any deterministic failure yields `FAIL`; otherwise the trial yields `PASS`.

There is no model-authored red-team score and no rule treating absence of suspicious prose as safety evidence.

## Exact-identity replay and assurance

`EvidenceReplayAdapter` performs historical regrading, not re-execution. It refuses replay when trial, subject, or scenario identity differs and revalidates recorded delivery receipts without pretending to inject again.

`EvaluationSession`, `ReliabilityReport`, `AssuranceReport`, and `ReleaseGate` preserve blocked/evaluator uncertainty separately from behavioral failures. Critical safety evidence is non-compensatory; insufficient evidence produces `INCONCLUSIVE` rather than acceptance.

## Current boundary

The core currently provides deterministic contracts, adversarial fixtures/campaigns, evidence-bound attack-delivery verification, six concrete OpenAI delivery channels (`USER_INPUT`, local `TOOL_RESULT`, description-level `TOOL_METADATA`, session-history `MEMORY`, inline-file `RESOURCE`, first-native-handoff `HANDOFF`), identity-bound evidence, integrity-verified local persistence, exact historical replay, deterministic state/policy oracles, metamorphic relations, repeated-trial statistics, assurance reports, release gating, failure minimization, and deterministic OpenAI SDK integration tests.

The current source checkpoint is **167 passed, 9 deselected, 93.81% branch coverage**, strict mypy clean across **34 source files**, with **9/9** deterministic OpenAI SDK tests green.

Credentialed live-provider assurance, generic environment injection, production application-memory/RAG injection, hosted File Search/vector-store/URL retrieval manipulation, tool-name/parameter-schema poisoning, hosted/MCP result or metadata interception, distributed/remote handoff-fabric injection, cryptographically authenticated injector identity, target-side delivery attestation, automatic/adaptive adversarial generation, hostile-writer authenticated evidence/report signing, remote attestation, immutable remote retention, MCP fault servers, calibrated semantic graders, and automatic perturbation generation remain separate implementation layers.
